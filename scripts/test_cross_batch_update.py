"""
Test cross-batch update (state-continuation):
Photo 1 (0f6271ed, 11:33, full meal) already exists in DB as 1150 kcal.
Photo 2 (157efe12, 11:46, leftovers) arrives in a new cron batch.
Luna should:
  1. Inspect get_recent_meals (finding 0f6271ed with meal_detail).
  2. Call analyze_with_gemini with BOTH asset_ids: [0f6271ed, 157efe12] and a prompt describing before/after.
  3. Emit an update decision on target_asset_id=0f6271ed with actual consumption calories (~880 kcal).
  4. DB should update 0f6271ed to the new combined values, and record 157efe12 as 0 kcal merged_into 0f6271ed.
"""

import json
import logging
import os
import shutil
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

TEST_DB = "/tmp/inkcal-test-update.db"
for suffix in ("", "-wal", "-shm"):
    try:
        os.remove(TEST_DB + suffix)
    except FileNotFoundError:
        pass
shutil.copy("data/inkcal.db", TEST_DB)
os.environ["INKCAL_DB"] = TEST_DB

sys.path.insert(0, ".")

from dotenv import load_dotenv
load_dotenv()

import src.db as db
from pathlib import Path
db.init_db(Path(TEST_DB))

from main import _run_agent_batch, load_config
from src.calorie_analyzer import CalorieAnalyzer
from src.immich_client import ImmichClient, format_photo_time

AID_1 = "0f6271ed-1bd4-4def-ba85-cbafa0d6504e"  # 11:33 before
AID_2 = "157efe12-615e-4629-b9c2-0bf81effce01"  # 11:46 after

# Reset AID_1 to initial unmerged state (1150 kcal), delete AID_2
conn = db._get_conn()
conn.execute("DELETE FROM records WHERE asset_id = ?", (AID_2,))
conn.execute("DELETE FROM classified_non_food WHERE asset_id = ?", (AID_2,))
conn.execute("""
    UPDATE records SET
        meal = '中式外卖盒饭',
        meal_detail = '白米饭，糖醋里脊，木耳炒鸡蛋，油爆虾，芹菜炒腐竹',
        calories = 1150.0,
        protein_g = 50.0,
        carbs_g = 111.0,
        fat_g = 57.0,
        confidence = 'high',
        merged_into = NULL
    WHERE asset_id = ?
""", (AID_1,))
conn.commit()

config = load_config()
immich = ImmichClient(config["immich_url"], config["immich_key"])

# Fetch AID_2 metadata and original bytes
meta2 = immich._client.get(f"/api/assets/{AID_2}").json()
exif2 = meta2.get("exifInfo", {})
raw_pt2 = exif2.get("dateTimeOriginal", "")
exif_tz2 = exif2.get("timeZone")
pt2 = format_photo_time(raw_pt2, exif_tz2)
orig2 = immich.download_original(AID_2)
thumb_url2 = immich.get_thumbnail_url(AID_2)
immich.close()

batch = [{
    "aid": AID_2,
    "source": "immich",
    "photo_time": pt2,
    "thumbnail_url": thumb_url2,
    "original": orig2,
}]

analyzer = CalorieAnalyzer(
    config["gemini_key"],
    base_url=config.get("gemini_base_url"),
    model=config.get("gemini_model", "gemini-3-flash-preview"),
)

print(f"\n===== Running _run_agent_batch with new photo {AID_2[:8]} =====")
_run_agent_batch("2026-09-15", batch, analyzer, run_id="test-update-run", config=config)
analyzer.close()

print("\n===== Checking Results in Test DB =====")
r1 = db.get_record_by_asset_id(AID_1)
r2 = db.get_record_by_asset_id(AID_2)

print("Record 1 (Target):")
print(f"  meal: {r1.get('meal')}")
print(f"  detail: {r1.get('meal_detail')}")
print(f"  calories: {r1.get('calories')}")
print(f"  macros: P={r1.get('protein_g')}, C={r1.get('carbs_g')}, F={r1.get('fat_g')}")
print(f"  merged_into: {r1.get('merged_into')}")

print("\nRecord 2 (New):")
print(f"  meal: {r2.get('meal')}")
print(f"  detail: {r2.get('meal_detail')}")
print(f"  calories: {r2.get('calories')}")
print(f"  merged_into: {r2.get('merged_into')}")

dec = conn.execute("SELECT action, relation, target_asset_id, prompt_for_gemini, reasoning, result FROM agent_decisions WHERE run_id = 'test-update-run'").fetchone()
if dec:
    print("\nDecision logged:")
    print(f"  action: {dec['action']}, relation: {dec['relation']}, target: {dec['target_asset_id']}")
    print(f"  prompt_for_gemini: {dec['prompt_for_gemini']}")
    print(f"  reasoning: {dec['reasoning']}")
    print(f"  result: {dec['result']}")

# Assertions
assert r1["calories"] > 500, f"Expected combined calories to reflect actual consumption (>500), got {r1['calories']}"
assert r2["calories"] == 0, f"Expected child row to be 0 cal, got {r2['calories']}"
assert r2["merged_into"] == AID_1, f"Expected child to merge into {AID_1}, got {r2['merged_into']}"
print("\n🎉 ALL CHECKS PASSED!")
