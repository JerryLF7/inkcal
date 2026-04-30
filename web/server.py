"""intake Web — mobile-friendly meal records viewer."""
import io
import json
import os
import secrets
from datetime import datetime, timedelta, timezone, date
from pathlib import Path

import httpx
import imagehash
from PIL import Image
from flask import Flask, jsonify, request, send_from_directory, Response, session, redirect, url_for

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

app = Flask(__name__, static_folder="static", static_url_path="")
app.secret_key = os.getenv("INTAKE_SECRET", secrets.token_hex(32))

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
HKT = timezone(timedelta(hours=8))


def _check_auth():
    """Return True if user is authenticated or auth is not configured."""
    user = os.getenv("INTAKE_USER", "")
    pwd = os.getenv("INTAKE_PASS", "")
    if not user or not pwd:
        return True
    return session.get("auth") == True

AUTH_REQUIRED = bool(os.getenv("INTAKE_USER", ""))


def _immich_headers() -> dict:
    return {"x-api-key": os.getenv("IMMICH_API_KEY", "")}


def _load_date(date_str: str) -> list[dict]:
    path = DATA_DIR / f"{date_str}.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, FileNotFoundError):
        return []


def _save_date(date_str: str, records: list[dict]):
    path = DATA_DIR / f"{date_str}.json"
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2))


def _available_dates() -> list[str]:
    if not DATA_DIR.exists():
        return []
    return sorted(
        (f.stem for f in DATA_DIR.glob("*.json") if f.stem.count("-") == 2),
        reverse=True,
    )


def _summarize(records: list[dict]) -> dict:
    return {
        "meals": len(records),
        "calories": sum(r.get("calories", 0) for r in records),
        "protein": sum(r.get("protein_g", 0) for r in records),
        "carbs": sum(r.get("carbs_g", 0) for r in records),
        "fat": sum(r.get("fat_g", 0) for r in records),
    }


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
        records = _load_date(date_str)
        return jsonify({
            "date": date_str,
            "records": records,
            "summary": _summarize(records),
        })

    if start and end:
        all_records = []
        cursor = datetime.strptime(start, "%Y-%m-%d")
        end_dt = datetime.strptime(end, "%Y-%m-%d")
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
    try:
        r = httpx.get(url, headers=_immich_headers(), timeout=15)
        return Response(r.content, mimetype=r.headers.get("content-type", "image/jpeg"))
    except Exception:
        return "image fetch failed", 502


@app.route("/api/label", methods=["POST"])
def api_label():
    data = request.get_json()
    date_str = data.get("date", "")
    asset_id = data.get("asset_id", "")
    label = data.get("label", "")
    if not date_str or not asset_id or label not in ("correct", "wrong"):
        return jsonify({"error": "invalid params"}), 400

    records = _load_date(date_str)
    for r in records:
        if r.get("asset_id") == asset_id:
            r["user_label"] = label
            _save_date(date_str, records)
            return jsonify({"ok": True, "user_label": label})
    return jsonify({"error": "record not found"}), 404


@app.route("/api/upload-image", methods=["POST"])
def api_upload_image():
    date_str = request.form.get("date", "")
    asset_id = request.form.get("asset_id", "")
    file = request.files.get("image")
    if not date_str or not asset_id or not file:
        return jsonify({"error": "missing params"}), 400

    # Compute pHash of uploaded image
    uploaded_img = Image.open(io.BytesIO(file.read())).convert("RGB")
    uploaded_hash = imagehash.phash(uploaded_img)

    # Extract EXIF timestamp to narrow search window
    time_window = _extract_exif_time(uploaded_img)

    # Try to match against Immich photos from the same day
    immich_url = os.getenv("IMMICH_URL", "")
    if immich_url:
        matched_asset = _match_immich_photo(date_str, uploaded_hash, time_window)
        if matched_asset:
            records = _load_date(date_str)
            for r in records:
                if r.get("asset_id") == asset_id:
                    r["thumbnail_url"] = matched_asset["thumbnail_url"]
                    r["asset_id"] = matched_asset["id"]
                    r["photo_time"] = matched_asset.get("photo_time", r.get("photo_time", ""))
                    r.pop("replacement_image", None)
                    _save_date(date_str, records)
                    return jsonify({"ok": True, "matched": True, "asset_id": matched_asset["id"],
                                    "thumbnail_url": matched_asset["thumbnail_url"]})

    # Fallback: save locally
    img_dir = DATA_DIR / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{date_str}_{asset_id}.jpg"
    filepath = img_dir / filename
    uploaded_img.save(str(filepath))

    records = _load_date(date_str)
    for r in records:
        if r.get("asset_id") == asset_id:
            r["replacement_image"] = str(filepath)
            _save_date(date_str, records)
            return jsonify({"ok": True, "matched": False, "replacement_image": str(filepath)})
    return jsonify({"error": "record not found"}), 404


