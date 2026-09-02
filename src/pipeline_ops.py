"""Pipeline operations shared by CLI and web server.

Functions that were previously only available through web endpoints
are extracted here so both CLI (inkcal analyze/reanalyze) and Flask
can call the same logic.
"""

import io
import logging
import os
from dataclasses import replace
from datetime import datetime, timezone, timedelta
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)

HKT = timezone(timedelta(hours=8))
DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def analyze_asset(
    asset_id: str,
    source: str,
    config: dict,
    photo_time: str = "",
    thumbnail_url: str = "",
    image_bytes: bytes | None = None,
) -> tuple[dict | None, str | None]:
    """Download original from photo source, run Gemini (skip food detection),
    save record, and remove from classified_non_food.

    image_bytes: optional pre-downloaded original (used by the agent-path
    fallback in web/server.py to avoid a second download).

    Returns (record, error) tuple.  On success error is None.
    Error values: "already_processed", "download_failed", "not_food", "analysis_failed".
    """
    from src import db
    from src.calorie_analyzer import CalorieAnalyzer

    # Race-condition guard
    if db.get_record_by_asset_id(asset_id):
        logger.warning("Asset %s already processed", asset_id[:8])
        return None, "already_processed"

    if image_bytes is None:
        image_bytes = _download_original(asset_id, source, config)
    if not image_bytes:
        logger.error("Failed to download original for %s [%s]", asset_id[:8], source)
        return None, "download_failed"

    # Resolve real photo time from source metadata if caller didn't supply it
    if not photo_time:
        photo_time = _resolve_photo_time(asset_id, source, config)

    analyzer = CalorieAnalyzer(
        config.get("gemini_key", ""),
        base_url=config.get("gemini_base_url"),
        model=config.get("gemini_model", "gemini-3-flash-preview"),
    )
    result = analyzer.analyze(image_bytes)
    analyzer.close()

    if result.get("meal") == "not real food":
        logger.info("Gemini rejected %s as non-food", asset_id[:8])
        return None, "not_food"

    if result.get("meal") == "unknown":
        logger.warning("Gemini analysis failed for %s (returned unknown)", asset_id[:8])
        return None, "analysis_failed"

    # Build thumbnail URL for the record (unless caller provided one)
    if not thumbnail_url:
        if source == "immich":
            immich_url = config.get("immich_url", "").rstrip("/")
            thumbnail_url = f"{immich_url}/api/assets/{asset_id}/thumbnail?size=preview"
        elif source == "photoprism":
            photoprism_url = config.get("photoprism_url", "").rstrip("/")
            thumbnail_url = f"{photoprism_url}/api/v1/t/{asset_id}/tile_224"

    record = {
        "asset_id": asset_id,
        "source_type": source,
        "source_id": asset_id,
        "photo_time": photo_time or datetime.now(HKT).isoformat(),
        "thumbnail_url": thumbnail_url,
        "meal": result.get("meal", "unknown"),
        "calories": result.get("calories", 0),
        "protein_g": result.get("protein_g", 0),
        "carbs_g": result.get("carbs_g", 0),
        "fat_g": result.get("fat_g", 0),
        "confidence": result.get("confidence", "low"),
        "analyzed_at": datetime.now(HKT).isoformat(),
    }
    db.insert_record(record)
    db.remove_classified_non_food(asset_id)

    return record, None


# ── Luna agent path (manual photos, plan B) ───────────────────────────

