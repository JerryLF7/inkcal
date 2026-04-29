#!/usr/bin/env python3
"""
intake — automatic food calorie tracker.

Pipeline:
  Immich API → fetch photos → SigLIP2 (local food filter) → Gemini (calories) → log
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv

from src.immich_client import ImmichClient
from src.food_detector import FoodDetector
from src.calorie_analyzer import CalorieAnalyzer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("intake")

DATA_DIR = Path(__file__).resolve().parent / "data"


def load_config():
    load_dotenv()
    return {
        "immich_url": os.getenv("IMMICH_URL", "http://your-immich-host:2283"),
        "immich_key": os.getenv("IMMICH_API_KEY"),
        "gemini_key": os.getenv("GEMINI_API_KEY"),
        "gemini_base_url": os.getenv("GEMINI_BASE_URL"),
        "gemini_model": os.getenv("GEMINI_MODEL", "gemini-3-flash-preview"),
    }


def already_processed(date_str: str) -> set[str]:
    """Check which asset IDs have already been processed for a given date."""
    log_file = DATA_DIR / f"{date_str}.json"
    if not log_file.exists():
        return set()
    try:
        with open(log_file) as f:
            records = json.load(f)
        return {r["asset_id"] for r in records if r.get("asset_id")}
    except (json.JSONDecodeError, FileNotFoundError):
        return set()


def append_log(date_str: str, asset_id: str, photo_time: str, thumbnail_url: str, result: dict):
    """Append analysis result to the given date's log."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    log_file = DATA_DIR / f"{date_str}.json"

    record = {
        "asset_id": asset_id,
        "photo_time": photo_time,
        "thumbnail_url": thumbnail_url,
        "meal": result.get("meal", "unknown"),
        "calories": result.get("calories", 0),
        "protein_g": result.get("protein_g", 0),
        "carbs_g": result.get("carbs_g", 0),
        "fat_g": result.get("fat_g", 0),
        "confidence": result.get("confidence", "low"),
        "analyzed_at": datetime.now(timezone(timedelta(hours=8))).isoformat(),
    }

    if log_file.exists():
        with open(log_file) as f:
            records = json.load(f)
    else:
        records = []

    records.append(record)

    with open(log_file, "w") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)

    return record


def summarize(records: list[dict]):
    """Print a human-readable summary of today's food intake."""
    if not records:
        logger.info("🍽️ 今天没有检测到食物照片。")
        return

    total_cal = sum(r.get("calories", 0) for r in records)
    logger.info("=" * 40)
    logger.info("📊 今日食物热量汇总")
    logger.info("=" * 40)
    for r in records:
        cal = r.get("calories", 0)
        meal = r.get("meal", "unknown")
        conf = r.get("confidence", "low")
        marker = "✅" if conf == "high" else "⚠️" if conf == "medium" else "🤷"
        logger.info(f"  {marker} {meal}: {cal}kcal ({conf})")
    logger.info(f"  合计: {total_cal}kcal")
    logger.info("=" * 40)


def main():
    parser = argparse.ArgumentParser(description="intake — automatic food calorie tracker")
    parser.add_argument("--date", help="Date to process (YYYY-MM-DD), defaults to today")
    args = parser.parse_args()

    config = load_config()

    if not config["immich_key"]:
        logger.error("IMMICH_API_KEY not set in .env")
        sys.exit(1)

    if args.date:
        target_date = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=timezone(timedelta(hours=8)))
        date_str = args.date
    else:
        target_date = datetime.now(timezone(timedelta(hours=8)))
        date_str = target_date.strftime("%Y-%m-%d")

    immich = ImmichClient(config["immich_url"], config["immich_key"])
    detector = FoodDetector()
    analyzer = CalorieAnalyzer(
        config["gemini_key"],
        base_url=config["gemini_base_url"],
        model=config["gemini_model"],
    )

    # Step 1: Fetch photos for the target date
    logger.info("📸 Fetching photos for %s from Immich...", date_str)
    assets = immich.get_date_assets(target_date)
    if not assets:
        logger.info("%s 没有照片。", date_str)
        immich.close()
        detector.close()
        analyzer.close()
        return

    logger.info("%s 共 %d 张照片", date_str, len(assets))

    # Step 2: Check already processed
    processed = already_processed(date_str)
    new_assets = [a for a in assets if a["id"] not in processed]
    logger.info("未处理: %d 张", len(new_assets))

    # Step 3 & 4: Filter by food, then analyze
    food_records = []
    for asset in new_assets:
        aid = asset["id"]
        photo_time = asset.get("exifInfo", {}).get("dateTimeOriginal", "unknown")
        logger.info("  🔍 检测 [%s...] (拍摄于 %s)", aid[:8], photo_time)

        try:
            thumb = immich.download_thumbnail(aid)
        except Exception as e:
            logger.error("  下载缩略图失败: %s", e)
            continue

        if not detector.is_food(thumb):
            logger.info("  ❌ 不是食物，跳过")
            continue

        logger.info("  🍽️  检测到食物! 调 Gemini 分析...")
        thumbnail_url = immich.get_thumbnail_url(aid)
        result = analyzer.analyze(thumb)

        record = append_log(date_str, aid, photo_time, thumbnail_url, result)
        food_records.append(record)
        logger.info("  ✅ %s ~%skcal", result.get("meal", "?"), result.get("calories", 0))

    # Step 5: Summary — re-read the log for a complete picture
    log_file = DATA_DIR / f"{date_str}.json"
    if log_file.exists():
        with open(log_file) as f:
            all_records = json.load(f)
        summarize(all_records)
    else:
        summarize([])

    immich.close()
    detector.close()
    analyzer.close()


if __name__ == "__main__":
    main()
