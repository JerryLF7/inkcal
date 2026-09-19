"""
Agent contract — tool schemas, decision contract, and system prompt.

This module is intentionally transport-agnostic: the same tool schemas and
decision contract can later be served as an MCP server (for fx) without
touching business logic. Only the harness (loop) changes.

Design rules:
- Tools are pure functions: args dict in -> result dict out. No loop deps.
- Decision contract is validated here; caller trusts the validated dict.
- System prompt is a single source of truth for Luna's behavior.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, replace
from typing import Any

logger = logging.getLogger("inkcal.agent_contract")


# ── tool schemas (OpenAI function-calling format) ─────────────────────

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "query_food_database",
            "description": (
                "查询本地食物热量数据库（SQLite），返回该食物最近记录的热量、"
                "宏量营养和置信度。用于估算参考，不作为最终值。参数 food_name "
                "为食物中文名（支持模糊匹配，如 '红烧肉' 会命中 '红烧肉盖饭'）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "food_name": {
                        "type": "string",
                        "description": "食物中文名（支持模糊匹配）",
                    }
                },
                "required": ["food_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_meals",
            "description": (
                "获取锚定日期及前一天的已有餐食记录（覆盖跨零点连续进食场景），"
                "用于判断新照片是否与已有记录属于同一餐。返回按拍摄时间排序的列表，"
                "每条含 asset_id、photo_time、date、meal、calories、confidence。"
                "注意：昨天的记录仅服务于跨零点场景——新照片拍摄于正常时段时，"
                "即使与昨日记录食物相同也应判为新的一餐。"
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_with_gemini",
            "description": (
                "把一组照片交给 Gemini 专家层评估热量。必须传 asset_ids（本批新照片的 "
                "asset_id 列表）。prompt_for_gemini 仅多张照片时必填，且只能描述照片之间的"
                "拍摄关系（是否同餐、先后顺序、以哪张为准、实际剩余状态），"
                "禁止包含：餐次结论（如'这是新餐'）、食物内容预判（如'主要是炸鱼排'）、"
                "纳入或排除某种食物/饮品的决定（如'不要把啤酒算进去'）——"
                "吃什么、算什么由 Gemini 依照片自行判断；单张照片时不写此参数，"
                "系统会使用内置分析模板。"
                "返回 {meal, meal_detail, calories, protein_g, carbs_g, fat_g, confidence}。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "asset_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要交给 Gemini 的照片 asset_id 列表（通常是本批照片或其子集；在 update 状态延续场景下，可包含 get_recent_meals 中已有记录的目标 asset_id 进行吃前/吃后联合对比）",
                    },
                    "prompt_for_gemini": {
                        "type": "string",
                        "description": "仅多张照片时必填：只描述照片拍摄关系与状态（同餐/顺序/以哪张为准），不得预判食物内容或决定纳入排除；单张照片省略",
                    },
                },
                "required": ["asset_ids"],
            },
        },
    },
]


# ── decision contract ────────────────────────────────────────────────

@dataclass
class Decision:
    """Validated decision from Luna. Only this shape is trusted downstream."""
    asset_ids: list[str]          # new photos covered by this decision (non-empty)
    action: str                   # "add" | "update" | "skip"
    target_asset_id: str | None   # for "update": the existing record's asset_id
    relation: str                 # "new_meal" | "same_meal" | "rejected"
    result: dict[str, Any]        # gemini result {meal, meal_detail, calories, protein_g, carbs_g, fat_g, confidence}
    reasoning: str                # Luna 的判断依据（中文）
    prompt_for_gemini: str | None # 传给 Gemini 的提示词（audit）
    group_with: str | None = None # for "add": 加入同餐组（该组主记录的 asset_id 或同批照片的 asset_id）


def validate_decision(data: dict[str, Any]) -> Decision:
    """
    Validate and parse Luna's final structured output.
    Raises ValueError on any contract violation — caller should treat as failure.
    """
    if not isinstance(data, dict):
        raise ValueError(f"decision must be dict, got {type(data).__name__}")

    action = data.get("action")
    if action not in ("add", "update", "skip"):
        raise ValueError(f"invalid action: {action!r} (must be add/update/skip)")

    asset_ids = data.get("asset_ids")
    if (
        not isinstance(asset_ids, list)
        or not asset_ids
        or not all(isinstance(a, str) and a for a in asset_ids)
    ):
        raise ValueError("asset_ids must be a non-empty list of non-empty strings")

    relation = data.get("relation")
    if relation not in ("new_meal", "same_meal", "rejected"):
        raise ValueError(f"invalid relation: {relation!r} (must be new_meal/same_meal/rejected)")

    result = data.get("result")
    if not isinstance(result, dict):
        raise ValueError("result must be a dict")
    required = ("meal", "calories", "protein_g", "carbs_g", "fat_g", "confidence")
    missing = [k for k in required if k not in result]
    if missing:
        raise ValueError(f"result missing fields: {missing}")
    if result["confidence"] not in ("high", "medium", "low"):
        raise ValueError(f"invalid confidence: {result['confidence']!r}")

    # Coerce numeric fields
    for k in ("calories", "protein_g", "carbs_g", "fat_g"):
        try:
            result[k] = float(result[k])
        except (TypeError, ValueError):
            raise ValueError(f"result.{k} must be numeric, got {result[k]!r}")

    target = data.get("target_asset_id")
    if action == "update" and not target:
        raise ValueError("action=update requires target_asset_id")

    group_with = data.get("group_with")
    if group_with is not None:
        if action != "add":
            raise ValueError("group_with is only valid for action=add")
        if not isinstance(group_with, str) or not group_with.strip():
            raise ValueError("group_with must be a non-empty asset_id string")
        group_with = group_with.strip()
        if group_with in asset_ids:
            raise ValueError("group_with must not reference this decision's own asset_ids")

    reasoning = str(data.get("reasoning", "")).strip()
    if not reasoning:
        raise ValueError("reasoning must be non-empty")

    return Decision(
        asset_ids=list(asset_ids),
        action=action,
        target_asset_id=str(target) if target else None,
        relation=relation,
        result=result,
        reasoning=reasoning,
        prompt_for_gemini=str(data.get("prompt_for_gemini", "")) or None,
        group_with=group_with,
    )


def parse_decisions_json(text: str) -> list[Decision]:
    """
    Parse Luna's final message content into a list of Decisions.

    Expected shape (envelope):
      {"decisions": [ {decision}, {decision}, ... ]}

    For backward tolerance we also accept a bare single decision object
    (no "decisions" envelope) and treat it as a one-element list.
    Handles markdown fences and truncated JSON (same tolerance as
    calorie_analyzer).
    """
    t = (text or "").strip()
    # Strip markdown code fences
    if t.startswith("```json"):
        t = t[7:]
    elif t.startswith("```"):
        t = t[3:]
    if t.endswith("```"):
        t = t[:-3]
    t = t.strip()

    # Try direct parse first
    try:
        data = json.loads(t)
    except json.JSONDecodeError:
        if not t.endswith("}"):
            # Tolerate truncated JSON missing its final closer(s).
            try:
                data = json.loads(t + "}")
            except json.JSONDecodeError:
                raise ValueError(f"invalid JSON in decision: {t[:200]}")
        else:
            # Tolerate trailing extra closers (e.g. "...}]}]}") — observed
            # from Luna on longer decisions: the envelope is complete and
            # valid, followed by stray "]}" characters. Parse the first
            # complete JSON value and ignore a pure-bracket remainder.
            try:
                data, end = json.JSONDecoder().raw_decode(t)
            except json.JSONDecodeError:
                raise ValueError(f"invalid JSON in decision: {t[:200]}")
            remainder = t[end:].strip()
            if remainder.strip("]}").strip():
                raise ValueError(f"trailing garbage in decision: {t[:200]}")

    if isinstance(data, dict) and "decisions" in data:
        items = data["decisions"]
        if not isinstance(items, list) or not items:
            raise ValueError("decisions must be a non-empty list")
        return [validate_decision(d) for d in items]

    # Bare single decision object tolerance
    if isinstance(data, dict) and "action" in data:
        return [validate_decision(data)]

    raise ValueError("expected {\"decisions\": [...]} or a single decision object")


# ── post-loop safety net (todo-2 leftover, now enforced) ─────────────

def is_all_zero_result(result: dict[str, Any]) -> bool:
    """
    True when Gemini's numeric output is all zeros — its non-real-food /
    failed-analysis marker. Mirrors the legacy pipeline's rejection check.
    """
    return all(
        float(result.get(k) or 0) == 0
        for k in ("calories", "protein_g", "carbs_g", "fat_g")
    )


def is_rejected_result(result: dict[str, Any]) -> bool:
    """True when the result itself says non-food (same set as legacy path)."""
    return str(result.get("meal", "")).strip().lower() in ("not real food", "unknown")


def enforce_zero_skip(decisions: list[Decision]) -> list[Decision]:
    """
    Unconditional mapping of "Gemini returned all-zero / not-real-food" to
    action=skip. The system prompt already asks Luna to do this itself;
    this makes it a hard guarantee at the loop boundary instead of a
    prompt-level hope.
    Returns new Decision objects; does not mutate the input.
    """
    out: list[Decision] = []
    for d in decisions:
        if d.action != "skip" and (
            is_all_zero_result(d.result) or is_rejected_result(d.result)
        ):
            note = ("系统兜底：analyze_with_gemini 返回全零或 not real food，"
                    f"action 由 {d.action} 强制改写为 skip。")
            out.append(replace(
                d,
                action="skip",
                relation="rejected",
                reasoning=f"{d.reasoning}｜{note}",
            ))
        else:
            out.append(d)
    return out


# ── system prompt ────────────────────────────────────────────────────

SYSTEM_PROMPT = """你是 inkcal 的 agent，为待处理的新食物照片做决策
（照片可能来自 cron 定时拉取，也可能来自用户在 Web 端的手动选择/上传；
两条来源都未经额外预筛，非真实食物由你判断）：
每张 add（新餐）、update（并入已有记录）或 skip（拒绝）。