def analyze_assets_via_agent(
    assets: list[dict],
    config: dict,
    run_id: str = "",
) -> tuple[list[dict] | None, list[str], str | None]:
    """Run a manual-photo batch through Luna's harness (skips SigLIP2).

    Used by /api/analyze-album-photo, /api/manual-upload and `inkcal analyze`
    when AGENT_ENABLED=1. Photos bypass the local food detector (user picked
    them explicitly) but stay subject to Luna's skip contract (screenshots,
    menus etc. are still rejected).

    assets: list of {asset_id, source, photo_time, image_bytes, thumbnail_url}
    config: same dict shape as analyze_asset() plus LUNA_* env handling here.

    Returns (records, skipped_ids, fallback_reason):
      records        — newly inserted record dicts (add decisions; update is
                       downgraded to add because manual photos have no
                       pre-existing record to merge into)
      skipped_ids    — asset_ids Luna rejected (already written to
                       classified_non_food with decided_by="agent")
      fallback_reason — None on success; "harness_failed" / "luna_unavailable"
                       / "partial:<n>" when the caller must retry via the
                       legacy per-photo path.
    """
    from src import db
    from src.calorie_analyzer import CalorieAnalyzer
    from src.agent_harness import AgentHarness

    if not assets:
        return [], [], None

    luna_api_key = os.getenv("LUNA_API_KEY", "")
    if not luna_api_key:
        logger.warning("agent path skipped: LUNA_API_KEY not configured")
        return None, [], "luna_unavailable"

    # Pre-filter photos that somehow got recorded between picker load and
    # this call (same race the cron path guards against).
    pending = []
    for a in assets:
        if db.get_record_by_asset_id(a["asset_id"]):
            logger.warning("agent path: %s already processed, dropping",
                           a["asset_id"][:8])
            continue
        pending.append(a)
    if not pending:
        return [], [], None

    analyzer = CalorieAnalyzer(
        config.get("gemini_key", ""),
        base_url=config.get("gemini_base_url"),
        model=config.get("gemini_model", "gemini-3-flash-preview"),
    )

    def image_getter(asset_id: str) -> bytes:
        for a in pending:
            if a["asset_id"] == asset_id:
                return a["image_bytes"]
        raise KeyError(asset_id)

    harness = AgentHarness(
        luna_api_key=luna_api_key,
        luna_base_url=os.getenv("LUNA_BASE_URL") or None,
        luna_model=os.getenv("LUNA_MODEL", "gpt-5.6-luna"),
        deps={"gemini_analyzer": analyzer},
    )

    luna_assets = [{
        "asset_id": a["asset_id"],
        "photo_time": a.get("photo_time", ""),
        "source": a.get("source", "immich"),
        "image_bytes": a["image_bytes"],
    } for a in pending]

    try:
        decisions = harness.run(luna_assets, image_getter)
    except Exception as e:
        logger.error("agent path: harness raised: %s", e)
        decisions = None
    finally:
        harness.close()
        analyzer.close()

    if decisions is None:
        logger.warning("agent path failed (%d photos), caller must fall back",
                       len(pending))
        return None, [], "harness_failed"

    records: list[dict] = []
    skipped: list[str] = []
    covered: set[str] = set()
    session_date = max(((a.get("photo_time") or "")[:10] for a in pending),
                       default=datetime.now(HKT).strftime("%Y-%m-%d"))

    for dec in decisions:
        db.insert_agent_decision(
            session_date,
            {
                "asset_ids": dec.asset_ids,
                "action": dec.action,
                "relation": dec.relation,
                "target_asset_id": dec.target_asset_id,
                "result": dec.result,
                "reasoning": dec.reasoning,
                "prompt_for_gemini": dec.prompt_for_gemini,
            },
            run_id=run_id or None,
            model_used=os.getenv("LUNA_MODEL", "gpt-5.6-luna"),
        )
        covered.update(dec.asset_ids)
        db.add_event(run_id, "agent_decision", ",".join(dec.asset_ids), {
            "action": dec.action,
            "relation": dec.relation,
            "target_asset_id": dec.target_asset_id,
            "meal": dec.result.get("meal"),
            "calories": dec.result.get("calories"),
            "origin": "manual",
        })

        if dec.action == "skip":
            for aid in dec.asset_ids:
                db.add_classified_non_food(aid, decided_by="agent")
                skipped.append(aid)
            continue

        # update: manual photos have no pre-existing record to merge into;
        # the semantics here are always a new meal — downgrade to add.
        if dec.action == "update":
            logger.info("agent path: update decision downgraded to add "
                        "(manual photos have no target record)")
            dec = replace(dec, action="add", relation="new_meal")

        if dec.action == "add":
            for aid in dec.asset_ids:
                item = next((a for a in pending if a["asset_id"] == aid), None)
                if item is None:
                    logger.error("agent path: add references unknown asset %s",
                                 aid[:8])
                    continue
                record = _build_record(
                    asset_id=item["asset_id"],
                    source=item.get("source", "manual"),
                    photo_time=item.get("photo_time", ""),
                    thumbnail_url=item.get("thumbnail_url", ""),
                    result=dec.result,
                )
                db.insert_record(record)
                db.remove_classified_non_food(aid)
                records.append(record)
                logger.info("agent path: ✅ add [%s...] %s ~%skcal",
                            aid[:8], dec.result.get("meal"),
                            dec.result.get("calories"))

    missing = [a["asset_id"] for a in pending if a["asset_id"] not in covered]
    if missing:
        logger.error("agent path: decisions did not cover %d photos: %s",
                     len(missing), [m[:8] for m in missing])
        return (records or None), skipped, f"partial:{len(missing)}"

    return records, skipped, None


