"""Simulate one cron tick that picks up TWO new photos (2026-08-26 lunch).

Isolated: INKCAL_DB=/tmp/inkcal-test.db (copy of prod with records 179/180
purged). Photos re-downloaded from Immich; SigLIP2 runs for real; the Luna
harness runs for real (Gemini included). Decisions ARE applied to the test
DB so the post-conditions can be checked. Prod DB untouched.

Run: PYTHONPATH=. venv/bin/python scripts/test_luna_cron_two_photos.py
"""

import json
import logging
import os
import shutil
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

os.environ["INKCAL_DB"] = "/tmp/inkcal-test.db"

sys.path.insert(0, ".")

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

# ── 0. prepare isolated db: fresh copy of prod, with the two target
#       records purged so cron sees them as NEW photos ───────────────
for suffix in ("", "-wal", "-shm"):
    try:
        os.remove("/tmp/inkcal-test.db" + suffix)
    except FileNotFoundError:
        pass
shutil.copy("data/inkcal.db", "/tmp/inkcal-test.db")

import src.db as db  # noqa: E402
import src.agent_harness as ah  # noqa: E402
from main import (  # noqa: E402
    _run_agent_batch, already_processed, load_config, load_ignored,
)
from src.calorie_analyzer import CalorieAnalyzer  # noqa: E402
from src.food_detector import FoodDetector  # noqa: E402
from src.immich_client import ImmichClient, format_photo_time  # noqa: E402

db.init_db()

# Debug hooks: raw Luna output + token usage (same spy style as test_luna_lunch)
_orig_call = ah.AgentHarness._call_luna

def _spy_call(self, input_items, *, previous_response_id=None):
    resp = _orig_call(self, input_items, previous_response_id=previous_response_id)
    u = getattr(resp, "usage", None)
    print(f"  [resp] status={resp.status} "
          f"in={getattr(u, 'input_tokens', '?')} out={getattr(u, 'output_tokens', '?')}")
    return resp

ah.AgentHarness._call_luna = _spy_call

_orig_parse = ah.parse_decisions_json

def _spy_parse(text):
    try:
        return _orig_parse(text)
    except ValueError:
        print(f"  [raw output, {len(text)} chars] >>>{text}<<<")
        raise

ah.parse_decisions_json = _spy_parse

DATE = "2026-08-26"
ASSET_IDS = [
    "1a51d328-5cd7-4c4d-98d5-1eb6943e4a8d",  # 11:35 外卖盒饭
    "41ca6def-83eb-4c91-8853-612ad6d9bd25",  # 11:48 外卖便当
]

# Purge existing rows for these assets in the TEST db (simulates "new photos")
_conn = db._get_conn()
_conn.execute(
    f"DELETE FROM records WHERE asset_id IN ({','.join('?' for _ in ASSET_IDS)})",
    ASSET_IDS)
_conn.execute(
    f"DELETE FROM classified_non_food WHERE asset_id IN ({','.join('?' for _ in ASSET_IDS)})",
    ASSET_IDS)
_conn.commit()

config = load_config()
client = ImmichClient(config["immich_url"], config["immich_key"])
run_id = "sim-" + __import__("time").strftime("%Y%m%d%H%M%S")

# ── 1. simulate cron pickup: filter like _run_source does ────────────
processed = already_processed(DATE)
ignored = load_ignored()
food_batch = []
detector = FoodDetector()
for aid in ASSET_IDS:
    assert aid not in processed and aid not in ignored, f"{aid[:8]} still processed?!"
    meta = client._client.get(f"/api/assets/{aid}")
    meta.raise_for_status()
    exif = meta.json().get("exifInfo", {})
    photo_time = format_photo_time(exif.get("dateTimeOriginal", ""), exif.get("timeZone"))
    thumb = client.download_thumbnail(aid)
    score = detector.score(thumb)
    print(f"{aid[:8]}: siglip2 score={score:.3f} @ {photo_time}")
    if score < 0.5:
        print(f"  ❌ SigLIP2 would filter this out — simulation ends here")
        sys.exit(1)
    food_batch.append({
        "aid": aid,
        "source": "immich",
        "photo_time": photo_time,
        "thumbnail_url": client.get_thumbnail_url(aid),
        "original": client.download_original(aid),
    })
detector.close()
client.close()

# ── 2. agent path exactly as _run_source would call it ───────────────
analyzer = CalorieAnalyzer(
    config["gemini_key"],
    base_url=config["gemini_base_url"],
    model=config["gemini_model"],
)
_run_agent_batch(DATE, food_batch, analyzer, run_id=run_id)
analyzer.close()

# ── 3. post-conditions on the TEST db ────────────────────────────────
print("\n===== post-conditions (test db) =====")
raw = [r for r in db.get_records_by_date(DATE) if r["asset_id"] in ASSET_IDS]
for r in raw:
    print(json.dumps({k: r.get(k) for k in
                      ("id", "asset_id", "meal", "calories", "photo_time",
                       "confidence", "merged_into")},
                     ensure_ascii=False, indent=1))
meals = [m for m in db.group_meals(db.get_records_by_date(DATE))
         if m["asset_id"] in ASSET_IDS]
non_food = [a for a in ASSET_IDS
            if db._get_conn().execute(
                "SELECT 1 FROM classified_non_food WHERE asset_id=?", (a,)).fetchone()]
decisions = db.get_decisions_by_date(DATE)
mine = [d for d in decisions
        if set(d.get("asset_ids") or []) & set(ASSET_IDS)
        and (d.get("run_id") or "") == run_id]
print(f"raw rows: {len(raw)}  |  grouped cards: {len(meals)}  |  "
      f"photos on card: {[len(m['photos']) for m in meals]}  |  "
      f"non-food: {len(non_food)}  |  decisions: {len(mine)}  |  run_id={run_id}")

# Expectation (same-meal pair): ONE card carrying both photos, counted once.
if len(meals) == 1 and len(meals[0]["photos"]) == 2:
    print("✅ same-meal merge: ONE card, both photos attached, counted once")
elif len(meals) == 2:
    print("⚠️ Luna split into two separate meals — inspect reasoning above")
else:
    print("⚠️ unexpected shape — inspect rows above")
