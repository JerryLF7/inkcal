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
    Send a batch of photos to Gemini expert layer with Luna's prompt.
    args:
      asset_ids: list[str] — subset of the batch's asset_ids to send
      prompt_for_gemini: str — Luna's auxiliary prompt describing relations
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
    if not prompt:
        return {"ok": False, "error": "prompt_for_gemini must be non-empty"}

    images: list[bytes] = []
    for aid in asset_ids:
        try:
            images.append(image_getter(aid))
        except Exception as e:
            logger.error("image_getter failed for %s: %s", aid, e)
            return {"ok": False, "error": f"failed to fetch image for {aid}: {e}"}

    # Call Gemini with multi-image + Luna's prompt.
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
    """
    import base64

    # Luna's prompt_for_gemini describes WHAT to analyze, but says nothing
    # about output format — long analytical instructions were observed to
    # pull Gemini into markdown essays that fail JSON parsing. Pin the
    # output contract at the end of the prompt, closest to generation.
    format_anchor = (
        "\n\n重要：无论上面的分析要求是什么，最终只返回一个 JSON 对象，"
        "不要输出任何解释文字或 markdown 代码块。字段必须严格为："
        '{"meal": "中文简述", "calories": <数字>, "protein_g": <数字>, '
        '"carbs_g": <数字>, "fat_g": <数字>, "confidence": "high|medium|low"}。'
        '若不是真实食物，所有数值置 0 且 meal="not real food"、confidence="low"。'
    )
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt + format_anchor}]
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
        "id", "asset_id", "photo_time", "meal", "calories",
        "protein_g", "carbs_g", "fat_g", "confidence",
    )}


def get_records_in_range(args: dict, deps: dict) -> dict:
    from src import db

    start = str(args.get("start", "")).strip()
    end = str(args.get("end", "")).strip()
    if not start or not end:
        return {"ok": False, "error": "start and end are required (YYYY-MM-DD)"}
    records = db.get_records_by_date_range(start, end)
    return {"ok": True, "count": len(records),
            "records": [_record_brief(r) for r in records]}


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
    return {"ok": True, "count": len(records),
            "records": [_record_brief(r) for r in records]}


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

    allowed = {"meal", "calories", "protein_g", "carbs_g", "fat_g"}
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
