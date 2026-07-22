#!/usr/bin/env python3
"""
inkcal — automatic food calorie tracker.

Subcommands:
  run         Full pipeline: Immich → SigLIP2 → Gemini → log
  view        View recorded meals in formatted table
  add         Manually record a meal
  search      Search meal descriptions by keyword (FTS5)

Usage:
  inkcal run [--date YYYY-MM-DD]
  inkcal view [--date YYYY-MM-DD] [--week] [--month YYYY-MM]
  inkcal add --meal "红烧肉" --calories 600 [--protein 25] [--carbs 30] [--fat 20]
  inkcal search KEYWORD [--from YYYY-MM-DD] [--to YYYY-MM-DD]
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
logger = logging.getLogger("inkcal")

DATA_DIR = Path(__file__).resolve().parent / "data"

from src import db


# ── output helpers (--json / structured errors) ─────────────────────

_JSON_MODE = False

EXIT = {
    "not_found": 2,
    "ambiguous": 3,
    "not_food": 4,
    "invalid_args": 64,
    "external_error": 69,
}


def _emit(payload: dict) -> bool:
    """Print payload as JSON when --json is on. Returns True if handled."""
    if _JSON_MODE:
        print(json.dumps(payload, ensure_ascii=False, default=str))
        return True
    return False


def fail(code: str, message: str, **extra):
    """Structured error exit: machine reads `error`, humans read `message`."""
    if _JSON_MODE:
        print(json.dumps(
            {"ok": False, "error": code, "message": message, **extra},
            ensure_ascii=False, default=str))
    else:
        print(f"❌ {message}")
    sys.exit(EXIT.get(code, 1))


def _brief(record: dict) -> dict:
    """Compact record shape for candidate lists in ambiguous errors."""
    return {
        "id": record.get("id"),
        "asset_id": record.get("asset_id"),
        "meal": record.get("meal"),
        "photo_time": record.get("photo_time"),
        "calories": record.get("calories"),
    }


def _resolve_one(prefix: str, date_str: str | None = None) -> dict:
    """Locate a single record by asset_id prefix, or fail with a structured error."""
    hits = db.find_records_by_asset_id_prefix(prefix, date_str)
    if len(hits) == 1:
        return hits[0]
    if not hits:
        fail("not_found", f"未找到匹配记录: {prefix}")
    fail("ambiguous", f"“{prefix}” 匹配到 {len(hits)} 条记录，请提供更长的前缀",
         candidates=[_brief(h) for h in hits])


# ── helpers ──────────────────────────────────────────────────────────

def load_config():
    from dotenv import load_dotenv
    load_dotenv()
    return {
        "immich_url": os.getenv("IMMICH_URL", "http://your-immich-host:2283"),
        "immich_key": os.getenv("IMMICH_API_KEY"),
        "photoprism_url": os.getenv("PHOTOPRISM_URL", ""),
        "photoprism_key": os.getenv("PHOTOPRISM_API_KEY", ""),
        "gemini_key": os.getenv("GEMINI_API_KEY"),
        "gemini_base_url": os.getenv("GEMINI_BASE_URL"),
        "gemini_model": os.getenv("GEMINI_MODEL", "gemini-3-flash-preview"),
    }


def already_processed(date_str: str) -> set[str]:
    return db.get_processed_asset_ids(date_str)


def load_ignored() -> set[str]:
    return db.get_ignored_assets() | db.get_classified_non_food()


def append_log(date_str: str, asset_id: str, photo_time: str,
               thumbnail_url: str, result: dict, source_type: str = "immich"):
    record = {
        "asset_id": asset_id,
        "source_type": source_type,
        "source_id": asset_id,
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
    return db.insert_record(record)


def load_records(date_str: str) -> list[dict]:
    return db.get_records_by_date(date_str)


# ── multi-source pipeline helper ─────────────────────────────────────

def _resolve_sources(config: dict) -> list[str]:
    """Return list of enabled photo sources from the SOURCE env var.

    Format: comma-separated list, e.g. "immich", "photoprism",
    "immich,photoprism".

    Backwards-compat: if SOURCE is not set but IMMICH_API_KEY is present,
    Immich is enabled automatically (old behaviour).
    """
    source_str = os.getenv("SOURCE", "").strip().lower()
    if source_str:
        return [s.strip() for s in source_str.split(",") if s.strip()]

    # Backwards-compat: old behaviour — auto-enable Immich if key exists
    if config["immich_key"]:
        return ["immich"]
    return []


def _run_source(
    source: str,
    date_str: str,
    target_date: datetime,
    detector,
    analyzer,
    config: dict,
):
    """Run the full pipeline for a single photo source."""
    if source == "immich":
        from src.immich_client import ImmichClient, format_photo_time

        client = ImmichClient(config["immich_url"], config["immich_key"])
        logger.info("📸 [%s] Fetching photos for %s...", source, date_str)
        assets = client.get_date_assets(target_date)
    elif source == "photoprism":
        from src.photoprism_client import PhotoPrismClient

        client = PhotoPrismClient(config["photoprism_url"], config["photoprism_key"])
        logger.info("📸 [%s] Fetching photos for %s...", source, date_str)
        assets = client.get_date_assets(target_date)
    else:
        logger.error("未知来源: %s", source)
        return

    if not assets:
        logger.info("%s [%s] 没有照片。", date_str, source)
        client.close()
        return

    logger.info("%s [%s] 共 %d 张照片", date_str, source, len(assets))

    processed = already_processed(date_str)
    ignored = load_ignored()
    new_assets = [a for a in assets if a["id"] not in processed and a["id"] not in ignored]
    skipped_ignored = len([a for a in assets if a["id"] in ignored])
    logger.info("未处理: %d 张 (忽略 %d 张)", len(new_assets), skipped_ignored)

    for asset in new_assets:
        aid = asset["id"]

        if source == "immich":
            from src.immich_client import format_photo_time

            exif = asset.get("exifInfo", {})
            raw_photo_time = exif.get("dateTimeOriginal", "")
            exif_tz = exif.get("timeZone")
            photo_time = format_photo_time(raw_photo_time, exif_tz)
            try:
                thumb = client.download_thumbnail(aid)
            except Exception as e:
                logger.error("  下载缩略图失败: %s", e)
                continue
            thumbnail_url = client.get_thumbnail_url(aid)
            try:
                original = client.download_original(aid)
            except Exception as e:
                logger.error("  下载原图失败: %s", e)
                continue
        else:  # photoprism
            photo_time = asset["photo_time"]
            file_hash = asset["hash"]
            if not file_hash:
                logger.warning("  [%s] 跳过无 hash 的照片: %s", source, aid[:8])
                continue
            try:
                thumb = client.download_thumbnail(file_hash)
            except Exception as e:
                logger.error("  下载缩略图失败: %s", e)
                continue
            thumbnail_url = client.get_thumbnail_url(file_hash)
            try:
                original = client.download_original(aid)
            except Exception as e:
                logger.error("  下载原图失败: %s", e)
                continue

        logger.info("  🔍 检测 [%s...] (拍摄于 %s)", aid[:8], photo_time)

        if not detector.is_food(thumb):
            logger.info("  ❌ 不是食物，跳过")
            db.add_classified_non_food(aid, decided_by="siglip2")
            continue

        logger.info("  🍽️  检测到食物! 调 Gemini 分析...")
        result = analyzer.analyze(original)

        # Gemini may reject non-real-food images (screenshots, menus, etc.).
        # Treat this as an automatic (not user-initiated) non-food decision so
        # the photo remains visible in the album picker for manual correction.
        if result.get("meal") in ("not real food", "unknown"):
            logger.info("  ❌ Gemini 判定非真实食物，加入自动非食物缓存")
            db.add_classified_non_food(aid, decided_by="gemini")
            continue

        append_log(date_str, aid, photo_time, thumbnail_url, result, source_type=source)
        logger.info("  ✅ %s ~%skcal", result.get("meal", "?"), result.get("calories", 0))

    client.close()


# ── subcommand: run ──────────────────────────────────────────────────

def cmd_run(args):
    db.init_db()

    from src.food_detector import FoodDetector
    from src.calorie_analyzer import CalorieAnalyzer

    config = load_config()
    sources = _resolve_sources(config)

    if not sources:
        logger.error("没有启用的照片源。请在 .env 中设置 SOURCE_IMMICH=1 或 SOURCE_PHOTOPRISM=1")
        sys.exit(1)

    if args.date:
        target_date = datetime.strptime(args.date, "%Y-%m-%d").replace(
            tzinfo=timezone(timedelta(hours=8)))
        date_str = args.date
    else:
        target_date = datetime.now(timezone(timedelta(hours=8)))
        date_str = target_date.strftime("%Y-%m-%d")

    detector = FoodDetector()
    analyzer = CalorieAnalyzer(
        config["gemini_key"],
        base_url=config["gemini_base_url"],
        model=config["gemini_model"],
    )

    for source in sources:
        try:
            _run_source(source, date_str, target_date, detector, analyzer, config)
        except Exception as e:
            logger.error("[%s] Pipeline failed: %s", source, e)

    detector.close()
    analyzer.close()
    cmd_view(argparse.Namespace(
        date=date_str, week=False, month=None, from_date=None, to_date=None))


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
    db.init_db()

    if args.from_date or args.to_date:
        start = args.from_date or "1970-01-01"
        end = args.to_date or datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
        all_records = db.get_records_by_date_range(start, end)
        dates = [start, end]
    else:
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
        if _emit({"ok": True, "command": "view",
                  "range": {"from": dates[0], "to": dates[-1]},
                  "records": [],
                  "summary": {"meals": 0, "calories": 0, "protein": 0,
                              "carbs": 0, "fat": 0}}):
            return
        print("🍽️  暂无记录")
        return

    if _emit({"ok": True, "command": "view",
              "range": {"from": dates[0], "to": dates[-1]},
              "records": all_records,
              "summary": db.summarize_records(all_records)}):
        return all_records

    header = ["ID", "餐食", "热量", "蛋白", "碳水", "脂肪", "时间"]
    rows = []
    daily_totals = {}
    for r in all_records:
        pt = r.get("photo_time", "")
        if pt:
            time_str = pt.replace("T", " ")
            if len(time_str) > 16 and time_str[16] == ':':
                time_str = time_str[:19]  # include seconds
                # append timezone if present
                tz_idx = pt.rfind('+') if '+' in pt else pt.rfind('-')
                if tz_idx > 10:
                    time_str += ' ' + pt[tz_idx:]
            else:
                time_str = time_str[:16]
        else:
            time_str = r.get("analyzed_at", "")[:16]
        rows.append([
            r.get("asset_id", "?")[:8],
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
    db.init_db()
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
    record = append_log(date_str, asset_id, photo_time, "", result, source_type="manual")
    if _emit({"ok": True, "command": "add", "record": record}):
        return record
    logger.info("✅ 已记录: %s  %skcal (%s)", date_str, result["calories"], result["meal"])
    return record


# ── subcommand: edit ─────────────────────────────────────────────────

def cmd_edit(args):
    db.init_db()

    record = _resolve_one(args.id)
    aid = record["asset_id"]

    updates = {k: v for k, v in {
        "meal": args.meal,
        "calories": args.calories,
        "protein_g": args.protein,
        "carbs_g": args.carbs,
        "fat_g": args.fat,
    }.items() if v is not None}

    # Date/time change: rebuild photo_time, preserving untouched components
    if args.date or args.time:
        old_pt = record.get("photo_time", "")
        try:
            old_dt = datetime.fromisoformat(old_pt) if old_pt else None
        except ValueError:
            old_dt = None
        date_part = args.date or (old_pt[:10] if old_pt else
            datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d"))
        if args.time:
            time_part = f"{args.time}:00"
        elif old_dt:
            time_part = old_dt.strftime("%H:%M:%S")
        else:
            time_part = "00:00:00"
        tz_raw = old_dt.strftime("%z") if old_dt and old_dt.tzinfo else "+0800"
        tz_part = f"{tz_raw[:3]}:{tz_raw[3:]}" if tz_raw else "+08:00"
        updates["photo_time"] = f"{date_part}T{time_part}{tz_part}"

    if args.confidence:
        updates["confidence"] = args.confidence
    elif updates:
        updates["confidence"] = "high"  # human correction > model estimate

    if not updates:
        fail("invalid_args",
             "没有要修改的字段（--meal/--calories/--protein/--carbs/--fat/"
             "--date/--time/--confidence）")

    # Preserve old values for traceability/rollback before mutating
    db.append_reanalysis_history(aid, {
        **{k: record.get(k) for k in
           ("meal", "calories", "protein_g", "carbs_g", "fat_g", "confidence")},
        "notes": args.note or "manual edit",
    })
    db.update_record(aid, updates)
    new = db.get_record_by_asset_id(aid)

    if _emit({"ok": True, "command": "edit", "record": new}):
        return new

    print(f"✅ 已修改 {aid[:8]}... ({new.get('meal', '?')})")
    for k, v in updates.items():
        if record.get(k) != v:
            print(f"   {k}: {record.get(k)} → {v}")
    return new


# ── subcommand: search ─────────────────────────────────────────────────

def cmd_search(args):
    db.init_db()

    records = db.search_records(
        keyword=args.keyword,
        start_date=args.from_date,
        end_date=args.to_date,
        limit=args.limit,
    )

    if not records:
        if _emit({"ok": True, "command": "search", "keyword": args.keyword,
                  "records": [], "count": 0}):
            return
        print(f"🍽️  未找到匹配 “{args.keyword}” 的记录")
        return

    if _emit({"ok": True, "command": "search", "keyword": args.keyword,
              "range": {"from": args.from_date, "to": args.to_date},
              "records": records, "count": len(records)}):
        return

    header = ["ID", "餐食", "热量", "蛋白", "碳水", "脂肪", "时间"]
    rows = []
    for r in records:
        pt = r.get("photo_time", "")
        if pt:
            time_str = pt.replace("T", " ")
            if len(time_str) > 16 and time_str[16] == ':':
                time_str = time_str[:19]
                tz_idx = pt.rfind('+') if '+' in pt else pt.rfind('-')
                if tz_idx > 10:
                    time_str += ' ' + pt[tz_idx:]
            else:
                time_str = time_str[:16]
        else:
            time_str = r.get("analyzed_at", "")[:16]
        rows.append([
            r.get("asset_id", "?")[:8],
            r.get("meal", "?")[:20],
            f"{r.get('calories', 0)}kcal",
            f"{r.get('protein_g', 0)}g",
            f"{r.get('carbs_g', 0)}g",
            f"{r.get('fat_g', 0)}g",
            time_str,
        ])

    _print_table(rows, header)
    print(f"\n🔍 找到 {len(records)} 条匹配 “{args.keyword}” 的记录")


# ── subcommand: label ─────────────────────────────────────────────────

def cmd_label(args):
    db.init_db()

    if args.status:
        labeled = []
        for date_str in db.get_available_dates():
            for r in db.get_records_by_date(date_str):
                if r.get("user_label"):
                    labeled.append({
                        "date": date_str,
                        "id": r.get("id"),
                        "asset_id": r.get("asset_id", ""),
                        "meal": r.get("meal", "?"),
                        "label": r["user_label"],
                    })

        correct = sum(1 for x in labeled if x["label"] == "correct")
        wrong = sum(1 for x in labeled if x["label"] == "wrong")
        total = len(labeled)
        if _emit({"ok": True, "command": "label", "mode": "status",
                  "total": total, "correct": correct, "wrong": wrong,
                  "labeled": labeled}):
            return
        print(f"标注进度: {total} 条")
        print(f"  正确: {correct}  有误: {wrong}")
        if labeled:
            print("\n明细:")
            for item in labeled:
                aid = item["asset_id"][:8]
                print(f"  [{item['date']}] {aid}... {item['meal']} → {item['label']}")
        return

    if args.list:
        date_str = args.date or datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
        records = load_records(date_str)
        unlabeled = [r for r in records if not r.get("user_label")]
        if _emit({"ok": True, "command": "label", "mode": "list", "date": date_str,
                  "total": len(records), "unlabeled": unlabeled}):
            return
        if not unlabeled:
            print(f"{date_str}  所有 {len(records)} 条记录已标注")
        else:
            print(f"{date_str}  未标注 {len(unlabeled)}/{len(records)}:")
            for r in unlabeled:
                aid = r.get("asset_id", "?")[:8]
                print(f"  {aid}...  {r.get('meal', '?')}")
        return

    # Label a specific record
    if not args.id or not args.label:
        fail("invalid_args", "label 需要 --id 和 --label 参数")
    date_str = args.date or datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    label = args.label

    record = _resolve_one(args.id, date_str)
    db.update_record(record["asset_id"], {"user_label": label})
    updated = db.get_record_by_asset_id(record["asset_id"])
    if _emit({"ok": True, "command": "label", "record": updated}):
        return
    aid = record["asset_id"][:8]
    print(f"✅ 已标注 [{date_str}] {aid}... {record.get('meal', '?')} → {label}")


# ── subcommand: replace ────────────────────────────────────────────────

def cmd_replace(args):
    db.init_db()
    from src.immich_client import ImmichClient

    config = load_config()
    date_str = args.date or datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")

    image_path = Path(args.image).expanduser()
    if not image_path.exists():
        print(f"❌ 图片不存在: {image_path}")
        sys.exit(1)
    image_bytes = image_path.read_bytes()

    immich = ImmichClient(config["immich_url"], config["immich_key"])
    time_window = ImmichClient.extract_exif_time(image_bytes)
    matched = immich.match_by_phash(date_str, image_bytes, time_window=time_window)
    immich.close()

    records = load_records(date_str)
    for r in records:
        if r.get("asset_id", "").startswith(args.id):
            if matched:
                db.update_record(r["asset_id"], {
                    "thumbnail_url": matched["thumbnail_url"],
                    "asset_id": matched["id"],
                    "photo_time": matched.get("photo_time", r.get("photo_time", "")),
                    "replacement_image": None,
                })
                print(f"✅ 已匹配并替换: {matched['id'][:8]}...")
            else:
                img_dir = DATA_DIR / "images"
                img_dir.mkdir(parents=True, exist_ok=True)
                filename = f"{date_str}_{r['asset_id'][:8]}.jpg"
                filepath = img_dir / filename
                filepath.write_bytes(image_bytes)
                db.update_record(r["asset_id"], {
                    "replacement_image": str(filepath),
                })
                print(f"⚠️ 未匹配到 Immich 照片，已保存本地: {filepath}")
            return
    fail("not_found", f"未找到匹配记录: {args.id}")


# ── subcommand: migrate ────────────────────────────────────────────────

def cmd_migrate(args):
    db_path = DATA_DIR / "inkcal.db"
    if db_path.exists() and not args.force:
        print(f"❌ 数据库已存在: {db_path}")
        print("   使用 --force 强制重新迁移（会清空现有数据）")
        sys.exit(1)

    db.init_db(db_path)
    if args.force:
        conn = db._get_conn()
        conn.execute("DELETE FROM reanalysis_history")
        conn.execute("DELETE FROM records")
        conn.execute("DELETE FROM ignored_assets")
        conn.commit()

    print("🔄 开始迁移 JSON 数据到 SQLite...")
    records, history, ignored = db.migrate_from_json(DATA_DIR)
    print(f"✅ 迁移完成: {records} 条记录, {history} 条历史, {ignored} 条忽略")

    # Backup JSON files
    backup_dir = DATA_DIR / "migrated-json-backup"
    backup_dir.mkdir(exist_ok=True)
    import shutil
    for f in DATA_DIR.glob("*.json"):
        if f.stem.count("-") == 2 or f.name == "ignored.json":
            dest = backup_dir / f.name
            shutil.move(str(f), str(dest))
    print(f"📦 原 JSON 文件已移至: {backup_dir}")


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
        description="inkcal — automatic food calorie tracker")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_json_flag(p):
        p.add_argument("--json", action="store_true",
                       help="Machine-readable JSON output")

    p_run = sub.add_parser("run", help="Run full pipeline (Immich → SigLIP2 → Gemini)")
    p_run.add_argument("--date", help="Date to process (YYYY-MM-DD), defaults to today")

    p_view = sub.add_parser("view", help="View recorded meals")
    p_view.add_argument("--date", help="Date to view (YYYY-MM-DD)")
    p_view.add_argument("--week", action="store_true", help="View this week")
    p_view.add_argument("--month", help="View a month (YYYY-MM)")
    p_view.add_argument("--from", dest="from_date", help="Range start (YYYY-MM-DD)")
    p_view.add_argument("--to", dest="to_date", help="Range end (YYYY-MM-DD)")
    add_json_flag(p_view)

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
    add_json_flag(p_add)

    p_edit = sub.add_parser("edit", help="Edit a record's meal/macros/date directly")
    p_edit.add_argument("--id", required=True, help="Asset ID (prefix match)")
    p_edit.add_argument("--meal", help="New meal description")
    p_edit.add_argument("--calories", type=int, help="New calories (kcal)")
    p_edit.add_argument("--protein", type=int, help="New protein (g)")
    p_edit.add_argument("--carbs", type=int, help="New carbs (g)")
    p_edit.add_argument("--fat", type=int, help="New fat (g)")
    p_edit.add_argument("--confidence", choices=["high", "medium", "low"],
                        help="New confidence (defaults to high on edit)")
    p_edit.add_argument("--date", help="Move record to this date (YYYY-MM-DD)")
    p_edit.add_argument("--time", help="New time (HH:MM)")
    p_edit.add_argument("--note", help="Note saved to reanalysis history")
    add_json_flag(p_edit)

    p_search = sub.add_parser("search", help="Search meal descriptions by keyword (FTS5)")
    p_search.add_argument("keyword", help="Search keyword, e.g. 汤咖喱 or 咖喱")
    p_search.add_argument("--from", dest="from_date", help="Start date (YYYY-MM-DD)")
    p_search.add_argument("--to", dest="to_date", help="End date (YYYY-MM-DD)")
    p_search.add_argument("--limit", type=int, default=50, help="Max results (default 50)")
    add_json_flag(p_search)

    p_label = sub.add_parser("label", help="Label records")
    p_label.add_argument("--date", help="Date (YYYY-MM-DD), defaults to today")
    p_label.add_argument("--id", help="Asset ID (prefix match)")
    p_label.add_argument("--label", choices=["correct", "wrong"], help="Label to apply")
    p_label.add_argument("--list", action="store_true", help="List unlabeled records for a date")
    p_label.add_argument("--status", action="store_true", help="Show global labeling progress")
    add_json_flag(p_label)

    p_replace = sub.add_parser("replace", help="Replace a record's image via pHash matching")
    p_replace.add_argument("--date", help="Date (YYYY-MM-DD), defaults to today")
    p_replace.add_argument("--id", required=True, help="Asset ID to replace (prefix match)")
    p_replace.add_argument("--image", required=True, help="Path to replacement image")

    p_migrate = sub.add_parser("migrate", help="Migrate JSON files to SQLite")
    p_migrate.add_argument("--force", action="store_true",
                           help="Force re-migration (clears existing DB)")

    args = parser.parse_args()

    global _JSON_MODE
    _JSON_MODE = getattr(args, "json", False)

    if args.command == "run":
        cmd_run(args)
    elif args.command == "view":
        cmd_view(args)
    elif args.command == "add":
        cmd_add(args)
    elif args.command == "edit":
        cmd_edit(args)
    elif args.command == "search":
        cmd_search(args)
    elif args.command == "label":
        cmd_label(args)
    elif args.command == "replace":
        cmd_replace(args)
    elif args.command == "migrate":
        cmd_migrate(args)


if __name__ == "__main__":
    main()
