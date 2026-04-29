"Quick scan: classify food/not-food for given dates, no Gemini."
import argparse
import logging
import os
import sys
from datetime import datetime, timezone, timedelta

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, "src")
from immich_client import ImmichClient
from food_detector import FoodDetector

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("scan")

parser = argparse.ArgumentParser(description="Quick food/not-food scan for given dates")
date_group = parser.add_mutually_exclusive_group(required=True)
date_group.add_argument("--date", help="Single date (YYYY-MM-DD)")
date_group.add_argument("--dates", help="Comma-separated dates (YYYY-MM-DD,YYYY-MM-DD,...)")
args = parser.parse_args()

if args.date:
    dates = [args.date]
else:
    dates = [d.strip() for d in args.dates.split(",")]

immich = ImmichClient(
    os.getenv("IMMICH_URL", "http://192.168.5.7:2283"),
    os.getenv("IMMICH_API_KEY"),
)
detector = FoodDetector()

total = 0
food_count = 0

for d in dates:
    target = datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone(timedelta(hours=8)))
    assets = immich.get_date_assets(target)
    logger.info("%s: %d photos", d, len(assets))
    total += len(assets)

    for a in assets:
        try:
            thumb = immich.download_thumbnail(a["id"])
            is_food = detector.is_food(thumb)
            aid = a["id"][:8]
            photo_time = a.get("exifInfo", {}).get("dateTimeOriginal", "?")
            if is_food:
                food_count += 1
                logger.info("  ✅ FOOD: %s (%s)", aid, photo_time)
            else:
                logger.info("  ❌ not:  %s (%s)", aid, photo_time)
        except Exception as e:
            logger.error("  fail: %s", e)

logger.info("=== Total: %d photos, %d food ===", total, food_count)
immich.close()
detector.close()