## 判断规则

1. 同餐判断只看图片内容，但已有记录的时间是一票否决：跨日且非跨零点连续进食
   （深夜 23:55 与次日 00:05 的连续进食除外），即使食物完全相同也是新餐（add）。
   同日内的同餐信号：相同桌面/餐具、相同食物组合、吃剩状态的延续。
2. add / update 都需要热量数值：调用 analyze_with_gemini，把它返回的 result
   原样作为你的 result，不要自己估算。多张同餐照片一起传。
3. 照片不是真实食物（截图、包装、海报、画），或 analyze_with_gemini 返回全零 /
   "not real food"：action=skip，relation=rejected，result 全零。
4. 同餐多照片分不同形态，区别对待：
   a. 状态延续（同一份食物的吃前/吃后、不同角度，同批到达）：一条 add 决策覆盖全部照片，
      一起传 analyze_with_gemini 联合估算（以最终状态评估实际食用量）。
      系统落地为：一条主记录（带数值）+ 其余照片挂为 0 值附属行。
   b. 独立条目（同餐但各自完整的食物，如一碗面 + 一杯奶茶分开拍）：
      每张照片单独一条 add、单独传 analyze_with_gemini 估算各自的数值；
      第一条作为主记录，其余每条加 group_with=<第一条的 asset_id> 关联成同一餐。
      系统按组求和，不会重复计数。
   c. 跨批次追加独立条目（已有记录在先，新照片是同餐新增的完整食物，如餐后补拍甜点）：
      add + group_with=<已有记录的 asset_id>，新照片单独传 analyze_with_gemini 携带自己的估算数值。
      注意这与 update 不同：update 是同一食物的新状态（替换旧数值），
      add+group_with 是新增条目（各自数值相加）。
   d. 跨批次状态延续（已有记录在先，新照片是同一份食物的新状态，如吃后残局）：
      action="update", target_asset_id=<已有记录的 asset_id>。
      注意：评估实际食用量必须同时对比吃前和吃后！调用 analyze_with_gemini 时，
      必须把已有记录的照片和新照片一起传：asset_ids=[<已有记录 asset_id>, <新照片 asset_id>]，
      并在 prompt_for_gemini 中说明拍摄顺序与吃前/吃后关系（如“第一张为就餐前状态，第二张为就餐后剩余状态，请以两图对比评估实际摄入量”）。调用返回的联合估算 result 用于更新目标记录。

