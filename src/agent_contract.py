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
                "asset_id 列表）和 prompt_for_gemini（你写的辅助提示词，说明照片关系与"
                "实际食用判断）。返回 {meal, calories, protein_g, carbs_g, fat_g, confidence}。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "asset_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要交给 Gemini 的照片 asset_id 列表（通常是本批全部，或你判断属于同一餐的子集）",
                    },
                    "prompt_for_gemini": {
                        "type": "string",
                        "description": "给 Gemini 的辅助提示词，说明照片关系与实际食用判断",
                    },
                },
                "required": ["asset_ids", "prompt_for_gemini"],
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
    result: dict[str, Any]        # gemini result {meal, calories, protein_g, carbs_g, fat_g, confidence}
    reasoning: str                # Luna 的判断依据（中文）
    prompt_for_gemini: str | None # 传给 Gemini 的提示词（audit）


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
            try:
                data = json.loads(t + "}")
            except json.JSONDecodeError:
                raise ValueError(f"invalid JSON in decision: {t[:200]}")
        else:
            raise ValueError(f"invalid JSON in decision: {t[:200]}")

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

SYSTEM_PROMPT = """你是 inkcal 的 agent，负责判断 SigLIP2 过滤出的食物照片该如何处理。

你的输入：一批新食物照片（带 asset_id 和拍摄时间），以及可调用的工具。
你的目标：为这批照片做出决策——每张是新的一餐（add）、还是与已有记录同餐（update）、还是应当拒绝（skip）。

## 判断规则

1. 同餐判断**只看图片内容**、不看时间间隔——这条规则只适用于**同一批内多张照片之间的分组**。对已有记录判断 same_meal 时，时间必须是硬约束：
   - get_recent_meals 返回的列表可能包含昨天的记录，它们**只服务于跨零点场景**（深夜 23:55 与次日 00:05 的连续进食）。
   - 新照片若拍摄于正常时段（上午/中午/傍晚等），与昨天的记录**即使食物完全相同也一律判新的一餐**（add/new_meal），绝不用 update 去合并。
   - 先比对每条记录的 date 字段与新照片的日期：跨日且不是零点前后的连续进食，就不可能同餐。
   - 同餐的信号（限同一餐时段内）：相同桌面/餐具、相同食物组合、吃剩状态的延续（如：第一张全量，第二张某食物变少）。
   - 不同餐的信号：完全不同的桌面、完全不同的食物、明显是两次独立进食。
2. 如果是**同餐**，决定以哪张照片为准（通常是最后一张，显示最终剩余状态），然后调用 analyze_with_gemini，把相关照片都传给它，并写清实际食用部分。
   - 例：三张照片 A+B → A+½B+C → ½A+B空盘+C，实际食用是 B+½A，C 是后加的背景不算。
   - prompt_for_gemini 要明确告诉它："以图三为准，前两张是同一餐的先前状态，实际食用部分是 B+½A"。
3. 如果是**新的一餐**，直接调用 analyze_with_gemini（单张或少量相关照片），prompt 里说明这是新餐。
4. 如果照片**不是真实食物**（截图、包装、海报、画），用 action=skip，relation=rejected，result 给全零，reasoning 说明为何拒绝。

## 输出契约（必须严格遵守）

最终必须只输出一个 JSON 对象（外层是 decisions 数组），不要 markdown 代码块，不要解释性文字：

{
  "decisions": [
    {
      "asset_ids": ["<本决策覆盖的新照片 asset_id 列表>"],
      "action": "add" | "update" | "skip",
      "target_asset_id": "<已有记录的 asset_id，仅 update 需要>",
      "relation": "new_meal" | "same_meal" | "rejected",
      "result": {
        "meal": "简短中文食物描述",
        "calories": <数字>,
        "protein_g": <数字>,
        "carbs_g": <数字>,
        "fat_g": <数字>,
        "confidence": "high" | "medium" | "low"
      },
      "reasoning": "你的判断依据（中文，说明为什么是同餐/新餐/拒绝，以及实际食用判断）",
      "prompt_for_gemini": "<你传给 Gemini 的辅助提示词>"
    }
  ]
}

规则：
- 一批可能有多个决策（如三张照片：两张同餐 update，一张新餐 add）。每张新照片必须且只能出现在一个决策的 asset_ids 里。
- 一个决策的 asset_ids 可以是多张（同餐的多张一起交给 Gemini）。

## 工具使用

- 你可以随时调用 query_food_database 查询历史同款食物的热量做参考。
- 调用 analyze_with_gemini 前，先在 reasoning 里想好判断。
- analyze_with_gemini 的 result 就是你最终 result 的来源——不要自己估热量，直接采用 Gemini 的返回值。

## 注意

- 结果必须基于 analyze_with_gemini 的真实返回。如果它返回了全零或 "not real food"，那很可能是图片格式错误或非食物，你应当用 action=skip 而不是 add。
- 你的 reasoning 会被人工审计，写清楚逻辑链。"""


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