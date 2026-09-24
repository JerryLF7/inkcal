"""
Test script to run the real pipeline with Luna agent on the 2026-09-21 pasta photos.
Tests whether the new prompt & pipeline contract prevents duplicate counting of the pasta.
"""

import os
import shutil
import sqlite3
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("test_pipeline_21")

from main import load_config
from src import db
from src.pipeline_ops import analyze_assets_via_agent, _get_image_bytes

TEST_DB = Path("/tmp/test_inkcal_21.db")
PROD_DB = Path("data/inkcal.db")

# Assets from 2026-09-21
AID_SALAD = "6199492e-a94d-4ea1-a2f7-15c41e3d1d0b"      # 11:33:05 蔬菜沙拉
AID_PASTA_ONLY = "ab1ad3e8-4cb8-44a1-aa00-4919a810afa0" # 11:44:58 意面配饮料
AID_COMBO = "18e269e7-97f6-41e4-abfa-e1d976cacee8"      # 11:47:31 意面+鸡排+可乐套餐全景

def main():
    cfg = load_config()

    # Step 1: Pre-fetch image bytes for the 3 assets using production DB
    db.init_db(PROD_DB)
    images = {}
    records_info = {}
    for aid in [AID_SALAD, AID_PASTA_ONLY, AID_COMBO]:
        r = db.get_record_by_asset_id(aid)
        assert r, f"asset {aid} not found in prod db"
        records_info[aid] = r
        img = _get_image_bytes(r, cfg)
        assert img, f"image bytes missing for {aid}"
        images[aid] = img

    logger.info("Successfully fetched images for all 3 assets from Immich")

    # Step 2: Prepare isolated test DB
    if TEST_DB.exists():
        TEST_DB.unlink()
    shutil.copy2(PROD_DB, TEST_DB)
    # Also clean wal/shm if present
    for ext in ["-wal", "-shm"]:
        p = Path(str(TEST_DB) + ext)
        if p.exists():
            p.unlink()

    # Delete 2026-09-21 records and agent decisions from test DB
    conn = sqlite3.connect(TEST_DB)
    conn.execute("DELETE FROM records WHERE asset_id IN (?, ?, ?)", (AID_SALAD, AID_PASTA_ONLY, AID_COMBO))
    conn.execute("DELETE FROM classified_non_food WHERE asset_id IN (?, ?, ?)", (AID_SALAD, AID_PASTA_ONLY, AID_COMBO))
    conn.execute("DELETE FROM ignored_assets WHERE asset_id IN (?, ?, ?)", (AID_SALAD, AID_PASTA_ONLY, AID_COMBO))
    conn.commit()
    conn.close()

    # Point db module to TEST_DB
    db.close_db()
    db.init_db(TEST_DB)

    logger.info("=== TEST SCENARIO: Cross-batch ingest (same as 2026-09-21 real event) ===")
    logger.info("Batch 1: Inserting initial pasta-only record (AID_PASTA_ONLY)...")

    # In Batch 1, AID_PASTA_ONLY arrives first
    batch_1 = [{
        "asset_id": AID_PASTA_ONLY,
        "source": "immich",
        "photo_time": records_info[AID_PASTA_ONLY]["photo_time"],
        "image_bytes": images[AID_PASTA_ONLY],
        "thumbnail_url": records_info[AID_PASTA_ONLY]["thumbnail_url"],
    }]
    recs_1, skipped_1, err_1 = analyze_assets_via_agent(batch_1, cfg, run_id="test_run_1")
    logger.info("Batch 1 result: recs=%s, skipped=%s, err=%s", len(recs_1 or []), skipped_1, err_1)
    assert recs_1 and len(recs_1) == 1, "Batch 1 failed to insert record"
    r1 = recs_1[0]
    logger.info("Initial record: [%s] %s ~%skcal", r1["asset_id"][:8], r1["meal"], r1["calories"])

    logger.info("\nBatch 2: Now user submits AID_SALAD and AID_COMBO (combo includes pasta + chicken)...")
    batch_2 = [
        {
            "asset_id": AID_SALAD,
            "source": "immich",
            "photo_time": records_info[AID_SALAD]["photo_time"],
            "image_bytes": images[AID_SALAD],
            "thumbnail_url": records_info[AID_SALAD]["thumbnail_url"],
        },
        {
            "asset_id": AID_COMBO,
            "source": "immich",
            "photo_time": records_info[AID_COMBO]["photo_time"],
            "image_bytes": images[AID_COMBO],
            "thumbnail_url": records_info[AID_COMBO]["thumbnail_url"],
        },
    ]

    recs_2, skipped_2, err_2 = analyze_assets_via_agent(batch_2, cfg, run_id="test_run_2")
    logger.info("Batch 2 result: recs=%s, skipped=%s, err=%s", len(recs_2 or []), skipped_2, err_2)

    # Check final state in DB for 2026-09-21
    day_recs = db.get_records_by_date("2026-09-21")
    logger.info("\n=== RAW RECORDS IN TEST DB ===")
    for r in day_recs:
        logger.info("ID: %s, asset: %s, meal: %s, cal: %s, merged_into: %s",
                    r["id"], r["asset_id"][:8], r["meal"], r["calories"], r.get("merged_into"))

    grouped = db.group_meals(day_recs)
    logger.info("\n=== GROUPED MEALS (AS SEEN BY WEB / USER) ===")
    for g in grouped:
        logger.info("Meal: %s | Total Calories: %skcal | P/C/F: %s/%s/%s",
                    g["meal"], g["calories"], g["protein_g"], g["carbs_g"], g["fat_g"])
        logger.info("Detail: %s", g.get("meal_detail"))
        for p in g.get("photos", []):
            logger.info("  - photo [%s]: meal=%s, cal=%s", p["asset_id"][:8], p.get("meal"), p.get("calories"))

    summary = db.summarize_records(day_recs)
    logger.info("\n=== DAY SUMMARY TOTALS ===")
    logger.info("Total Calories: %skcal (Expected ~1300-1400 kcal, NOT ~2000 kcal!)", summary["calories"])

if __name__ == "__main__":
    main()