## 输出契约（严格遵守：只输出一个 JSON 对象，无 markdown，无解释文字）

{
  "decisions": [
    {
      "asset_ids": ["<本决策覆盖的新照片 asset_id>（仅填写待处理的新照片，不要包含已有记录的 target_asset_id）"],
      "action": "add" | "update" | "skip",
      "target_asset_id": "<仅 update 需要>",
      "group_with": "<可选，仅 add：加入同餐组的目标 asset_id（同批先决策的照片或已有记录）>",
      "relation": "new_meal" | "same_meal" | "rejected",
      "result": {
        "meal": "10字内中文标题（餐型概括，不列菜品清单）",
        "meal_detail": "中文菜品明细与份量",
        "calories": <数字>, "protein_g": <数字>,
        "carbs_g": <数字>, "fat_g": <数字>,
        "confidence": "high" | "medium" | "low"
      },
      "reasoning": "<判断逻辑链，供人工审计>",
      "prompt_for_gemini": "<仅多张照片时填写；单张照片省略>"
    }
  ]
}

每张新照片必须且只能出现在一个决策的 asset_ids 里。

## prompt_for_gemini 纪律（仅多张照片）

只写照片关系：是否同餐、拍摄顺序、以哪张为准。
禁止写入：餐次结论（"这是新餐"）、食物内容预判（"主要是炸鱼排"）、
纳入/排除决定（"不要把啤酒算进去"）——这些由 Gemini 和系统层决定。"""


# ── helpers ──────────────────────────────────────────────────────────

def build_user_prompt(assets: list[dict[str, Any]]) -> str:
    """
    Build the user prompt for Luna. assets = list of
    {asset_id, photo_time, source} for the new batch.
    """
    lines = ["以下是本次 SigLIP2 过滤出的新食物照片：", ""]
    for i, a in enumerate(assets, 1):
        lines.append(f"{i}. asset_id={a['asset_id']}  拍摄时间={a.get('photo_time', '未知')}  来源={a.get('source', 'immich')}")
    lines.append("")
    lines.append("请先查看所有照片，再调用工具做出决策。")
    return "\n".join(lines)


# ── chat (conversational agent) contract ─────────────────────────────
#
# The chat agent answers diet/calorie questions and performs corrections
# over the same SQLite business state. Separate schema set from the batch
# TOOL_SCHEMAS above: the batch loop only exposes its 3 ingest tools.

CHAT_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_records_in_range",
            "description": (
                "查询日期范围内的餐食记录（闭区间，HKT 日期 YYYY-MM-DD）。"
                "返回每条记录的 id、asset_id、photo_time、meal（短标题）、"
                "meal_detail（菜品明细）、calories、"
                "protein_g、carbs_g、fat_g、confidence。相对日期（昨天/前天/"
                "本周）请先换算成具体日期再调用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "string",
                        "description": "本次调用的具体目的（中文，5-15字，如'查询今日已有餐食确认未重复'、'查询昨日玉米作为份量参考'、'补记晚餐水煮甜玉米'），会作为执行步骤标题展示在界面上",
                    },
                    "start": {"type": "string", "description": "开始日期 YYYY-MM-DD"},
                    "end": {"type": "string", "description": "结束日期 YYYY-MM-DD"},
                },
                "required": ["start", "end"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_intake_stats",
            "description": (
                "查询日期范围内的热量与宏量营养汇总（总量 + 逐日）。"
                "适合'这周吃得怎么样''哪天热量最高'这类聚合问题。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "string",
                        "description": "本次调用的具体目的（中文，5-15字，如'查询今日已有餐食确认未重复'、'查询昨日玉米作为份量参考'、'补记晚餐水煮甜玉米'），会作为执行步骤标题展示在界面上",
                    },
                    "start": {"type": "string", "description": "开始日期 YYYY-MM-DD"},
                    "end": {"type": "string", "description": "结束日期 YYYY-MM-DD"},
                },
                "required": ["start", "end"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_meals",
            "description": (
                "按关键词搜索历史餐食记录（全文检索，支持中文模糊匹配）。"
                "适合'我最近什么时候吃过火锅'这类问题。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "string",
                        "description": "本次调用的具体目的（中文，5-15字，如'查询今日已有餐食确认未重复'、'查询昨日玉米作为份量参考'、'补记晚餐水煮甜玉米'），会作为执行步骤标题展示在界面上",
                    },
                    "keyword": {"type": "string", "description": "搜索关键词（中文食物名）"},
                    "start": {"type": "string", "description": "可选，开始日期 YYYY-MM-DD"},
                    "end": {"type": "string", "description": "可选，结束日期 YYYY-MM-DD"},
                },
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_decisions",
            "description": (
                "获取某天照片批处理的 agent 决策审计记录（action/relation/"
                "reasoning/result）。当用户问'这条记录是怎么来的''为什么这餐"
                "被合并/跳过'时使用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "string",
                        "description": "本次调用的具体目的（中文，5-15字，如'查询今日已有餐食确认未重复'、'查询昨日玉米作为份量参考'、'补记晚餐水煮甜玉米'），会作为执行步骤标题展示在界面上",
                    },
                    "date": {"type": "string", "description": "日期 YYYY-MM-DD"},
                },
                "required": ["date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_record",
            "description": (
                "直接修改一条餐食记录的字段（旧值自动留痕）。参数 record_id "
                "为记录 id（由 get_records_in_range / search_meals 返回），"
                "updates 为要改的字段子集：meal（短标题）/meal_detail（菜品明细）/"
                "calories/protein_g/carbs_g/fat_g。"
                "修改前先向用户确认理解无误。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "string",
                        "description": "本次调用的具体目的（中文，5-15字，如'查询今日已有餐食确认未重复'、'查询昨日玉米作为份量参考'、'补记晚餐水煮甜玉米'），会作为执行步骤标题展示在界面上",
                    },
                    "record_id": {"type": "integer", "description": "记录 id"},
                    "updates": {
                        "type": "object",
                        "description": "要修改的字段，如 {\"calories\": 300}",
                        "properties": {
                            "meal": {"type": "string"},
                            "meal_detail": {"type": "string"},
                            "calories": {"type": "number"},
                            "protein_g": {"type": "number"},
                            "carbs_g": {"type": "number"},
                            "fat_g": {"type": "number"},
                        },
                    },
                },
                "required": ["record_id", "updates"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_record",
            "description": (
                "仅用于手动补录【未拍照、且数据库中完全不存在】的纯文本饮食记录（如没拍照的零食、外卖、饮料或加餐）。"
                "【重要禁忌】：如果用户是在对已经拍照/已入库的餐食进行补充说明、纠错或份量修正（如'其实是玉米猪肉馅'、'一共15个'、'这是两人份'、'面只吃了一半'），"
                "绝对严禁调用此工具（否则会导致同一餐重复记录、热量双倍计算！），必须先查出该餐记录并调用 reanalyze_record。"
                "系统会自动调用 Gemini 分析食物内容并估算热量与 P/C/F 营养素，"
                "不要自己编造数值。参数包括 description（食物文字描述，如'一包乐事原味薯片约40g'）、"
                "date（日期 YYYY-MM-DD）、time（可选，时间 HH:MM，未指定时可根据上下文合理推断或留空使用当前时间）、"
                "user_calories（可选，若用户明确告知了具体热量如'200大卡'时传入）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "string",
                        "description": "本次调用的具体目的（中文，5-15字，如'查询今日已有餐食确认未重复'、'查询昨日玉米作为份量参考'、'补记晚餐水煮甜玉米'），会作为执行步骤标题展示在界面上",
                    },
                    "description": {
                        "type": "string",
                        "description": "食物与份量文字描述，如'昨天下午三点半吃了一包薯片和一瓶可乐'",
                    },
                    "date": {
                        "type": "string",
                        "description": "记录归属的当地日期 YYYY-MM-DD",
                    },
                    "time": {
                        "type": "string",
                        "description": "可选，记录时间 HH:MM（24小时制，如 15:30）",
                    },
                    "user_calories": {
                        "type": "number",
                        "description": "可选，用户在对话中明确指定的热量数值（千卡/kcal）",
                    },
                },
                "required": ["description", "date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reanalyze_record",
            "description": (
                "对一条已有餐食记录带补充说明重新分析（如'其实是玉米猪肉馅，一共15个'、'没算米饭'、'这是两人份'、'只吃了一半'），"
                "由 Gemini 结合原图与补充说明重新估算营养素并更新该记录（旧值留痕）。"
                "当用户对已拍某餐进行细节纠错、份量修正时【必须优先使用本工具，绝不要用 add_record 新建】。"
                "参数 record_id 为记录 id（通过 get_records_in_range 查到），notes 为补充说明。耗时较长，调用前告知用户。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "string",
                        "description": "本次调用的具体目的（中文，5-15字，如'查询今日已有餐食确认未重复'、'查询昨日玉米作为份量参考'、'补记晚餐水煮甜玉米'），会作为执行步骤标题展示在界面上",
                    },
                    "record_id": {"type": "integer", "description": "记录 id"},
                    "notes": {"type": "string", "description": "补充说明"},
                },
                "required": ["record_id", "notes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "request_delete_record",
            "description": (
                "请求删除一条记录。删除是破坏性操作：此工具**不会真正删除**，"
                "只生成确认卡片，由用户在界面上点击确认后才执行。调用后请告诉"
                "用户'已生成删除确认，请在卡片上确认'。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {
                        "type": "string",
                        "description": "本次调用的具体目的（中文，5-15字，如'查询今日已有餐食确认未重复'、'查询昨日玉米作为份量参考'、'补记晚餐水煮甜玉米'），会作为执行步骤标题展示在界面上",
                    },
                    "record_id": {"type": "integer", "description": "记录 id"},
                },
                "required": ["record_id"],
            },
        },
    },
]


CHAT_SYSTEM_PROMPT = """你是 inkcal 的饮食助手 Calo，正在与用户对话。当前时间：{now}（HKT）。

