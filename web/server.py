"""intake Web — mobile-friendly meal records viewer."""
import json
import os
from datetime import datetime, timedelta, timezone, date
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

app = Flask(__name__, static_folder="static", static_url_path="")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
HKT = timezone(timedelta(hours=8))


def _load_date(date_str: str) -> list[dict]:
    path = DATA_DIR / f"{date_str}.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, FileNotFoundError):
        return []


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


if __name__ == "__main__":
    port = int(os.getenv("INTAKE_PORT", "5800"))
    print(f"🍽️  intake Web — http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=True)
