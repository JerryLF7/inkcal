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
    Return today's meal records (the current session's existing entries),
    ordered by photo_time. Used by Luna to judge whether a new photo belongs
    to an existing meal.

    NOTE: "today" is derived from the newest asset's photo_time (the batch
    being processed), so the session is anchored to the photos, not to wall
    clock — this makes it safe for backfill runs on historical dates.
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

    records = db.get_records_by_date(anchor_date)
    meals = []
    for r in records:
        meals.append({
            "asset_id": r.get("asset_id"),
            "photo_time": r.get("photo_time"),
            "meal": r.get("meal"),
            "calories": r.get("calories"),
            "protein_g": r.get("protein_g"),
            "carbs_g": r.get("carbs_g"),
            "fat_g": r.get("fat_g"),
            "confidence": r.get("confidence"),
        })
    # Sort by photo_time for stable "which came first" reading
    meals.sort(key=lambda m: m.get("photo_time") or "")
    logger.info("get_recent_meals(anchor=%s) -> %d meals", anchor_date, len(meals))
    return {"ok": True, "anchor_date": anchor_date, "meals": meals}


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

    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
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