def _build_record(asset_id: str, source: str, photo_time: str,
                  thumbnail_url: str, result: dict) -> dict:
    """Assemble a records-row dict from a Luna decision result."""
    return {
        "asset_id": asset_id,
        "source_type": source,
        "source_id": asset_id,
        "photo_time": photo_time or datetime.now(HKT).isoformat(),
        "thumbnail_url": thumbnail_url,
        "meal": result.get("meal", "unknown"),
        "calories": result.get("calories", 0),
        "protein_g": result.get("protein_g", 0),
        "carbs_g": result.get("carbs_g", 0),
        "fat_g": result.get("fat_g", 0),
        "confidence": result.get("confidence", "low"),
        "analyzed_at": datetime.now(HKT).isoformat(),
    }


def reanalyze_record(asset_id: str, notes: str, config: dict) -> dict | None:
    """Re-analyze a food photo with user-provided notes.

    Retrieves the image (from replacement_image file, Immich thumbnail,
    or PhotoPrism thumbnail), runs Gemini reanalysis, appends current
    values to reanalysis_history, and updates the record.

    Returns the updated record dict, or None if the image is unavailable.
    """
    from src import db
    from src.calorie_analyzer import CalorieAnalyzer

    found = db.get_record_by_asset_id(asset_id)
    if not found:
        logger.error("Record not found: %s", asset_id[:8])
        return None

    image_bytes = _get_image_bytes(found, config)
    if image_bytes is None:
        logger.error("Image unavailable for %s", asset_id[:8])
        return None

    # Verify image validity
    try:
        Image.open(io.BytesIO(image_bytes)).verify()
    except Exception:
        logger.error("Invalid image data for %s", asset_id[:8])
        return None

    analyzer = CalorieAnalyzer(
        config.get("gemini_key", ""),
        base_url=config.get("gemini_base_url"),
        model=config.get("gemini_model", "gemini-3-flash-preview"),
    )

    current_result = {
        "meal": found.get("meal", "unknown"),
        "calories": found.get("calories", 0),
        "protein_g": found.get("protein_g", 0),
        "carbs_g": found.get("carbs_g", 0),
        "fat_g": found.get("fat_g", 0),
        "confidence": found.get("confidence", "low"),
    }

    result = analyzer.reanalyze(image_bytes, current_result, notes)
    analyzer.close()

    # Preserve current values in history before overwriting
    db.append_reanalysis_history(asset_id, {
        "meal": found.get("meal"),
        "calories": found.get("calories"),
        "protein_g": found.get("protein_g"),
        "carbs_g": found.get("carbs_g"),
        "fat_g": found.get("fat_g"),
        "confidence": found.get("confidence"),
        "notes": notes,
        "reanalyzed_at": datetime.now(HKT).isoformat(),
    })

    # Update record with new values
    db.update_record(asset_id, {
        "meal": result.get("meal", found["meal"]),
        "calories": result.get("calories", found["calories"]),
        "protein_g": result.get("protein_g", found["protein_g"]),
        "carbs_g": result.get("carbs_g", found["carbs_g"]),
        "fat_g": result.get("fat_g", found["fat_g"]),
        "confidence": result.get("confidence", found["confidence"]),
    })

    return db.get_record_by_asset_id(asset_id)