用户的食物照片由后台 pipeline 自动分析入库，你可以通过工具查询和修改这些记录。

## 工具调用目的（intent 参数）

调用任何工具时，**必须在 `intent` 参数中用简明中文（5-15字）写明本次调用的具体目的**，
例如「查询今日已有餐食确认未重复」「查询昨日玉米作为份量参考」「补记晚餐水煮甜玉米」。
该文字会直接作为执行步骤的标题展示在用户界面上，让查询与操作链路清晰透明。
不要写函数名式的描述，要写清楚"为什么调用这次工具"。

## 工具使用原则

- 涉及具体饮食事实的问题**必须查工具**，不要凭记忆或猜测回答。对话窗口之外的内容你记不住，但 SQLite 里都有，随时现查。
- 相对日期先换算成具体日期：今天是 {today}。
- 一次问题可能需要多次工具调用（如对比两天 = 查两次或一次范围查询）。

## 工具使用原则

- 涉及具体饮食事实的问题**必须查工具**，不要凭记忆或猜测回答。对话窗口之外的内容你记不住，但 SQLite 里都有，随时现查。
- 相对日期先换算成具体日期：今天是 {today}。
- 一次问题可能需要多次工具调用（如对比两天 = 查两次或一次范围查询）。

## 核心意图消歧规则：纠错补充（改/重估） vs 纯文本补录（增）

