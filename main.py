#!/usr/bin/env python3
"""
intake — automatic food calorie tracker.

Subcommands:
  run         Full pipeline: Immich → SigLIP2 → Gemini → log
  view        View recorded meals in formatted table
  add         Manually record a meal

Usage:
  intake run [--date YYYY-MM-DD]
  intake view [--date YYYY-MM-DD] [--week] [--month YYYY-MM]
  intake add --meal "红烧肉" --calories 600 [--protein 25] [--carbs 30] [--fat 20]
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("intake")

DATA_DIR = Path(__file__).resolve().parent / "data"


# ── helpers ──────────────────────────────────────────────────────────

def load_config():
    from dotenv import load_dotenv
    load_dotenv()
    return {
        "immich_url": os.getenv("IMMICH_URL", "http://your-immich-host:2283"),
        "immich_key": os.getenv("IMMICH_API_KEY"),
        "gemini_key": os.getenv("GEMINI_API_KEY"),
        "gemini_base_url": os.getenv("GEMINI_BASE_URL"),
        "gemini_model": os.getenv("GEMINI_MODEL", "gemini-3-flash-preview"),
    }


def already_processed(date_str: str) -> set[str]:
    log_file = DATA_DIR / f"{date_str}.json"
    if not log_file.exists():
        return set()
    try:
        with open(log_file) as f:
            records = json.load(f)
        return {r["asset_id"] for r in records if r.get("asset_id")}
    except (json.JSONDecodeError, FileNotFoundError):
        return set()


def append_log(date_str: str, asset_id: str, photo_time: str,
               thumbnail_url: str, result: dict):
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

    records = json.loads(log_file.read_text()) if log_file.exists() else []
    records.append(record)
    log_file.write_text(json.dumps(records, indent=2, ensure_ascii=False))
    return record


def load_records(date_str: str) -> list[dict]:
    log_file = DATA_DIR / f"{date_str}.json"
    if not log_file.exists():
        return []
    try:
        return json.loads(log_file.read_text())
    except json.JSONDecodeError:
        return []


# ── subcommand: run ──────────────────────────────────────────────────

def cmd_run(args):
    from src.immich_client import ImmichClient
    from src.food_detector import FoodDetector
    from src.calorie_analyzer import CalorieAnalyzer

    config = load_config()

    if not config["immich_key"]:
        logger.error("IMMICH_API_KEY not set in .env")
        sys.exit(1)

    if args.date:
        target_date = datetime.strptime(args.date, "%Y-%m-%d").replace(
            tzinfo=timezone(timedelta(hours=8)))
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

    logger.info("📸 Fetching photos for %s from Immich...", date_str)
    assets = immich.get_date_assets(target_date)
    if not assets:
        logger.info("%s 没有照片。", date_str)
        immich.close(); detector.close(); analyzer.close()
        return

    logger.info("%s 共 %d 张照片", date_str, len(assets))

    processed = already_processed(date_str)
    new_assets = [a for a in assets if a["id"] not in processed]
    logger.info("未处理: %d 张", len(new_assets))

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

    immich.close(); detector.close(); analyzer.close()
    cmd_view(argparse.Namespace(date=date_str, week=False, month=None))


# ── subcommand: view ─────────────────────────────────────────────────

def _print_table(rows: list[list[str]], header: list[str]):
    """Simple terminal table. Rows: list of string columns."""
    if not rows:
        return
    col_widths = [
        max(len(str(r[i])) for r in rows + [header])
        for i in range(len(header))
    ]
    sep = "─" * (sum(col_widths) + len(header) * 3 + 1)
    hr = "─" * (sum(col_widths) + len(header) * 3 + 1)
    print(hr)
    print("│ " + " │ ".join(h.ljust(w) for h, w in zip(header, col_widths)) + " │")
    print(sep)
    for row in rows:
        print("│ " + " │ ".join(
            (str(r) if i == 0 else str(r).rjust(w))
            for i, (r, w) in enumerate(zip(row, col_widths))
        ) + " │")
    print(hr)


def cmd_view(args):
    if args.week:
        today = datetime.now(timezone(timedelta(hours=8)))
        # Monday of this week
        monday = today - timedelta(days=today.weekday())
        dates = [(monday + timedelta(days=i)).strftime("%Y-%m-%d")
                 for i in range(7)]
    elif args.month:
        year, month = args.month.split("-")
        import calendar
        last_day = calendar.monthrange(int(year), int(month))[1]
        dates = [f"{args.month}-{d:02d}" for d in range(1, last_day + 1)]
    elif args.date:
        dates = [args.date]
    else:
        dates = [datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")]

    all_records = []
    for d in dates:
        all_records.extend(load_records(d))

    if not all_records:
        print("🍽️  暂无记录")
        return

    header = ["餐食", "热量", "蛋白", "碳水", "脂肪", "时间"]
    rows = []
    daily_totals = {}
    for r in all_records:
        time_str = r.get("photo_time", "").replace("T", " ")[:16]
        if not time_str:
            time_str = r.get("analyzed_at", "")[:16]
        rows.append([
            r.get("meal", "?")[:20],
            f"{r.get('calories', 0)}kcal",
            f"{r.get('protein_g', 0)}g",
            f"{r.get('carbs_g', 0)}g",
            f"{r.get('fat_g', 0)}g",
            time_str,
        ])
        date_key = time_str[:10] if time_str else "?"
        t = daily_totals.setdefault(date_key, {"cal": 0, "protein": 0, "carbs": 0, "fat": 0})
        t["cal"] += r.get("calories", 0)
        t["protein"] += r.get("protein_g", 0)
        t["carbs"] += r.get("carbs_g", 0)
        t["fat"] += r.get("fat_g", 0)

    _print_table(rows, header)

    # Daily summaries
    for date_key, t in sorted(daily_totals.items()):
        mark = "✅" if t["cal"] < 2500 else "⚠️"
        print(f"\n{mark} {date_key}  合计: {t['cal']}kcal  "
              f"蛋白 {t['protein']}g  碳水 {t['carbs']}g  脂肪 {t['fat']}g")

    # Grand total if multiple days
    if len(daily_totals) > 1:
        gt = sum(t["cal"] for t in daily_totals.values())
        print(f"\n📊 共 {len(daily_totals)} 天，总计 {gt}kcal")

    return all_records


# ── subcommand: add ──────────────────────────────────────────────────

def cmd_add(args):
    from datetime import datetime, timezone, timedelta

    if args.date:
        date_str = args.date
    else:
        date_str = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")

    if args.time:
        photo_time = f"{date_str}T{args.time}:00+08:00"
    else:
        photo_time = datetime.now(timezone(timedelta(hours=8))).isoformat()

    result = {
        "meal": args.meal,
        "calories": args.calories,
        "protein_g": args.protein,
        "carbs_g": args.carbs,
        "fat_g": args.fat,
        "confidence": args.confidence,
    }

    asset_id = f"manual-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    record = append_log(date_str, asset_id, photo_time, "", result)
    logger.info("✅ 已记录: %s  %skcal (%s)", date_str, result["calories"], result["meal"])
    return record


# ── subcommand: serve ─────────────────────────────────────────────────

def cmd_serve(args):
    """Start the web UI server."""
    port = args.port
    web_dir = Path(__file__).resolve().parent / "web"
    os.chdir(web_dir)
    os.execvp(sys.executable, [sys.executable, "server.py"])
    # Note: os.execvp replaces the process, so this never returns


# ── entry point ──────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="intake — automatic food calorie tracker")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="Run full pipeline (Immich → SigLIP2 → Gemini)")
    p_run.add_argument("--date", help="Date to process (YYYY-MM-DD), defaults to today")

    p_view = sub.add_parser("view", help="View recorded meals")
    p_view.add_argument("--date", help="Date to view (YYYY-MM-DD)")
    p_view.add_argument("--week", action="store_true", help="View this week")
    p_view.add_argument("--month", help="View a month (YYYY-MM)")

    p_add = sub.add_parser("add", help="Manually record a meal")
    p_add.add_argument("--meal", required=True, help="Meal description")
    p_add.add_argument("--calories", type=int, required=True, help="Calories (kcal)")
    p_add.add_argument("--protein", type=int, default=0, help="Protein (g)")
    p_add.add_argument("--carbs", type=int, default=0, help="Carbs (g)")
    p_add.add_argument("--fat", type=int, default=0, help="Fat (g)")
    p_add.add_argument("--date", help="Date (YYYY-MM-DD), defaults to today")
    p_add.add_argument("--time", help="Time (HH:MM), defaults to now")
    p_add.add_argument("--confidence", default="medium",
                       choices=["high", "medium", "low"])

    args = parser.parse_args()

    if args.command == "run":
        cmd_run(args)
    elif args.command == "view":
        cmd_view(args)
    elif args.command == "add":
        cmd_add(args)


if __name__ == "__main__":
    main()
