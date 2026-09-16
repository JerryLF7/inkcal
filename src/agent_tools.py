"""
Agent tools — pure function implementations.

MCP-ready interface: each tool is a pure function `on_call(args) -> dict`
with no knowledge of the agent loop, transport, or storage. This makes them
directly reusable by:
  - the hand-rolled harness (today)
  - an MCP server wrapper (future, for fx or other MCP clients)
  - unit tests (today)

All dependencies (db, immich, gemini) are injected via `deps` dict.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("inkcal.agent_tools")


# ── image MIME detection (shared with harness) ───────────────────────

def detect_image_mime(data: bytes) -> str:
    """
    Detect image MIME type from magic bytes. Falls back to image/jpeg.
    Used to build correc URLs for Luna/Gemini (both are strict:
    a wrong MIME prefix can cause silent 'no image' rejections).
    """
    if not data:
        return "image/jpeg"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"\x89PNG":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand in (b"heic", b"heix", b"hevc", b"hevx", b"mif1"):
            return "image/heic"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "image/jpeg"


# ── query_food_database ──────────────────────────────────────────────

def query_food_database(args: dict, deps: dict) -> dict:
    """
    Query local SQLite food database for historical records matching a food name.
    Returns recent matches (up to 3) with calories/macros/confidence.
    """
    from src import db  # lazy import to keep this module importable standalone

    food_name = str(args.get("food_name", "")).strip()
    if not food_name:
        return {"ok": False, "error": "food_name is required"}

    matches = db.search_records(food_name, limit=3)
    out = []
    for r in matches:
        out.append({
            "meal": r.get("meal"),
            "calories": r.get("calories"),
            "protein_g": r.get("protein_g"),
            "carbs_g": r.get("carbs_g"),
            "fat_g": r.get("fat_g"),
            "confidence": r.get("confidence"),
            "photo_time": r.get("photo_time"),
        })
    logger.info("query_food_database('%s') -> %d matches", food_name, len(out))
    return {"ok": True, "matches": out}


# ── get_recent_meals ─────────────────────────────────────────────────

def get_recent_meals(args: dict, deps: dict) -> dict:
    """
    Return existing meal records around the batch's anchor date (anchor day
    plus the day before), ordered by photo_time. Used by Luna to judge
    whether a new photo belongs to an existing meal.

    The window covers cross-midnight meals (23:55 + next-day 00:05 photos):
    the anchor is derived from the newest asset's photo_time, so without
    looking back one day, a just-after-midnight photo could never see the
    late-night meal it belongs to. Grouping itself remains image-based.
    """
    from src import db

    assets = deps.get("assets", [])
    if not assets:
        return {"ok": True, "meals": [], "note": "no assets in batch"}

    # Anchor date = newest asset's date (HKT)
    latest = max(assets, key=lambda a: a.get("photo_time", ""))
    anchor_date = (latest.get("photo_time") or "")[:10]  # YYYY-MM-DD
    if not anchor_date:
        return {"ok": False, "error": "cannot determine anchor date from assets"}

    try:
        from datetime import date as _date, timedelta as _timedelta

        prev_date = (_date.fromisoformat(anchor_date)
                     - _timedelta(days=1)).isoformat()
    except ValueError:
        prev_date = anchor_date

    records = db.get_records_by_date_range(prev_date, anchor_date)
    meals = []
    for r in records:
        pt = r.get("photo_time") or ""
        meals.append({
            "asset_id": r.get("asset_id"),
            "photo_time": pt,
            "date": pt[:10],  # explicit for cross-day reasoning
            "meal": r.get("meal"),
            "meal_detail": r.get("meal_detail", ""),
            "calories": r.get("calories"),
            "protein_g": r.get("protein_g"),
            "carbs_g": r.get("carbs_g"),
            "fat_g": r.get("fat_g"),
            "confidence": r.get("confidence"),
        })
    # Sort by photo_time for stable "which came first" reading
    meals.sort(key=lambda m: m.get("photo_time") or "")
    logger.info("get_recent_meals(window=%s..%s) -> %d meals",
                prev_date, anchor_date, len(meals))
    return {"ok": True, "window": [prev_date, anchor_date], "meals": meals}


# ── analyze_with_gemini ──────────────────────────────────────────────

def analyze_with_gemini(args: dict, deps: dict) -> dict:
    """
    Send a batch of photos to Gemini expert layer.
    args:
      asset_ids: list[str] — photos to send
      prompt_for_gemini: str — REQUIRED for multi-photo calls; describes
        photo relations only. OPTIONAL and IGNORED for single-photo calls
        (the tool substitutes the shipped analyze.md template — Luna prose
        for a single photo is pure boilerplate and a content-smuggling
        channel).
    deps must contain:
      gemini_analyzer: CalorieAnalyzer instance
      image_getter: callable(asset_id) -> bytes (original image bytes)
    """
    analyzer = deps.get("gemini_analyzer")
    image_getter = deps.get("image_getter")
    if analyzer is None or image_getter is None:
        return {"ok": False, "error": "missing gemini_analyzer or image_getter in deps"}

    asset_ids = args.get("asset_ids") or []
    prompt = str(args.get("prompt_for_gemini", "")).strip()
    if not asset_ids:
        return {"ok": False, "error": "asset_ids must be non-empty"}
    if len(asset_ids) > 1 and not prompt:
        return {"ok": False, "error": "prompt_for_gemini is required for multi-photo calls"}

    images: list[bytes] = []
    for aid in asset_ids:
        try:
            images.append(image_getter(aid))
        except Exception as e:
            logger.error("image_getter failed for %s: %s", aid, e)
            return {"ok": False, "error": f"failed to fetch image for {aid}: {e}"}

    if len(images) == 1 and prompt:
        logger.info("analyze_with_gemini: single-photo call, ignoring prompt_for_gemini (%d chars)",
                    len(prompt))

    # Call Gemini with images + assembled prompt.
    # The analyzer's analyze() takes a single image; for multi-image we call
    # the underlying client directly with all images in one request.
    try:
        result = _gemini_multi_image(analyzer, images, prompt)
        logger.info(
            "analyze_with_gemini: %d images -> meal=%s calories=%s",
            len(images), result.get("meal"), result.get("calories"),
        )
        return {"ok": True, "result": result}
    except Exception as e:
        logger.error("analyze_with_gemini failed: %s", e)
        return {"ok": False, "error": f"gemini analysis failed: {e}"}


def _gemini_multi_image(analyzer, images: list[bytes], prompt: str) -> dict:
    """
    Send multiple images + prompt to Gemini in one request.
    Reuses the analyzer's OpenAI client and JSON parsing.

    Prompt layout (order matters — task frame first, Luna's notes after):
      1. TASK_FRAME: fixed numeric-estimation rules owned by THIS layer.
         Luna must not and cannot change these (e.g. 2026-08-31 dinner:
         Luna excluded a beer; drinks are part of intake and must count).
      2. Body:
         - single photo -> shipped analyze.md template (same text as the
           manual-upload / legacy path; NOT the user-overridable variant —
           see loader note below). Luna's prompt_for_gemini is ignored for
           single-photo calls.
         - multiple photos -> Luna's prompt_for_gemini (photo relations
           ONLY: same-meal links, order, which photo shows the final
           state). No meal-type verdicts, no content pre-judgement, no
           include/exclude decisions.
      3. format_anchor: JSON output contract pinned last, closest to
         generation.
    """
    import base64

    from src.prompts import loader as prompt_loader

    # Fixed task frame: what to include, how to treat ambiguity, and that
    # the model must judge content itself from visible evidence. Principle:
    # over-count (user can correct via reanalyze) beats under-count
    # (invisible loss). Same rules as src/prompts/analyze.md, adapted for
    # multi-photo + Luna-annotated batches.
    task_frame = (
        "你是营养师，任务是只根据照片可见证据估算这一餐的热量与宏量营养。"
        "下面附带的辅助说明仅描述照片之间的拍摄关系（是否同餐、先后顺序、以哪张为准），"
        "其中对食物内容的预判不作为你的依据——请自己从图片判断吃了什么。\n\n"
        "纳入规则（必须遵守）：\n"
        "1. 全摄入基准：凡照片中出现的、属于本次进食的食物和饮品一律计入热量与宏量营养，"
        "包括酒水、饮料、咖啡、奶茶等（此类常被漏算，请特别注意）。\n"
        "2. 仅排除明确不属于本次进食的物品：外卖盒外的包装盒、手机、电脑、"
        "他人未入食的餐食、餐桌装饰等非摄入物。\n"
        "3. 拿不准某物品是否被食用时，计入并调低 confidence——宁可多算让人工纠正，"
        "不可漏算。\n"
        "4. 多张照片时以最终状态（最后一张或剩余最少的状态）评估实际食用量，"
        "未动过的重复出镜物品只算一次。\n"
        "5. 估算保持保守：按常见份量常识，不放大也不缩小。\n"
        "6. 若发现是截图、包装、菜单、海报、绘画、屏幕里的食物等非真实食物，"
        "所有数值置 0 且 meal=\"not real food\"、meal_detail=\"\"。"
        "\n"
        "标题规则（必须遵守）：meal 是卡片标题——10 字以内的餐型/形态概括"
        "（如「中式外卖盒饭」「海带猪蹄汤配米饭」），不要把菜品清单堆进去；"
        "meal_detail 写具体菜品明细与大致份量/食用比例（如「白米饭，炸鸡块，"
        "青椒炒肉丝（食用约四分之三）」），但不重复 meal 已点名的主菜。"
    )

    # Pin the output contract at the very end, closest to generation:
    # long analytical instructions were observed to pull Gemini into
    # markdown essays that fail JSON parsing.
    format_anchor = (
        "\n\n重要：无论上面的分析要求是什么，最终只返回一个 JSON 对象，"
        "不要输出任何解释文字或 markdown 代码块。字段必须严格为："
        '{"meal": "10字内中文标题", "meal_detail": "中文菜品明细（不重复标题已点名的菜）", '
        '"calories": <数字>, "protein_g": <数字>, '
        '"carbs_g": <数字>, "fat_g": <数字>, "confidence": "high|medium|low"}。'
        '若不是真实食物，所有数值置 0 且 meal="not real food"、meal_detail=""、confidence="low"。'
    )

    # Single photo: use the shipped analyze.md template so the loop path and
    # the manual-upload/legacy path run the SAME prompt. Deliberately the
    # packaged default (not get_analyze_prompt()): the user-override slot
    # exists for tuning, and system invariants must not depend on it —
    # task_frame + format_anchor already pin the hard rules either way.
    if len(images) == 1:
        body = prompt_loader.load_packaged_analyze()
        text = task_frame + "\n\n" + body + format_anchor
    else:
        # Pin the output contract at the very end, closest to generation:
        # long analytical instructions were observed to pull Gemini into
        # markdown essays that fail JSON parsing.
        text = task_frame + "\n\n——以下为照片关系说明——\n" + prompt + format_anchor

    content: list[dict[str, Any]] = [{"type": "text", "text": text}]
    for img in images:
        b64 = base64.b64encode(img).decode("utf-8")
        mime = detect_image_mime(img)
        data_url = f"{mime};base64,{b64}"
        content.append({"type": "image_url", "image_url": {"url": data_url}})

    r = analyzer._client.chat.completions.create(
        model=analyzer.model,
        messages=[{"role": "user", "content": content}],
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    return analyzer._parse_response(r)


# ── tool registry (name -> callable) ─────────────────────────────────

TOOLS = {
    "query_food_database": query_food_database,
    "get_recent_meals": get_recent_meals,
    "analyze_with_gemini": analyze_with_gemini,
}


def call_tool(name: str, args: dict, deps: dict) -> dict:
    """Dispatch a tool call by name. Returns a result dict (never raises)."""
    fn = TOOLS.get(name)
    if fn is None:
        logger.warning("unknown tool: %s", name)
        return {"ok": False, "error": f"unknown tool: {name}"}
    try:
        return fn(args, deps)
    except Exception as e:
        logger.exception("tool %s raised", name)
        return {"ok": False, "error": f"tool {name} error: {e}"}


# ── chat tools (conversational agent) ────────────────────────────────
#
# Same pure-function contract as the batch tools above. deps carries
# "pipeline_config" (immich/photoprism/gemini settings) for write tools
# that need the analyzer.

def _record_brief(r: dict) -> dict:
    """Trim a db record to the fields useful in conversation context."""
    return {k: r.get(k) for k in (
        "id", "asset_id", "photo_time", "meal", "meal_detail", "calories",
        "protein_g", "carbs_g", "fat_g", "confidence",
        "thumbnail_url", "replacement_image",
    )}


def _group_brief(r: dict) -> dict:
    """Brief of a PRIMARY record plus its photo/sub-item rows (同餐组).

    photos 按拍摄时间排序，含主行自己；独立条目形态的从行携带自己的
    meal/数值，状态延续形态的从行为 0 值。
    """
    b = _record_brief(r)
    b["photos"] = [{k: p.get(k) for k in
                    ("asset_id", "photo_time", "meal", "meal_detail", "calories",
                     "thumbnail_url", "replacement_image")}
                   for p in r.get("photos", [])]
    return b


def _resolve_primary(rec: dict) -> dict:
    """若传入的是同餐组从行，解析到组的主记录（写操作只作用于主记录）。"""
    from src import db

    if rec.get("merged_into"):
        root = db.get_record_by_asset_id(rec["merged_into"])
        if root:
            return root
    return rec


def get_records_in_range(args: dict, deps: dict) -> dict:
    from src import db

    start = str(args.get("start", "")).strip()
    end = str(args.get("end", "")).strip()
    if not start or not end:
        return {"ok": False, "error": "start and end are required (YYYY-MM-DD)"}
    records = db.get_records_by_date_range(start, end)
    grouped = db.group_meals(records)
    return {"ok": True, "count": len(grouped),
            "records": [_group_brief(r) for r in grouped]}


def get_intake_stats(args: dict, deps: dict) -> dict:
    from src import db

    start = str(args.get("start", "")).strip()
    end = str(args.get("end", "")).strip()
    if not start or not end:
        return {"ok": False, "error": "start and end are required (YYYY-MM-DD)"}
    records = db.get_records_by_date_range(start, end)
    by_day: dict[str, list[dict]] = {}
    for r in records:
        by_day.setdefault((r.get("photo_time") or "")[:10], []).append(r)
    return {
        "ok": True,
        "total": db.summarize_records(records),
        "by_day": {d: db.summarize_records(rs) for d, rs in sorted(by_day.items())},
    }


def search_meals(args: dict, deps: dict) -> dict:
    from src import db

    keyword = str(args.get("keyword", "")).strip()
    if not keyword:
        return {"ok": False, "error": "keyword is required"}
    records = db.search_records(
        keyword,
        start_date=str(args.get("start", "")).strip() or None,
        end_date=str(args.get("end", "")).strip() or None,
        limit=10,
    )
    # 命中从行时归并到组主记录，一餐只出现一次
    roots: dict[str, dict] = {}
    for r in records:
        root_id = db.resolve_group_root(r["asset_id"])
        root = db.get_record_by_asset_id(root_id)
        if root:
            roots.setdefault(root_id, root)
    grouped = db.group_meals(list(roots.values()))
    return {"ok": True, "count": len(grouped),
            "records": [_group_brief(r) for r in grouped]}


def get_decisions(args: dict, deps: dict) -> dict:
    from src import db

    date_str = str(args.get("date", "")).strip()
    if not date_str:
        return {"ok": False, "error": "date is required (YYYY-MM-DD)"}
    decisions = db.get_decisions_by_date(date_str)
    # Trim to conversation-useful fields
    brief = [{
        "action": d.get("action"),
        "relation": d.get("relation"),
        "asset_ids": d.get("asset_ids"),
        "target_asset_id": d.get("target_asset_id"),
        "reasoning": d.get("reasoning"),
        "result": d.get("result"),
    } for d in decisions]
    return {"ok": True, "count": len(brief), "decisions": brief}


def edit_record(args: dict, deps: dict) -> dict:
    from src import db

    record_id = args.get("record_id")
    updates = args.get("updates") or {}
    if not record_id or not isinstance(updates, dict) or not updates:
        return {"ok": False, "error": "record_id and non-empty updates are required"}

    rec = db.get_record_by_id(int(record_id))
    if not rec:
        return {"ok": False, "error": f"record {record_id} not found"}
    rec = _resolve_primary(rec)

    allowed = {"meal", "meal_detail", "calories", "protein_g", "carbs_g", "fat_g"}
    clean = {k: v for k, v in updates.items() if k in allowed}
    if not clean:
        return {"ok": False, "error": f"no editable fields in updates (allowed: {sorted(allowed)})"}

    before = _record_brief(rec)
    db.update_record(rec["asset_id"], clean)
    after = db.get_record_by_id(int(record_id))
    return {"ok": True, "before": before, "after": _record_brief(after)}


def reanalyze_record_tool(args: dict, deps: dict) -> dict:
    from src import db
    from src.pipeline_ops import reanalyze_record

    record_id = args.get("record_id")
    notes = str(args.get("notes", "")).strip()
    if not record_id or not notes:
        return {"ok": False, "error": "record_id and notes are required"}

    rec = db.get_record_by_id(int(record_id))
    if not rec:
        return {"ok": False, "error": f"record {record_id} not found"}
    rec = _resolve_primary(rec)

    config = deps.get("pipeline_config")
    if not config:
        return {"ok": False, "error": "pipeline_config missing in deps"}

    updated = reanalyze_record(rec["asset_id"], notes, config)
    if updated is None:
        return {"ok": False, "error": "image unavailable or analysis failed"}
    return {"ok": True, "before": _record_brief(rec),
            "after": _record_brief(updated)}


def request_delete_record(args: dict, deps: dict) -> dict:
    """Never deletes. Returns a confirmation-card payload; the actual
    deletion happens only when the user clicks the card, via the existing
    DELETE /api/record endpoint (which handles ignore-list side effects)."""
    from src import db

    record_id = args.get("record_id")
    if not record_id:
        return {"ok": False, "error": "record_id is required"}
    rec = db.get_record_by_id(int(record_id))
    if not rec:
        return {"ok": False, "error": f"record {record_id} not found"}
    rec = _resolve_primary(rec)
    return {
        "ok": True,
        "requires_confirmation": True,
        "confirm_card": {
            "kind": "delete_record",
            "record_id": rec["id"],
            "asset_id": rec["asset_id"],
            "meal": rec["meal"],
            "calories": rec["calories"],
            "photo_time": rec["photo_time"],
        },
    }


CHAT_TOOLS = {
    "get_records_in_range": get_records_in_range,
    "get_intake_stats": get_intake_stats,
    "search_meals": search_meals,
    "get_decisions": get_decisions,
    "edit_record": edit_record,
    "reanalyze_record": reanalyze_record_tool,
    "request_delete_record": request_delete_record,
}


def call_chat_tool(name: str, args: dict, deps: dict) -> dict:
    """Dispatch one chat tool call. Returns a result dict (never raises)."""
    fn = CHAT_TOOLS.get(name)
    if fn is None:
        logger.warning("unknown chat tool: %s", name)
        return {"ok": False, "error": f"unknown tool: {name}"}
    try:
        return fn(args, deps)
    except Exception as e:
        logger.exception("chat tool %s raised", name)
        return {"ok": False, "error": f"tool {name} error: {e}"}