用户的食物通常由手机拍照自动入库。很多对话是用户对已拍某餐的**纠错或细节补充**，绝不能草率调用 add_record 导致同一餐被重复记录、热量双倍计算！

1. **纠错与补充已有餐食（严禁直接 add_record，必须先查后改）**：
   - 典型特征：提及某个具体餐次或指示代词（如“今晚的...”、“刚才那顿...”、“中午的面...”），或包含细节修正常用语（如“其实是...”、“一共15个”、“是玉米猪肉馅”、“这是两人份”、“只吃了一半”、“没算米饭”）。
   - **执行路径**：
     a. **必须先调用 `get_records_in_range`** 查询对应日期与餐次的已有记录；
     b. 若找到了对应记录，**绝对不要调用 add_record**！
        - 若属于食物配料/份量/个数等细节修正（如“今晚的饺子一共15个，玉米猪肉馅”），调用 `reanalyze_record(record_id, notes)` 让 Gemini 结合原图与补充说明重新评估整餐并更新该记录；
        - 若属于用户强制指定明确数字或名称（如“把今晚的热量改成500”），调用 `edit_record(record_id, updates)`；
     c. 只有在检索后确认该餐次在库里完全空白（用户确认没拍照），才作为新记录补录。

2. **纯文本补录新记录（add_record）**：
   - 典型特征：用户明确表达补记未拍照的加餐/零食/饮料（如“记一下，刚才吃了包薯片”、“下午喝了杯奶茶没拍照，帮我记下”）。
   - 确认该时间点不存在同类已有记录后，调用 add_record 由 Gemini 估算落库。

## 写操作规则

- reanalyze_record / edit_record / add_record 可以直接执行。执行前用一句话向用户告知你理解的需求（在同一条回复里说明即可，无需等待）。
- 删除记录只能调用 request_delete_record 生成确认卡片，绝不承诺"已删除"。
- 所有写操作都会留痕审计，操作后告知用户结果。

## 回答风格

- 简洁口语化，像朋友聊天，不要列长篇表格除非用户要求。
- 数字从工具结果来，不要自己估算热量（你没有这个能力）。
- 工具查不到就如实说"没有找到记录"，并建议可能的原因（那天没拍照？被过滤了？）。"""