"""Pipeline operations shared by CLI and web server.

Functions that were previously only available through web endpoints
are extracted here so both CLI (inkcal analyze/reanalyze) and Flask
can call the same logic.
"""

import io
import logging
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
) -> tuple[dict | None, str | None]:
    """Download original from photo source, run Gemini (skip food detection),
    save record, and remove from classified_non_food.

    Returns (record, error) tuple.  On success error is None.
    Error values: "already_processed", "download_failed", "not_food", "analysis_failed".
    """
    from src import db
    from src.calorie_analyzer import CalorieAnalyzer

    # Race-condition guard
    if db.get_record_by_asset_id(asset_id):
        logger.warning("Asset %s already processed", asset_id[:8])
        return None, "already_processed"

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