def _extract_exif_time(img):
    """Extract DateTimeOriginal from EXIF, return HKT ISO string or None."""
    try:
        exif = img._getexif() or {}
        dt_str = exif.get(36867) or exif.get(306)  # 36867=DateTimeOriginal, 306=DateTime
        if dt_str:
            dt = datetime.strptime(dt_str, "%Y:%m:%d %H:%M:%S")
            hkt = dt.replace(tzinfo=timezone(timedelta(hours=8)))
            return hkt.isoformat()
    except Exception:
        pass
    return None


def _match_immich_photo(date_str, target_hash, time_window=None, threshold=12):
    """Search Immich for a photo whose pHash matches target_hash.

    If time_window is provided (ISO timestamp), search ±5 minutes around it.
    Otherwise search the full day.
    """
    url = os.getenv("IMMICH_URL", "").rstrip("/")
    try:
        if time_window:
            ts = datetime.fromisoformat(time_window)
            start = (ts - timedelta(minutes=5)).isoformat()
            end = (ts + timedelta(minutes=5)).isoformat()
            size = 50
        else:
            start = f"{date_str}T00:00:00+08:00"
            end = f"{date_str}T23:59:59+08:00"
            size = 500

        body = {"takenAfter": start, "takenBefore": end, "type": "IMAGE", "size": size}
        r = httpx.post(f"{url}/api/search/metadata", json=body, headers=_immich_headers(), timeout=20)
        r.raise_for_status()
        assets = r.json().get("assets", {}).get("items", [])

        best_match = None
        best_dist = threshold + 1
        for asset in assets:
            try:
                rid = asset["id"]
                thumb_r = httpx.get(
                    f"{url}/api/assets/{rid}/thumbnail?size=preview",
                    headers=_immich_headers(), timeout=10,
                )
                thumb_r.raise_for_status()
                thumb = Image.open(io.BytesIO(thumb_r.content)).convert("RGB")
                dist = imagehash.phash(thumb) - target_hash
                if dist < best_dist:
                    best_dist = dist
                    best_match = {
                        "id": rid,
                        "thumbnail_url": f"{url}/api/assets/{rid}/thumbnail?size=preview",
                        "photo_time": asset.get("exifInfo", {}).get("dateTimeOriginal", ""),
                    }
                    if dist <= 2:
                        break
            except Exception:
                continue

        if best_match and best_dist <= threshold:
            return best_match
    except Exception:
        pass
    return None


@app.route("/api/local-image")
def api_local_image():
    path = request.args.get("path", "")
    if not path or not os.path.exists(path):
        return "not found", 404
    return send_from_directory(os.path.dirname(path), os.path.basename(path))


@app.route("/api/finetune-status")
def api_finetune_status():
    MIN_SAMPLES = 4
    labeled = []
    for date_str in _available_dates():
        for r in _load_date(date_str):
            if r.get("user_label"):
                labeled.append({
                    "date": date_str,
                    "asset_id": r.get("asset_id", ""),
                    "meal": r.get("meal", "?"),
                    "label": r["user_label"],
                    "has_replacement": bool(r.get("replacement_image")),
                })

    correct = sum(1 for x in labeled if x["label"] == "correct")
    wrong = sum(1 for x in labeled if x["label"] == "wrong")
    total = len(labeled)

    return jsonify({
        "total": total,
        "correct": correct,
        "wrong": wrong,
        "min_needed": MIN_SAMPLES,
        "ready": total >= MIN_SAMPLES,
        "labeled": labeled,
    })


@app.before_request
def _require_auth():
    if not AUTH_REQUIRED:
        return None
    if request.path.startswith("/api/login") or request.path.startswith("/login"):
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
<title>intake · 登录</title>
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
<h1>intake <span>  </span></h1>
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
    data = request.get_json() or {}
    user = os.getenv("INTAKE_USER", "")
    pwd = os.getenv("INTAKE_PASS", "")
    if data.get("user") == user and data.get("password") == pwd:
        session["auth"] = True
        return jsonify({"ok": True})
    return jsonify({"error": "bad credentials"}), 401


@app.route("/api/logout")
def api_logout():
    session.clear()
    return redirect("/login")


if __name__ == "__main__":
    port = int(os.getenv("INTAKE_PORT", "5800"))
    debug = os.getenv("INTAKE_DEBUG", "0") == "1"
    print(f"  intake Web — http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=debug)
