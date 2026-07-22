"""inkcal Web — mobile-friendly meal records viewer."""
import io
import ipaddress
import json
import logging
import os
import re
import secrets
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from time import monotonic

logger = logging.getLogger(__name__)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from PIL import Image
from flask import Flask, jsonify, request, send_from_directory, Response, session, redirect, url_for

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from src import db

app = Flask(__name__, static_folder="static", static_url_path="")
app.secret_key = os.getenv("INKCAL_SECRET", secrets.token_hex(32))
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("INKCAL_HTTPS", "0") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    MAX_CONTENT_LENGTH=16 * 1024 * 1024,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
HKT = timezone(timedelta(hours=8))

# Initialize database on startup
db.init_db(DATA_DIR / "inkcal.db")

INKCAL_USER = os.getenv("INKCAL_USER", "")
INKCAL_PASS = os.getenv("INKCAL_PASS", "")

if bool(INKCAL_USER) != bool(INKCAL_PASS):
    raise RuntimeError(
        "INKCAL_USER and INKCAL_PASS must be set together, or both left empty to disable auth."
    )

AUTH_REQUIRED = bool(INKCAL_USER)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ALLOWED_IMAGE_MIME = {"image/jpeg", "image/png", "image/heic", "image/heif", "image/webp"}

_LOGIN_WINDOW = 300  # seconds
_LOGIN_MAX = 5
_login_attempts: dict[str, list[float]] = defaultdict(list)


def _valid_date(date_str: str) -> bool:
    return bool(DATE_RE.fullmatch(date_str or ""))


def _check_auth() -> bool:
    if not AUTH_REQUIRED:
        return True
    return session.get("auth") is True


_TRUSTED_PROXIES = {"127.0.0.1", "::1"}


def _client_ip() -> str:
    direct = request.remote_addr or "unknown"
    if direct not in _TRUSTED_PROXIES:
        return direct
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        try:
            ipaddress.ip_address(first)
            return first
        except ValueError:
            pass
    real_ip = request.headers.get("X-Real-IP", "")
    if real_ip:
        try:
            ipaddress.ip_address(real_ip.strip())
            return real_ip.strip()
        except ValueError:
            pass
    return direct


def _login_rate_limited(ip: str) -> bool:
    now = monotonic()
    attempts = [t for t in _login_attempts[ip] if now - t < _LOGIN_WINDOW]
    _login_attempts[ip] = attempts
    return len(attempts) >= _LOGIN_MAX


def _record_login_failure(ip: str) -> None:
    _login_attempts[ip].append(monotonic())


def _immich_headers() -> dict:
    return {"x-api-key": os.getenv("IMMICH_API_KEY", "")}


def _load_date(date_str: str) -> list[dict]:
    return db.get_records_by_date(date_str)


def _available_dates() -> list[str]:
    return db.get_available_dates()


def _summarize(records: list[dict]) -> dict:
    return db.summarize_records(records)


def _load_ignored() -> set[str]:
    return db.get_ignored_assets()


def _save_ignored(ignored: set[str]):
    for asset_id in ignored:
        db.add_ignored_asset(asset_id)


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/dates")
def api_dates():
    return jsonify(_available_dates())


@app.route("/api/records")
def api_records():
    date_str = request.args.get("date")
    start = request.args.get("start")
    end = request.args.get("end")

    if date_str:
        if not _valid_date(date_str):
            return jsonify({"error": "invalid date"}), 400
        records = _load_date(date_str)
        return jsonify({
            "date": date_str,
            "records": records,
            "summary": _summarize(records),
        })

    if start and end:
        if not (_valid_date(start) and _valid_date(end)):
            return jsonify({"error": "invalid date range"}), 400
        all_records = []
        cursor = datetime.strptime(start, "%Y-%m-%d")
        end_dt = datetime.strptime(end, "%Y-%m-%d")
        if (end_dt - cursor).days > 366:
            return jsonify({"error": "range too large"}), 400
        while cursor <= end_dt:
            ds = cursor.strftime("%Y-%m-%d")
            all_records.extend({"date": ds, **r} for r in _load_date(ds))
            cursor += timedelta(days=1)
        return jsonify({
            "start": start,
            "end": end,
            "records": all_records,
            "summary": _summarize(all_records),
        })

    # Default: today
    today = datetime.now(HKT).strftime("%Y-%m-%d")
    records = _load_date(today)
    return jsonify({
        "date": today,
        "records": records,
        "summary": _summarize(records),
    })


