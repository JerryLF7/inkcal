"""intake Web — mobile-friendly meal records viewer."""
import io
import ipaddress
import json
import os
import re
import secrets
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from time import monotonic

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
from PIL import Image
from flask import Flask, jsonify, request, send_from_directory, Response, session, redirect, url_for

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

app = Flask(__name__, static_folder="static", static_url_path="")
app.secret_key = os.getenv("INTAKE_SECRET", secrets.token_hex(32))
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("INTAKE_HTTPS", "0") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    MAX_CONTENT_LENGTH=16 * 1024 * 1024,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
HKT = timezone(timedelta(hours=8))

INTAKE_USER = os.getenv("INTAKE_USER", "")
INTAKE_PASS = os.getenv("INTAKE_PASS", "")

if bool(INTAKE_USER) != bool(INTAKE_PASS):
    raise RuntimeError(
        "INTAKE_USER and INTAKE_PASS must be set together, or both left empty to disable auth."
    )

AUTH_REQUIRED = bool(INTAKE_USER)
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
    immich_url = os.getenv("IMMICH_URL", "").rstrip("/")
    if not url:
        return "missing url", 400
    if not immich_url:
        return "immich not configured", 500
    if not url.startswith(immich_url + "/"):
        return "forbidden", 403
    try:
        r = httpx.get(url, headers=_immich_headers(), timeout=15)
        return Response(r.content, mimetype=r.headers.get("content-type", "image/jpeg"))
    except Exception:
        return "image fetch failed", 502



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
            records = _load_date(date_str)
            for r in records:
                if r.get("asset_id") == asset_id:
                    r["thumbnail_url"] = matched["thumbnail_url"]
                    r["asset_id"] = matched["id"]
                    r["photo_time"] = matched.get("photo_time", r.get("photo_time", ""))
                    r.pop("replacement_image", None)
                    _save_date(date_str, records)
                    return jsonify({"ok": True, "matched": True, "asset_id": matched["id"],
                                    "thumbnail_url": matched["thumbnail_url"]})

    img_dir = DATA_DIR / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    safe_asset = re.sub(r"[^A-Za-z0-9_-]", "_", asset_id)[:64]
    filename = f"{date_str}_{safe_asset}.jpg"
    filepath = img_dir / filename
    filepath.write_bytes(image_bytes)

    records = _load_date(date_str)
    for r in records:
        if r.get("asset_id") == asset_id:
            r["replacement_image"] = str(filepath)
            _save_date(date_str, records)
            return jsonify({"ok": True, "matched": False, "replacement_image": str(filepath)})
    return jsonify({"error": "record not found"}), 404


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
    ip = _client_ip()
    if _login_rate_limited(ip):
        return jsonify({"error": "too many attempts, try again later"}), 429
    data = request.get_json() or {}
    user = os.getenv("INTAKE_USER", "")
    pwd = os.getenv("INTAKE_PASS", "")
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
    host = os.getenv("INTAKE_HOST", "127.0.0.1")
    port = int(os.getenv("INTAKE_PORT", "5800"))
    debug = os.getenv("INTAKE_DEBUG", "0") == "1"
    print(f"  intake Web — http://{host}:{port}")
    app.run(host=host, port=port, debug=debug)
