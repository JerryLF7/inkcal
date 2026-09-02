#!/usr/bin/env python3
"""
inkcal — automatic food calorie tracker.

Subcommands:
  run         Full pipeline: Immich → SigLIP2 → Gemini → log
  view        View recorded meals in formatted table
  add         Manually record a meal
  edit        Edit a record's meal/macros/date directly
  search      Search meal descriptions by keyword (FTS5)
  explain     Explain where a photo ended up in the pipeline

Usage:
  inkcal run [--date YYYY-MM-DD]
  inkcal view [--date YYYY-MM-DD] [--week] [--month YYYY-MM] [--json]
  inkcal add --meal "红烧肉" --calories 600 [--protein 25] [--carbs 30] [--fat 20]
  inkcal edit --id PREFIX [--calories 300] [--date YYYY-MM-DD] [--note "..."]
  inkcal search KEYWORD [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--json]
  inkcal explain (--id PREFIX | --date YYYY-MM-DD) [--json]
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
from src.resolver import resolve, resolve_one, ResolverError


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
    run_id: str = "",
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

    food_batch: list[dict] = []
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

        score = detector.score(thumb)
        if score < 0.5:
            logger.info("  ❌ 不是食物，跳过")
            db.add_classified_non_food(aid, decided_by="siglip2")
            if score >= 0.4:  # grey zone — worth a human look
                db.add_event(run_id, "classifier_unsure", aid,
                             {"score": round(score, 3)})
            continue

        logger.info("  🍽️  检测到食物，加入待处理批次")
        food_batch.append({
            "aid": aid,
            "source": source,
            "photo_time": photo_time,
            "thumbnail_url": thumbnail_url,
            "original": original,
        })

    client.close()

    if not food_batch:
        return

    # ── analysis: agent path (gray release) or legacy single-photo path ──
    if os.getenv("AGENT_ENABLED", "0") == "1":
        # Chunk the batch: every photo goes inline (base64) in one Responses
        # request, so a whole-day backfill (20+ originals) would blow past
        # the upstream context/size limits. Steady-state cron ticks see
        # 1-3 photos and stay within a single chunk.
        try:
            max_batch = max(1, int(os.getenv("AGENT_BATCH_SIZE", "6")))
        except ValueError:
            max_batch = 6
        for i in range(0, len(food_batch), max_batch):
            _run_agent_batch(date_str, food_batch[i:i + max_batch],
                             analyzer, run_id=run_id)
    else:
        for item in food_batch:
            _legacy_analyze_single(item, analyzer, run_id=run_id)


def _legacy_analyze_single(item: dict, analyzer, run_id: str = ""):
    """Legacy path: send one photo straight to Gemini and save the record."""
    aid = item["aid"]
    result = analyzer.analyze(item["original"])

    # Gemini may reject non-real-food images (screenshots, menus, etc.).
    # Treat this as an automatic (not user-initiated) non-food decision so
    # the photo remains visible in the album picker for manual correction.
    if result.get("meal") in ("not real food", "unknown"):
        logger.info("  ❌ Gemini 判定非真实食物，加入自动非食物缓存")
        db.add_classified_non_food(aid, decided_by="gemini")
        db.add_event(run_id, "gemini_rejected", aid, None)
        return

    rec = append_log(_date_of(item["photo_time"]), aid, item["photo_time"],
                     item["thumbnail_url"], result,
                     source_type=item["source"])
    logger.info("  ✅ %s ~%skcal", result.get("meal", "?"),
                result.get("calories", 0))

    db.add_event(run_id, "meal_recorded", aid, {
        "record_id": rec.get("id"),
        "meal": rec.get("meal"),
        "calories": rec.get("calories"),
    })
    if rec.get("confidence") == "low":
        db.add_event(run_id, "low_confidence", aid,
                     {"record_id": rec.get("id")})


def _date_of(photo_time: str) -> str:
    """HKT date part of an ISO photo_time string."""
    return (photo_time or "")[:10]


def _run_agent_batch(date_str: str, batch: list[dict], analyzer, *,
                     run_id: str = ""):
    """
    Agent path: hand the whole filtered batch to Luna's harness, apply the
    returned decisions to records + audit table. Falls back to the legacy
    per-photo path when the harness fails (gray-release guarantee).
    """
    from src.agent_harness import AgentHarness

    luna_model = os.getenv("LUNA_MODEL", "gpt-5.6-luna")

    def image_getter(asset_id: str) -> bytes:
        for it in batch:
            if it["aid"] == asset_id:
                return it["original"]
        raise KeyError(asset_id)

    harness = AgentHarness(
        luna_api_key=os.getenv("LUNA_API_KEY", ""),
        luna_base_url=os.getenv("LUNA_BASE_URL") or None,
        luna_model=luna_model,
        deps={"gemini_analyzer": analyzer},
    )
    assets = [{
        "asset_id": it["aid"],
        "photo_time": it["photo_time"],
        "source": it["source"],
        "image_bytes": it["original"],
    } for it in batch]

    decisions = None
    try:
        decisions = harness.run(assets, image_getter)
    finally:
        harness.close()

    if decisions is None:
        logger.warning("  ⚠️ Agent 路径失败，降级旧路径逐张处理 (%d 张)",
                       len(batch))
        for it in batch:
            db.add_event(run_id, "harness_fallback", it["aid"], None)
        for item in batch:
            _legacy_analyze_single(item, analyzer, run_id=run_id)
        return

    session_date = max((_date_of(a["photo_time"]) for a in assets),
                       default=date_str)
    covered: set[str] = set()

    for dec in decisions:
        db.insert_agent_decision(
            session_date,
            {
                "asset_ids": dec.asset_ids,
                "action": dec.action,
                "relation": dec.relation,
                "target_asset_id": dec.target_asset_id,
                "result": dec.result,
                "reasoning": dec.reasoning,
                "prompt_for_gemini": dec.prompt_for_gemini,
            },
            run_id=run_id,
            model_used=luna_model,
        )
        covered.update(dec.asset_ids)
        db.add_event(run_id, "agent_decision", ",".join(dec.asset_ids), {
            "action": dec.action,
            "relation": dec.relation,
            "target_asset_id": dec.target_asset_id,
            "meal": dec.result.get("meal"),
            "calories": dec.result.get("calories"),
        })

        if dec.action == "skip":
            # Luna rejected these photos (non-food etc.) — same handling as
            # the legacy Gemini rejection: keep them visible in album picker.
            for aid in dec.asset_ids:
                db.add_classified_non_food(aid, decided_by="agent")
                logger.info("  ⏭️  skip [%s...] %s", aid[:8],
                            dec.reasoning[:60])
            continue

        if dec.action == "update":
            target = dec.target_asset_id
            ok = False
            if target:
                ok = db.update_record(target, {
                    "meal": dec.result.get("meal"),
                    "calories": dec.result.get("calories"),
                    "protein_g": dec.result.get("protein_g"),
                    "carbs_g": dec.result.get("carbs_g"),
                    "fat_g": dec.result.get("fat_g"),
                    "confidence": dec.result.get("confidence", "low"),
                    "model_used": f"agent+{analyzer.model}",
                })
            if ok:
                logger.info("  🔄 update → [%s...] %s ~%skcal",
                            target[:8], dec.result.get("meal"),
                            dec.result.get("calories"))
            else:
                logger.warning("  ⚠️ update 目标不存在: %s（降级为 add）",
                               target)
                for aid in dec.asset_ids:
                    _agent_add(dec, aid, batch, run_id)
            continue

        # action == "add"
        for aid in dec.asset_ids:
            _agent_add(dec, aid, batch, run_id)

    # Safety net: every photo must be settled exactly once
    missing = [it["aid"] for it in batch if it["aid"] not in covered]
    if missing:
        logger.error("  ❌ 决策未覆盖 %d 张照片，逐张走旧路径: %s",
                     len(missing), [a[:8] for a in missing])
        for it in batch:
            if it["aid"] in missing:
                _legacy_analyze_single(it, analyzer, run_id=run_id)


def _agent_add(dec, aid: str, batch: list[dict], run_id: str):
    """Apply one 'add' decision: insert a record for a single new photo."""
    item = next((it for it in batch if it["aid"] == aid), None)
    if item is None:
        logger.error("  ❌ add 决策引用了批外 asset_id: %s", aid)
        return
    rec = append_log(_date_of(item["photo_time"]), aid, item["photo_time"],
                     item["thumbnail_url"], dec.result,
                     source_type=item["source"])
    logger.info("  ✅ add [%s...] %s ~%skcal", aid[:8],
                dec.result.get("meal"), dec.result.get("calories"))
    db.add_event(run_id, "meal_recorded", aid, {
        "record_id": rec.get("id"),
        "meal": rec.get("meal"),
        "calories": rec.get("calories"),
    })


# ── subcommand: run ──────────────────────────────────────────────────

def cmd_run(args):
    # Single-instance guard: cron runs every 10 min but a Luna harness loop
    # can take much longer (observed ~11 min); an overlapping run would
    # double-process the same photos and leave orphan agent decisions.
    import fcntl

    lock_path = DATA_DIR / "inkcal-run.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_fp = open(lock_path, "w")
    try:
        fcntl.flock(lock_fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        logger.warning("另一个 inkcal run 正在执行，本次跳过 (lock: %s)", lock_path)
        return
    lock_fp.write(str(os.getpid()))
    lock_fp.flush()

    db.init_db()

    from src.food_detector import FoodDetector
    from src.calorie_analyzer import CalorieAnalyzer

    config = load_config()
    sources = _resolve_sources(config)
    run_id = datetime.now().strftime("%Y%m%d%H%M%S") + "-" + os.urandom(3).hex()

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

    stats: dict[str, int] = {}
    for source in sources:
        try:
            _run_source(source, date_str, target_date, detector, analyzer,
                        config, run_id=run_id)
        except Exception as e:
            logger.error("[%s] Pipeline failed: %s", source, e)

    detector.close()
    analyzer.close()

    # Write run summary event
    summary = db.get_run_summary(run_id)
    db.add_event(run_id, "run_summary", None, {"date": date_str, "stats": summary})

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

    try:
        record = resolve_one(asset_prefix=args.id, ref=args.ref,
                             last=args.last, meal=args.meal, date=args.date)
    except ResolverError as e:
        fail(e.code, e.message, candidates=e.candidates)
    aid = record["asset_id"]

    updates = {k: v for k, v in {
        "meal": args.new_meal,
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

    if not updates and not args.note:
        fail("invalid_args",
             "没有要修改的字段（--new-meal/--calories/--protein/--carbs/--fat/"
             "--date/--time/--confidence/--note）")

    # Preserve old values for traceability/rollback before mutating
    note = args.note or ("manual edit" if updates else "note only")
    db.append_reanalysis_history(aid, {
        **{k: record.get(k) for k in
           ("meal", "calories", "protein_g", "carbs_g", "fat_g", "confidence")},
        "notes": note,
    })
    if updates:
        db.update_record(aid, updates)
    new = db.get_record_by_asset_id(aid)

    if _emit({"ok": True, "command": "edit", "record": new}):
        return new

    print(f"✅ 已修改 {aid[:8]}... ({new.get('meal', '?')})")
    for k, v in updates.items():
        if record.get(k) != v:
            print(f"   {k}: {record.get(k)} → {v}")
    return new


# ── subcommand: events ───────────────────────────────────────────────

def cmd_events(args):
    """Pull unconsumed pipeline events so the agent can act on them."""
    db.init_db()

    if not args.consumed:
        events = db.get_unconsumed_events()
        if _emit({"ok": True, "command": "events",
                  "events": events, "count": len(events)}):
            # Mark as consumed after emitting
            if events and not args.peek:
                db.mark_events_consumed([e["id"] for e in events])
            return
        if not events:
            print("📭 没有未消费的事件")
            return
        run_ids = {e["run_id"] for e in events}
        print(f"📬 {len(events)} 个未消费事件 (来自 {len(run_ids)} 次 run):")
        for e in events:
            emoji = {
                "meal_recorded": "✅", "low_confidence": "⚠️",
                "gemini_rejected": "🚫", "classifier_unsure": "🤔",
                "run_summary": "📊",
            }.get(e["event_type"], "📌")
            line = f"  {emoji} {e['event_type']}"
            p = e.get("payload") or {}
            if e["event_type"] == "meal_recorded":
                line += f"  {p.get('meal', '?')} ~{p.get('calories', 0)}kcal"
            elif e["event_type"] == "low_confidence":
                line += f"  record_id={p.get('record_id')}"
            elif e["event_type"] == "classifier_unsure":
                line += f"  {e.get('asset_id', '?')[:8]} score={p.get('score')}"
            elif e["event_type"] == "run_summary":
                line += f"  {p.get('date', '?')}  {p.get('stats', {})}"
            elif e["event_type"] == "gemini_rejected":
                line += f"  {e.get('asset_id', '?')[:8]}"
            print(line)
        if events:
            db.mark_events_consumed([e["id"] for e in events])
        return

    # --consumed mode: show historical events (read-only)
    all_events = []
    conn = db._get_conn()
    limit = args.limit or 100
    rows = conn.execute(
        "SELECT * FROM pipeline_events ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    import json as _json
    for r in rows:
        d = dict(r)
        if d.get("payload") and isinstance(d["payload"], str):
            try:
                d["payload"] = _json.loads(d["payload"])
            except _json.JSONDecodeError:
                pass
        all_events.append(d)
    if _emit({"ok": True, "command": "events", "mode": "history",
              "events": all_events, "count": len(all_events)}):
        return
    print(f"📋 最近 {len(all_events)} 个事件:")
    for e in all_events:
        print(f"  [{e['created_at']}] {e['event_type']}  "
              f"(run {e['run_id'][:12]})")


# ── subcommand: decisions ────────────────────────────────────────────

def cmd_decisions(args):
    """Show the agent decision audit trail for a date."""
    db.init_db()

    date_str = args.date or datetime.now(
        timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    decisions = db.get_decisions_by_date(date_str)

    if _emit({"ok": True, "command": "decisions", "date": date_str,
              "count": len(decisions), "decisions": decisions}):
        return

    if not decisions:
        print(f"🤖 {date_str} 没有 agent 决策记录")
        return

    print(f"🤖 {date_str} 共 {len(decisions)} 条 agent 决策:")
    for d in decisions:
        emoji = {"add": "✅", "update": "🔄", "skip": "⏭️"}.get(
            d["action"], "📌")
        assets = ",".join(a[:8] for a in d.get("asset_ids", []))
        result = d.get("result") or {}
        line = f"  [{d['created_at']}] {emoji} {d['action']}/{d['relation']}"
        line += f"  assets={assets}"
        if d["action"] == "update" and d.get("target_asset_id"):
            line += f" → target={d['target_asset_id'][:8]}"
        if d["action"] != "skip":
            line += f"  {result.get('meal', '?')} ~{result.get('calories', 0)}kcal"
        print(line)
        reasoning = d.get("reasoning") or ""
        if reasoning:
            print(f"      💭 {reasoning}")


# ── subcommand: analyze ──────────────────────────────────────────────

def cmd_analyze(args):
    """Force-analyze an asset, skipping the food-detection step.

    AGENT_ENABLED=1 routes through Luna's harness (agent_decisions audit,
    same estimate baseline as cron); any Luna-layer failure falls back to
    the legacy single-photo Gemini path.
    """
    db.init_db()
    config = load_config()

    if not args.id:
        fail("invalid_args", "analyze 需要 --id（照片的 asset_id）")
    if not config.get("gemini_key"):
        fail("external_error", "GEMINI_API_KEY 未配置，请检查 .env")

    sources = _resolve_sources(config)
    if not sources:
        fail("external_error", "没有启用的照片源")

    # Try to figure out the source; default to first enabled
    source = args.source or sources[0]
    if source not in ("immich", "photoprism"):
        fail("invalid_args", f"未知来源: {source}，应为 immich 或 photoprism")

    from src.pipeline_ops import analyze_asset, _download_original, _resolve_photo_time

    run_id = datetime.now().strftime("%Y%m%d%H%M%S") + "-" + os.urandom(3).hex()
    image_bytes = None
    record = None
    error = None

    if os.getenv("AGENT_ENABLED", "0") == "1" and os.getenv("LUNA_API_KEY", ""):
        from src.pipeline_ops import analyze_assets_via_agent

        image_bytes = _download_original(args.id, source, config)
        if image_bytes is None:
            fail("external_error", f"下载原图失败 [{source}]，请检查照片源是否在线")
        photo_time = _resolve_photo_time(args.id, source, config)

        records, skipped, fallback = analyze_assets_via_agent(
            [{
                "asset_id": args.id,
                "source": source,
                "photo_time": photo_time,
                "image_bytes": image_bytes,
                "thumbnail_url": "",
            }],
            config,
            run_id=run_id,
        )
        if fallback is None:
            if skipped:
                fail("not_food", f"Luna 判定 {args.id[:8]} 非真实食物，不记录")
            if records:
                record = records[0]
            else:
                fail("invalid_args", f"照片 {args.id[:8]} 已经分析过了")
        else:
            logger.warning("agent path fallback (%s), using legacy single-photo",
                           fallback)

    if record is None:
        record, error = analyze_asset(args.id, source, config,
                                      image_bytes=image_bytes)

    if error == "already_processed":
        fail("invalid_args", f"照片 {args.id[:8]} 已经分析过了")
    if error == "download_failed":
        fail("external_error", f"下载原图失败 [{source}]，请检查照片源是否在线")
    if error == "not_food":
        fail("not_food", f"Gemini 判定 {args.id[:8]} 非真实食物，不记录")
    if error == "analysis_failed":
        fail("external_error", f"分析 {args.id[:8]} 失败（模型未返回有效结果），请重试或手动记录")
    if error:
        fail("external_error", f"分析失败: {error}")
    if not record:
        fail("external_error", "分析失败，原因未知")

    if _emit({"ok": True, "command": "analyze", "record": record}):
        return
    print(f"✅ 已分析并记录: {record.get('meal', '?')} ~{record.get('calories', 0)}kcal")


# ── subcommand: reanalyze ────────────────────────────────────────────

def cmd_reanalyze(args):
    """Re-analyze a previously recorded meal with user-provided notes."""
    db.init_db()
    config = load_config()

    if not config.get("gemini_key"):
        fail("external_error", "GEMINI_API_KEY 未配置，请检查 .env")

    try:
        record = resolve_one(asset_prefix=args.id, ref=args.ref,
                             last=args.last, meal=args.meal, date=args.date)
    except ResolverError as e:
        fail(e.code, e.message, candidates=e.candidates)

    if not args.notes:
        fail("invalid_args", "reanalyze 需要 --notes 补充说明（如份量、遗漏食材）")

    from src.pipeline_ops import reanalyze_record
    updated = reanalyze_record(record["asset_id"], args.notes, config)
    if updated is None:
        fail("external_error", "无法获取照片进行重新分析")

    if _emit({"ok": True, "command": "reanalyze", "record": updated}):
        return
    print(f"🔄 已重新分析: {updated.get('meal', '?')} ~{updated.get('calories', 0)}kcal")


# ── subcommand: delete ───────────────────────────────────────────────

def cmd_delete(args):
    db.init_db()

    try:
        record = resolve_one(asset_prefix=args.id, ref=args.ref,
                             last=args.last, meal=args.meal, date=args.date)
    except ResolverError as e:
        fail(e.code, e.message, candidates=e.candidates)

    aid = record["asset_id"]
    replacement_image = record.get("replacement_image", "")

    deleted = db.delete_record(aid)
    if deleted is None:
        fail("not_found", f"删除失败: {aid}")

    # Clean up local replacement image
    if replacement_image:
        try:
            Path(replacement_image).unlink(missing_ok=True)
        except Exception:
            pass

    # Add to ignore list so cron won't re-process
    if aid and not aid.startswith("manual-"):
        db.add_ignored_asset(aid)

    if _emit({"ok": True, "command": "delete", "asset_id": aid,
              "record": deleted}):
        return
    print(f"🗑️  已删除 {aid[:8]}... ({record.get('meal', '?')})")


# ── subcommand: stats ────────────────────────────────────────────────

def _parse_last(s: str) -> tuple[str, str]:
    """Parse '--last 7d' / '2w' / '1m' into (from_date, to_date)."""
    import re
    m = re.match(r"^(\d+)\s*([dwm])$", s)
    if not m:
        fail("invalid_args", f"无法识别的时长: {s}，格式如 7d / 2w / 1m")
    n = int(m.group(1))
    unit = m.group(2)
    today = datetime.now(timezone(timedelta(hours=8)))
    if unit == "m":
        # Approximate: subtract n months
        year, month = today.year, today.month
        month -= n
        while month <= 0:
            year -= 1
            month += 12
        import calendar as cal
        last_day = cal.monthrange(year, month)[1]
        start = today.replace(year=year, month=month, day=min(today.day, last_day))
    else:
        days = n * (7 if unit == "w" else 1)
        start = today - timedelta(days=days)
    return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")


def cmd_stats(args):
    db.init_db()

    if args.last:
        start, end = _parse_last(args.last)
    else:
        start = args.from_date or "1970-01-01"
        end = args.to_date or datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")

    records = db.get_records_by_date_range(start, end)
    summary = db.summarize_records(records)
    days = len({r["photo_time"][:10] for r in records if r.get("photo_time")})
    days = days or 1

    averages = {
        "calories": round(summary["calories"] / days, 1),
        "protein": round(summary["protein"] / days, 1),
        "carbs": round(summary["carbs"] / days, 1),
        "fat": round(summary["fat"] / days, 1),
    }

    payload = {
        "ok": True,
        "command": "stats",
        "range": {"from": start, "to": end},
        "totals": {
            "meals": summary["meals"],
            "calories": summary["calories"],
            "protein": summary["protein"],
            "carbs": summary["carbs"],
            "fat": summary["fat"],
        },
        "daily_averages": averages,
        "days_with_records": days,
    }

    if getattr(args, "group_by", None) == "day":
        by_day: dict[str, dict] = {}
        for r in records:
            dk = r.get("photo_time", "")[:10]
            if dk not in by_day:
                by_day[dk] = {"meals": 0, "calories": 0, "protein": 0,
                              "carbs": 0, "fat": 0}
            t = by_day[dk]
            t["meals"] += 1
            t["calories"] += r.get("calories", 0)
            t["protein"] += r.get("protein_g", 0)
            t["carbs"] += r.get("carbs_g", 0)
            t["fat"] += r.get("fat_g", 0)
        payload["by_day"] = [{"date": d, **v} for d, v in sorted(by_day.items())]

    if _emit(payload):
        return

    t = payload["totals"]
    print(f"{start} → {end}  共 {days} 天  {t['meals']} 餐")
    print(f"  总计: {t['calories']}kcal  蛋白 {t['protein']}g  碳水 {t['carbs']}g  脂肪 {t['fat']}g")
    a = averages
    print(f"  日均: {a['calories']}kcal  蛋白 {a['protein']}g  碳水 {a['carbs']}g  脂肪 {a['fat']}g")


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
    if not args.label:
        fail("invalid_args", "label 需要 --label 参数（结合 --id/--ref/--last/--meal 定位记录）")
    date_str = args.date or datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    label = args.label

    try:
        record = resolve_one(asset_prefix=args.id, ref=args.ref,
                             last=args.last, meal=args.meal, date=date_str)
    except ResolverError as e:
        fail(e.code, e.message, candidates=e.candidates)
    db.update_record(record["asset_id"], {"user_label": label})
    updated = db.get_record_by_asset_id(record["asset_id"])
    if _emit({"ok": True, "command": "label", "record": updated}):
        return
    aid = record["asset_id"][:8]
    print(f"✅ 已标注 [{date_str}] {aid}... {record.get('meal', '?')} → {label}")


# ── subcommand: explain ──────────────────────────────────────────────

_EXPLAIN_HINTS = {
    "siglip2": "本地分类器判定非食物。若为漏判，可在 Web UI「选择照片」手动送 Gemini 分析",
    "gemini": "Gemini 判定非真实食物（截图/菜单/包装等）。如是误判，可在 Web UI 选择照片重新分析",
    "ignored": "用户删除/忽略的照片，pipeline 不再处理",
    "unprocessed": "尚未处理，cron 下一轮会处理；若长期停留，检查照片是否在 SOURCE 配置的相册中",
}

_STATUS_EMOJI = {
    "recorded": "✅",
    "classified_non_food": "🚫",
    "gemini_rejected": "🚫",
    "ignored": "🗑️",
    "unprocessed": "⏳",
}


def _explain_hit_record(r: dict) -> dict:
    return {
        "asset_id": r["asset_id"],
        "status": "recorded",
        "detail": {
            "record_id": r.get("id"),
            "meal": r.get("meal"),
            "calories": r.get("calories"),
            "photo_time": r.get("photo_time"),
        },
    }


def _explain_hit_cnf(e: dict) -> dict:
    by = e["decided_by"]
    return {
        "asset_id": e["asset_id"],
        "status": "gemini_rejected" if by == "gemini" else "classified_non_food",
        "detail": {
            "decided_by": by,
            "classified_at": e["classified_at"],
            "hint": _EXPLAIN_HINTS[by],
        },
    }


def cmd_explain(args):
    db.init_db()

    if args.id:
        hits = (
            [_explain_hit_record(r)
             for r in db.find_records_by_asset_id_prefix(args.id)]
            + [_explain_hit_cnf(e) for e in db.find_classified_non_food(args.id)]
            + [{"asset_id": a, "status": "ignored",
                "detail": {"hint": _EXPLAIN_HINTS["ignored"]}}
               for a in db.find_ignored_assets(args.id)]
        )
        if not hits:
            fail("not_found", f"{args.id} 不在任何本地表中",
                 hint="未处理的照片不会入库，可用 inkcal explain --date 查看当日所有照片状态")
        if len(hits) > 1:
            fail("ambiguous", f"“{args.id}” 匹配到 {len(hits)} 个资产，请提供更长的前缀",
                 candidates=hits)
        hit = hits[0]
        if _emit({"ok": True, "command": "explain", **hit}):
            return
        emoji = _STATUS_EMOJI[hit["status"]]
        print(f"{emoji} {hit['asset_id']}")
        print(f"   状态: {hit['status']}")
        for k, v in hit["detail"].items():
            print(f"   {k}: {v}")
        return

    if not args.date:
        fail("invalid_args", "explain 需要 --id 或 --date 参数")

    date_str = args.date
    config = load_config()
    sources = _resolve_sources(config)
    if not sources:
        fail("external_error", "没有启用的照片源，请检查 .env 的 SOURCE / IMMICH_API_KEY")

    target_date = datetime.strptime(date_str, "%Y-%m-%d").replace(
        tzinfo=timezone(timedelta(hours=8)))

    records_by_asset = {r["asset_id"]: r for r in db.get_records_by_date(date_str)}
    cnf_by_asset = {e["asset_id"]: e for e in db.find_classified_non_food()}
    ignored = set(db.find_ignored_assets())

    assets_out = []
    for source in sources:
        try:
            if source == "immich":
                from src.immich_client import ImmichClient
                client = ImmichClient(config["immich_url"], config["immich_key"])
            elif source == "photoprism":
                from src.photoprism_client import PhotoPrismClient
                client = PhotoPrismClient(config["photoprism_url"], config["photoprism_key"])
            else:
                logger.error("未知来源: %s", source)
                continue
            try:
                assets = client.get_date_assets(target_date)
            finally:
                client.close()
        except Exception as e:
            fail("external_error", f"[{source}] 拉取 {date_str} 照片列表失败: {e}")

        for a in assets:
            aid = a["id"]
            if aid in records_by_asset:
                hit = _explain_hit_record(records_by_asset[aid])
            elif aid in cnf_by_asset:
                hit = _explain_hit_cnf(cnf_by_asset[aid])
            elif aid in ignored:
                hit = {"asset_id": aid, "status": "ignored",
                       "detail": {"hint": _EXPLAIN_HINTS["ignored"]}}
            else:
                hit = {"asset_id": aid, "status": "unprocessed",
                       "detail": {"hint": _EXPLAIN_HINTS["unprocessed"]}}
            hit["source"] = source
            assets_out.append(hit)

    summary: dict[str, int] = {}
    for h in assets_out:
        summary[h["status"]] = summary.get(h["status"], 0) + 1

    if _emit({"ok": True, "command": "explain", "date": date_str,
              "assets": assets_out, "summary": summary}):
        return

    print(f"{date_str}  共 {len(assets_out)} 张照片: "
          + "  ".join(f"{_STATUS_EMOJI[k]}{k}×{v}" for k, v in sorted(summary.items())))
    for h in assets_out:
        line = f"  {_STATUS_EMOJI[h['status']]} {h['asset_id'][:8]}  {h['status']}"
        if h["status"] == "recorded":
            line += f"  {h['detail'].get('meal', '?')} ~{h['detail'].get('calories', 0)}kcal"
        elif h["status"] in ("classified_non_food", "gemini_rejected"):
            line += f"  (by {h['detail']['decided_by']})"
        print(line)


# ── subcommand: replace ────────────────────────────────────────────────

def cmd_replace(args):
    db.init_db()
    from src.immich_client import ImmichClient

    config = load_config()
    date_str = args.date or datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")

    image_path = Path(args.image).expanduser()
    if not image_path.exists():
        fail("invalid_args", f"图片不存在: {image_path}")
    image_bytes = image_path.read_bytes()

    immich = ImmichClient(config["immich_url"], config["immich_key"])
    time_window = ImmichClient.extract_exif_time(image_bytes)
    matched = immich.match_by_phash(date_str, image_bytes, time_window=time_window)
    immich.close()

    try:
        record = resolve_one(asset_prefix=args.id, ref=args.ref,
                             last=args.last, meal=args.meal, date=date_str)
    except ResolverError as e:
        fail(e.code, e.message, candidates=e.candidates)

    if matched:
        db.update_record(record["asset_id"], {
            "thumbnail_url": matched["thumbnail_url"],
            "asset_id": matched["id"],
            "photo_time": matched.get("photo_time", record.get("photo_time", "")),
            "replacement_image": None,
        })
        print(f"✅ 已匹配并替换: {matched['id'][:8]}...")
    else:
        img_dir = DATA_DIR / "images"
        img_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{date_str}_{record['asset_id'][:8]}.jpg"
        filepath = img_dir / filename
        filepath.write_bytes(image_bytes)
        db.update_record(record["asset_id"], {
            "replacement_image": str(filepath),
        })
        print(f"⚠️ 未匹配到 Immich 照片，已保存本地: {filepath}")


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

    def add_locator_args(p):
        """Add --id/--ref/--last/--meal resolver arguments to a subparser."""
        p.add_argument("--id", help="Asset ID (prefix match)")
        p.add_argument("--ref", type=int, help="Record ID (integer, from --json output)")
        p.add_argument("--last", action="store_true",
                       help="Most recent record")
        p.add_argument("--meal", help="Keyword to search meal description")

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
    add_locator_args(p_edit)
    p_edit.add_argument("--new-meal", help="New meal description")
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
    add_locator_args(p_label)
    p_label.add_argument("--label", choices=["correct", "wrong"], help="Label to apply")
    p_label.add_argument("--list", action="store_true", help="List unlabeled records for a date")
    p_label.add_argument("--status", action="store_true", help="Show global labeling progress")
    add_json_flag(p_label)

    p_replace = sub.add_parser("replace", help="Replace a record's image via pHash matching")
    p_replace.add_argument("--date", help="Date (YYYY-MM-DD), defaults to today")
    add_locator_args(p_replace)
    p_replace.add_argument("--image", required=True, help="Path to replacement image")

    p_delete = sub.add_parser("delete", help="Delete a record and ignore the asset")
    p_delete.add_argument("--date", help="Date (YYYY-MM-DD), defaults to today")
    add_locator_args(p_delete)
    add_json_flag(p_delete)

    p_stats = sub.add_parser("stats", help="Aggregate stats over a date range")
    p_stats.add_argument("--from", dest="from_date", help="Range start (YYYY-MM-DD)")
    p_stats.add_argument("--to", dest="to_date", help="Range end (YYYY-MM-DD)")
    p_stats.add_argument("--last", help="Shortcut: 7d / 2w / 1m")
    p_stats.add_argument("--group-by", choices=["day"], help="Break down by day")
    add_json_flag(p_stats)

    p_migrate = sub.add_parser("migrate", help="Migrate JSON files to SQLite")
    p_migrate.add_argument("--force", action="store_true",
                           help="Force re-migration (clears existing DB)")

    p_explain = sub.add_parser("explain", help="Explain where a photo ended up in the pipeline")
    p_explain.add_argument("--id", help="Asset ID (prefix match)")
    p_explain.add_argument("--date", help="List pipeline status of all photos on a date")
    add_json_flag(p_explain)

    p_analyze = sub.add_parser("analyze", help="Force-analyze an asset with Gemini (skip food detection)")
    p_analyze.add_argument("--id", required=True, help="Asset ID of the photo to analyze")
    p_analyze.add_argument("--source", choices=["immich", "photoprism"],
                           help="Photo source (default: first enabled)")
    add_json_flag(p_analyze)

    p_reanalyze = sub.add_parser("reanalyze", help="Re-analyze a record with additional notes")
    add_locator_args(p_reanalyze)
    p_reanalyze.add_argument("--notes", required=True, help="Additional context for reanalysis")
    p_reanalyze.add_argument("--date", help="Date filter for --meal locator")
    add_json_flag(p_reanalyze)

    p_events = sub.add_parser("events", help="Pull unconsumed pipeline events")
    p_events.add_argument("--consumed", action="store_true",
                          help="Show historical events instead of active queue")
    p_events.add_argument("--peek", action="store_true",
                          help="Peek without marking as consumed")
    p_events.add_argument("--limit", type=int, default=100,
                          help="Max events to show (--consumed mode only)")

    p_dec = sub.add_parser("decisions",
                           help="Show agent decision audit trail for a date")
    p_dec.add_argument("--date", help="Date to view (YYYY-MM-DD), defaults to today")
    add_json_flag(p_dec)
    add_json_flag(p_events)

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
    elif args.command == "explain":
        cmd_explain(args)
    elif args.command == "delete":
        cmd_delete(args)
    elif args.command == "stats":
        cmd_stats(args)
    elif args.command == "analyze":
        cmd_analyze(args)
    elif args.command == "reanalyze":
        cmd_reanalyze(args)
    elif args.command == "events":
        cmd_events(args)
    elif args.command == "decisions":
        cmd_decisions(args)


if __name__ == "__main__":
    main()