# ── internal helpers ──────────────────────────────────────────────────

def _resolve_photo_time(asset_id: str, source: str, config: dict) -> str:
    """Fetch the original photo capture time from Immich or PhotoPrism metadata."""
    from src.immich_client import ImmichClient, format_photo_time
    from src.photoprism_client import PhotoPrismClient

    try:
        if source == "immich":
            client = ImmichClient(
                config.get("immich_url", ""),
                config.get("immich_key", ""),
            )
            req = client._client.get(f"/api/assets/{asset_id}")
            req.raise_for_status()
            meta = req.json()
            client.close()
            exif = meta.get("exifInfo", {})
            raw_pt = exif.get("dateTimeOriginal", "")
            exif_tz = exif.get("timeZone")
            return format_photo_time(raw_pt, exif_tz)
        elif source == "photoprism":
            client = PhotoPrismClient(
                config.get("photoprism_url", ""),
                config.get("photoprism_key", ""),
            )
            req = client._client.get(f"/photos/{asset_id}")
            req.raise_for_status()
            meta = req.json()
            client.close()
            return meta.get("TakenAt", "") or meta.get("CreatedAt", "")
    except Exception as e:
        logger.warning("Failed to resolve photo time for %s [%s]: %s", asset_id[:8], source, e)
    return datetime.now(HKT).isoformat()


def _download_original(asset_id: str, source: str, config: dict) -> bytes | None:
    """Download original photo from Immich or PhotoPrism."""
    try:
        if source == "immich":
            from src.immich_client import ImmichClient
            client = ImmichClient(
                config.get("immich_url", ""),
                config.get("immich_key", ""),
            )
            data = client.download_original(asset_id)
            client.close()
            return data
        elif source == "photoprism":
            from src.photoprism_client import PhotoPrismClient
            client = PhotoPrismClient(
                config.get("photoprism_url", ""),
                config.get("photoprism_key", ""),
            )
            data = client.download_original(asset_id)
            client.close()
            return data
    except Exception as e:
        logger.error("Download original [%s] failed: %s", source, e)
    return None


def _get_image_bytes(record: dict, config: dict) -> bytes | None:
    """Retrieve image bytes for a record, trying replacement_image first,
    then Immich/PhotoPrism thumbnail download."""
    import httpx

    replacement_image = record.get("replacement_image", "")
    if replacement_image and Path(replacement_image).is_file():
        try:
            return Path(replacement_image).read_bytes()
        except Exception as e:
            logger.error("Failed to read replacement image: %s", e)

    thumbnail_url = record.get("thumbnail_url", "")
    if not thumbnail_url:
        return None

    immich_url = config.get("immich_url", "").rstrip("/")
    photoprism_url = config.get("photoprism_url", "").rstrip("/")

    try:
        if immich_url and thumbnail_url.startswith(immich_url + "/"):
            headers = {"x-api-key": config.get("immich_key", "")}
            r = httpx.get(thumbnail_url, headers=headers, timeout=15)
            if r.status_code == 200:
                return r.content
        elif photoprism_url and thumbnail_url.startswith(photoprism_url + "/"):
            r = httpx.get(thumbnail_url, timeout=15)
            if r.status_code == 200:
                return r.content
    except Exception as e:
        logger.error("Failed to fetch thumbnail: %s", e)

    return None