@app.route("/api/today")
def api_today():
    today = datetime.now(HKT).strftime("%Y-%m-%d")
    records = _load_date(today)
    return jsonify({
        "date": today,
        "records": records,
        "summary": _summarize(records),
    })


@app.route("/api/week")
def api_week():
    today = datetime.now(HKT)
    monday = today - timedelta(days=today.weekday())
    dates = [(monday + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]
    by_day = {}
    for ds in dates:
        by_day[ds] = _load_date(ds)
    all_records = [r for day_recs in by_day.values() for r in day_recs]
    return jsonify({
        "start": dates[0],
        "end": dates[-1],
        "by_day": {d: {"records": by_day[d], "summary": _summarize(by_day[d])} for d in dates},
        "summary": _summarize(all_records),
    })


@app.route("/api/image")
def api_image():
    url = request.args.get("url", "")
    if not url:
        return "missing url", 400

    immich_url = os.getenv("IMMICH_URL", "").rstrip("/")
    photoprism_url = os.getenv("PHOTOPRISM_URL", "").rstrip("/")

    if immich_url and url.startswith(immich_url + "/"):
        try:
            r = httpx.get(url, headers=_immich_headers(), timeout=15)
            return Response(r.content, mimetype=r.headers.get("content-type", "image/jpeg"))
        except Exception:
            return "image fetch failed", 502

    if photoprism_url and url.startswith(photoprism_url + "/"):
        # PhotoPrism thumbnails are cookie-free; token is already in the URL
        try:
            r = httpx.get(url, timeout=15)
            return Response(r.content, mimetype=r.headers.get("content-type", "image/jpeg"))
        except Exception:
            return "image fetch failed", 502

    return "forbidden", 403



@app.route("/api/upload-image", methods=["POST"])
def api_upload_image():
    date_str = request.form.get("date", "")
    asset_id = request.form.get("asset_id", "")
    file = request.files.get("image")
    if not _valid_date(date_str) or not asset_id or not file:
        return jsonify({"error": "missing or invalid params"}), 400
    if file.mimetype not in ALLOWED_IMAGE_MIME:
        return jsonify({"error": "unsupported mime"}), 400

    image_bytes = file.read()
    try:
        Image.open(io.BytesIO(image_bytes)).verify()
    except Exception:
        return jsonify({"error": "invalid image"}), 400

    immich_url = os.getenv("IMMICH_URL", "")

    if immich_url:
        from src.immich_client import ImmichClient
        immich = ImmichClient(immich_url, os.getenv("IMMICH_API_KEY", ""))
        time_window = ImmichClient.extract_exif_time(image_bytes)
        matched = immich.match_by_phash(date_str, image_bytes, time_window=time_window)
        immich.close()

        if matched:
            record = db.get_record_by_asset_id(asset_id)
            if record:
                db.update_record(asset_id, {
                    "thumbnail_url": matched["thumbnail_url"],
                    "asset_id": matched["id"],
                    "photo_time": matched.get("photo_time", record.get("photo_time", "")),
                    "replacement_image": None,
                })
                return jsonify({"ok": True, "matched": True, "asset_id": matched["id"],
                                "thumbnail_url": matched["thumbnail_url"]})

    img_dir = DATA_DIR / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    safe_asset = re.sub(r"[^A-Za-z0-9_-]", "_", asset_id)[:64]
    filename = f"{date_str}_{safe_asset}.jpg"
    filepath = img_dir / filename
    filepath.write_bytes(image_bytes)

    record = db.get_record_by_asset_id(asset_id)
    if record:
        db.update_record(asset_id, {"replacement_image": str(filepath)})
        return jsonify({"ok": True, "matched": False, "replacement_image": str(filepath)})
    return jsonify({"error": "record not found"}), 404


@app.route("/api/manual-upload", methods=["POST"])
def api_manual_upload():
    """Upload a photo for Gemini analysis + Immich matching."""
    file = request.files.get("image")
    if not file:
        return jsonify({"error": "missing image"}), 400
    if file.mimetype not in ALLOWED_IMAGE_MIME:
        return jsonify({"error": "unsupported mime"}), 400

    image_bytes = file.read()
    try:
        Image.open(io.BytesIO(image_bytes)).verify()
    except Exception:
        return jsonify({"error": "invalid image"}), 400

    gemini_key = os.getenv("GEMINI_API_KEY", "")
    if not gemini_key:
        return jsonify({"error": "GEMINI_API_KEY not configured"}), 500

    # ── Date determination ────────────────────────────────────────
    # Always extract EXIF time for precise Immich pHash matching.
    # User-provided date is only used for date_str when EXIF is absent.
    from src.immich_client import ImmichClient

    user_date = request.args.get("date", "") or request.form.get("date", "")
    user_date = user_date if _valid_date(user_date) else None
    exif_time = ImmichClient.extract_exif_time(image_bytes)

    if exif_time:
        dt = datetime.fromisoformat(exif_time)
        date_str = dt.strftime("%Y-%m-%d")
        photo_time = exif_time
        _source = "exif"
    elif user_date:
        date_str = user_date
        now = datetime.now(HKT)
        photo_time = f"{date_str}T{now.strftime('%H:%M:%S')}+08:00"
        _source = "user"
    else:
        now = datetime.now(HKT)
        date_str = now.strftime("%Y-%m-%d")
        photo_time = now.isoformat()
        _source = "fallback"

    import sys
    print(f"  [upload] user_date={user_date} exif_time={exif_time} _source={_source} date_str={date_str}", file=sys.stderr, flush=True)

    # ── Gemini analysis (first — skip pHash if not food) ──────────
    from src.calorie_analyzer import CalorieAnalyzer

    analyzer = CalorieAnalyzer(
        gemini_key,
        base_url=os.getenv("GEMINI_BASE_URL"),
        model=os.getenv("GEMINI_MODEL", "gemini-3-flash-preview"),
    )
    result = analyzer.analyze(image_bytes)
    analyzer.close()

    if result.get("meal") in ("not real food", "unknown"):
        return jsonify({"error": "not food", "detail": result.get("meal", "")}), 422

    # ── Multi-source pHash match (after Gemini confirmed it's food) ─────
    sources = _resolve_sources()
    matched = None
    matched_source = None

    for source in sources:
        if source == "immich":
            immich_url = os.getenv("IMMICH_URL", "")
            immich_key = os.getenv("IMMICH_API_KEY", "")
            if not (immich_url and immich_key):
                continue
            try:
                from src.immich_client import ImmichClient
                client = ImmichClient(immich_url, immich_key)
                matched = client.match_by_phash(date_str, image_bytes, time_window=exif_time)
                client.close()
                if matched:
                    matched_source = "immich"
                    break
            except Exception as e:
                logger.error("pHash match [immich] failed: %s", e)
        elif source == "photoprism":
            # TODO: implement pHash matching for PhotoPrism
            # PhotoPrismClient currently lacks match_by_phash()
            pass

    if matched:
        records = _load_date(date_str)
        if any(r.get("asset_id") == matched["id"] for r in records):
            return jsonify({"error": "already processed", "asset_id": matched["id"][:8]}), 409

    # ── Build record ─────────────────────────────────────────────
    if matched:
        asset_id = matched["id"]
        thumbnail_url = matched["thumbnail_url"]
        photo_time = matched.get("photo_time", photo_time)
        image_path = None
    else:
        asset_id = f"manual-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        thumbnail_url = ""
        img_dir = DATA_DIR / "images"
        img_dir.mkdir(parents=True, exist_ok=True)
        safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", asset_id)[:64]
        filename = f"{date_str}_{safe_id}.jpg"
        filepath = img_dir / filename
        filepath.write_bytes(image_bytes)
        image_path = str(filepath)

    record = {
        "asset_id": asset_id,
        "source_type": matched_source or "manual",
        "source_id": asset_id,
        "photo_time": photo_time,
        "thumbnail_url": thumbnail_url,
        "meal": result.get("meal", "unknown"),
        "calories": result.get("calories", 0),
        "protein_g": result.get("protein_g", 0),
        "carbs_g": result.get("carbs_g", 0),
        "fat_g": result.get("fat_g", 0),
        "confidence": result.get("confidence", "low"),
        "analyzed_at": datetime.now(HKT).isoformat(),
    }
    if image_path:
        record["replacement_image"] = image_path

    db.insert_record(record)

    return jsonify({"ok": True, "record": record, "matched": bool(matched), "date": date_str, "_date_source": _source, "_date_received": request.args.get("date", "") or request.form.get("date", "")})


def _resolve_sources() -> list[str]:
    """Return list of enabled photo sources from the SOURCE env var."""
    source_str = os.getenv("SOURCE", "").strip().lower()
    if source_str:
        return [s.strip() for s in source_str.split(",") if s.strip()]
    # Backwards-compat: auto-enable Immich if key exists
    if os.getenv("IMMICH_API_KEY"):
        return ["immich"]
    return []


@app.route("/api/album-photos")
def api_album_photos():
    """Return unprocessed album photos grouped by date, paginated.

    Query params:
      cursor -- YYYY-MM-DD start date (default: today)
      days   -- how many days to look back (default: 7)
    """
    cursor_str = request.args.get("cursor", "")
    days_str = request.args.get("days", "7")

    if cursor_str and not _valid_date(cursor_str):
        return jsonify({"error": "invalid cursor"}), 400
    try:
        days = int(days_str)
        if days < 1 or days > 30:
            days = 7
    except ValueError:
        days = 7

    cursor = datetime.strptime(cursor_str or datetime.now(HKT).strftime("%Y-%m-%d"), "%Y-%m-%d")
    sources = _resolve_sources()
    ignored = db.get_ignored_assets()
    classified_non_food = db.get_classified_non_food()

    dates_result = []
    for i in range(days):
        target_date = cursor - timedelta(days=i)
        date_str = target_date.strftime("%Y-%m-%d")
        processed = db.get_processed_asset_ids(date_str)

        day_photos = []
        for source in sources:
            if source == "immich":
                immich_url = os.getenv("IMMICH_URL", "")
                immich_key = os.getenv("IMMICH_API_KEY", "")
                if not (immich_url and immich_key):
                    continue
                try:
                    from src.immich_client import ImmichClient, format_photo_time
                    client = ImmichClient(immich_url, immich_key)
                    assets = client.get_date_assets(target_date)
                    for a in assets:
                        aid = a["id"]
                        if aid in processed or aid in ignored:
                            continue
                        exif = a.get("exifInfo", {})
                        raw_photo_time = exif.get("dateTimeOriginal", "")
                        exif_tz = exif.get("timeZone")
                        photo_time = format_photo_time(raw_photo_time, exif_tz)
                        day_photos.append({
                            "asset_id": aid,
                            "thumbnail_url": client.get_thumbnail_url(aid),
                            "photo_time": photo_time,
                            "source": "immich",
                            "classified_non_food": aid in classified_non_food,
                        })
                    client.close()
                except Exception as e:
                    logger.error("Album photos [immich] failed: %s", e)
            elif source == "photoprism":
                photoprism_url = os.getenv("PHOTOPRISM_URL", "")
                photoprism_key = os.getenv("PHOTOPRISM_API_KEY", "")
                if not (photoprism_url and photoprism_key):
                    continue
                try:
                    from src.photoprism_client import PhotoPrismClient
                    client = PhotoPrismClient(photoprism_url, photoprism_key)
                    assets = client.get_date_assets(target_date)
                    for a in assets:
                        aid = a["id"]
                        if aid in processed or aid in ignored:
                            continue
                        day_photos.append({
                            "asset_id": aid,
                            "thumbnail_url": client.get_thumbnail_url(a["hash"], size="tile_500"),
                            "photo_time": a["photo_time"],
                            "source": "photoprism",
                            "classified_non_food": aid in classified_non_food,
                        })
                    client.close()
                except Exception as e:
                    logger.error("Album photos [photoprism] failed: %s", e)

        if day_photos:
            dates_result.append({"date": date_str, "photos": day_photos})

    next_cursor = (cursor - timedelta(days=days)).strftime("%Y-%m-%d")
    return jsonify({"dates": dates_result, "next_cursor": next_cursor})


@app.route("/api/analyze-album-photo", methods=["POST"])
def api_analyze_album_photo():
    """Download album original, run Gemini (skip food detection), save record."""
    data = request.get_json() or {}
    asset_id = data.get("asset_id", "")
    source = data.get("source", "")
    date_str = data.get("date", "")
    thumbnail_url = data.get("thumbnail_url", "")
    photo_time = data.get("photo_time", "")

    if not asset_id or not source or not _valid_date(date_str):
        return jsonify({"error": "missing or invalid params"}), 400

    gemini_key = os.getenv("GEMINI_API_KEY", "")
    if not gemini_key:
        return jsonify({"error": "GEMINI_API_KEY not configured"}), 500

    from src.pipeline_ops import analyze_asset

    config = {
        "immich_url": os.getenv("IMMICH_URL", ""),
        "immich_key": os.getenv("IMMICH_API_KEY", ""),
        "photoprism_url": os.getenv("PHOTOPRISM_URL", ""),
        "photoprism_key": os.getenv("PHOTOPRISM_API_KEY", ""),
        "gemini_key": gemini_key,
        "gemini_base_url": os.getenv("GEMINI_BASE_URL"),
        "gemini_model": os.getenv("GEMINI_MODEL", "gemini-3-flash-preview"),
    }

    record, error = analyze_asset(asset_id, source, config,
                                  photo_time=photo_time,
                                  thumbnail_url=thumbnail_url)
    if error == "already_processed":
        return jsonify({"error": "already processed"}), 409
    if error == "not_food":
        return jsonify({"error": "not food"}), 422
    if error is not None:
        return jsonify({"error": error}), 500

    return jsonify({"ok": True, "record": record, "date": date_str})


@app.route("/api/move-record", methods=["POST"])
def api_move_record():
    """Move a record from its current date to a new date."""
    data = request.get_json() or {}
    asset_id = data.get("asset_id", "")
    new_date = data.get("date", "")
    if not asset_id or not _valid_date(new_date):
        return jsonify({"error": "missing or invalid params"}), 400

    record = db.get_record_by_asset_id(asset_id)
    if not record:
        return jsonify({"error": "record not found"}), 404

    # Get old date from database
    conn = db._get_conn()
    row = conn.execute("SELECT date FROM records WHERE asset_id = ?", (asset_id,)).fetchone()
    old_date = row["date"] if row else None

    # Re-try Immich pHash matching on the new date
    immich_matched = None
    replacement_image = record.get("replacement_image", "")
    if replacement_image and (DATA_DIR / "images").resolve() in Path(replacement_image).resolve().parents:
        try:
            image_bytes = Path(replacement_image).read_bytes()
            immich_url = os.getenv("IMMICH_URL", "")
            if immich_url:
                from src.immich_client import ImmichClient
                immich = ImmichClient(immich_url, os.getenv("IMMICH_API_KEY", ""))
                exif_time = ImmichClient.extract_exif_time(image_bytes)
                immich_matched = immich.match_by_phash(new_date, image_bytes, time_window=exif_time)
                immich.close()
        except Exception:
            pass

    # Build updates for move_record
    updates = {}
    if immich_matched:
        updates["asset_id"] = immich_matched["id"]
        updates["thumbnail_url"] = immich_matched["thumbnail_url"]
        updates["photo_time"] = immich_matched.get("photo_time", f"{new_date}T00:00:00+08:00")
        updates["replacement_image"] = None
        try:
            Path(replacement_image).unlink(missing_ok=True)
        except Exception:
            pass

    db.move_record(asset_id, new_date, updates)

    return jsonify({"ok": True, "asset_id": immich_matched["id"] if immich_matched else asset_id,
                    "old_date": old_date, "new_date": new_date,
                    "immich_matched": bool(immich_matched)})


@app.route("/api/record", methods=["DELETE"])
def api_delete_record():
    data = request.get_json() or {}
    asset_id = data.get("asset_id", "")
    if not asset_id:
        return jsonify({"error": "missing asset_id"}), 400

    record = db.delete_record(asset_id)
    if record is None:
        return jsonify({"error": "record not found"}), 404

    replacement_image = record.get("replacement_image", "")
    if replacement_image:
        try:
            Path(replacement_image).unlink(missing_ok=True)
        except Exception:
            pass

    # Add Immich assets to ignore list so cron won't re-process them
    if asset_id and not asset_id.startswith("manual-"):
        db.add_ignored_asset(asset_id)

    return jsonify({"ok": True})


@app.route("/api/reanalyze", methods=["POST"])
def api_reanalyze():
    """Re-analyze a food photo with user-provided notes."""
    data = request.get_json() or {}
    asset_id = data.get("asset_id", "")
    notes = (data.get("notes", "") or "").strip()

    if not asset_id:
        return jsonify({"error": "missing asset_id"}), 400
    if not notes:
        return jsonify({"error": "missing notes"}), 400

    found = db.get_record_by_asset_id(asset_id)
    if not found:
        return jsonify({"error": "record not found"}), 404

    # Delegate to shared pipeline_ops logic
    gemini_key = os.getenv("GEMINI_API_KEY", "")
    if not gemini_key:
        return jsonify({"error": "GEMINI_API_KEY not configured"}), 500

    from src.pipeline_ops import reanalyze_record

    config = {
        "immich_url": os.getenv("IMMICH_URL", ""),
        "immich_key": os.getenv("IMMICH_API_KEY", ""),
        "photoprism_url": os.getenv("PHOTOPRISM_URL", ""),
        "photoprism_key": os.getenv("PHOTOPRISM_API_KEY", ""),
        "gemini_key": gemini_key,
        "gemini_base_url": os.getenv("GEMINI_BASE_URL"),
        "gemini_model": os.getenv("GEMINI_MODEL", "gemini-3-flash-preview"),
    }

    updated = reanalyze_record(asset_id, notes, config)
    if updated is None:
        return jsonify({"error": "image unavailable"}), 502

    return jsonify({"ok": True, "record": updated})


@app.route("/api/local-image")
def api_local_image():
    path = request.args.get("path", "")
    if not path:
        return "missing path", 400
    try:
        resolved = Path(path).resolve()
        allowed_root = (DATA_DIR / "images").resolve()
        if not resolved.is_relative_to(allowed_root):
            return "forbidden", 403
        if not resolved.is_file():
            return "not found", 404
        return send_from_directory(resolved.parent, resolved.name)
    except (OSError, ValueError):
        return "invalid path", 400


@app.before_request
def _require_auth():
    if not AUTH_REQUIRED:
        return None
    if request.path in {"/api/login", "/login"}:
        return None
    if not _check_auth():
        if request.path.startswith("/api/"):
            return jsonify({"error": "unauthorized"}), 401
        return redirect("/login")


@app.route("/login")
def login_page():
    if _check_auth():
        return redirect("/")
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>inkcal · 登录</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#0f0f0f;color:#e0e0e0;display:flex;align-items:center;justify-content:center;min-height:100vh}
form{background:#1a1a1a;border-radius:16px;padding:32px 24px;width:100%;max-width:320px}
h1{font-size:20px;margin-bottom:24px;text-align:center}
h1 span{color:#666;font-size:14px;font-weight:400}
input{width:100%;background:#222;border:1px solid #333;border-radius:8px;padding:10px 14px;font-size:15px;color:#e0e0e0;margin-bottom:12px;outline:none;font-family:inherit}
input:focus{border-color:#2a6eff}
button{width:100%;background:#2a6eff;color:#fff;border:none;border-radius:8px;padding:12px;font-size:15px;cursor:pointer;font-family:inherit}
button:active{background:#1a5aee}
.error{color:#ff6b6b;font-size:13px;text-align:center;margin-top:12px;display:none}
</style>
</head>
<body>
<form onsubmit="login(event)">
<h1>inkcal <span>  </span></h1>
<input type="text" id="user" placeholder="用户名" autocomplete="username" required>
<input type="password" id="pass" placeholder="密码" autocomplete="current-password" required>
<button type="submit">登录</button>
<div class="error" id="error">用户名或密码错误</div>
</form>
<script>
function login(e){
e.preventDefault();
fetch('/api/login',{
method:'POST',
headers:{'Content-Type':'application/json'},
body:JSON.stringify({user:document.getElementById('user').value,password:document.getElementById('pass').value})
}).then(r=>{if(r.ok)location='/';else document.getElementById('error').style.display='block'});
}
</script>
</body>
</html>"""


@app.route("/api/login", methods=["POST"])
def api_login():
    ip = _client_ip()
    if _login_rate_limited(ip):
        return jsonify({"error": "too many attempts, try again later"}), 429
    data = request.get_json() or {}
    user = os.getenv("INKCAL_USER", "")
    pwd = os.getenv("INKCAL_PASS", "")
    submitted_user = data.get("user", "")
    submitted_pass = data.get("password", "")
    user_ok = secrets.compare_digest(submitted_user, user)
    pass_ok = secrets.compare_digest(submitted_pass, pwd)
    if user and pwd and user_ok and pass_ok:
        session["auth"] = True
        session.permanent = True
        _login_attempts.pop(ip, None)
        return jsonify({"ok": True})
    _record_login_failure(ip)
    return jsonify({"error": "bad credentials"}), 401


@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"ok": True})


if __name__ == "__main__":
    host = os.getenv("INKCAL_HOST", "127.0.0.1")
    port = int(os.getenv("INKCAL_PORT", "5800"))
    debug = os.getenv("INKCAL_DEBUG", "0") == "1"
    print(f"  inkcal Web — http://{host}:{port}")
    app.run(host=host, port=port, debug=debug)
