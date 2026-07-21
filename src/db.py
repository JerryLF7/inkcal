"""SQLite database layer for inkcal — replaces JSON file storage."""

import sqlite3
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger("inkcal.db")

# Module-level connection (lazy init)
_conn: sqlite3.Connection | None = None
_db_path: Path | None = None

HKT = timezone(timedelta(hours=8))


# ── connection management ────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        if _db_path is None:
            raise RuntimeError("Database not initialized. Call init_db() first.")
        _conn = sqlite3.connect(str(_db_path), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA foreign_keys=ON")
    return _conn


def init_db(db_path: Path | None = None) -> sqlite3.Connection:
    """Initialize the database: set path, create tables/indexes if missing."""
    global _db_path
    if db_path is not None:
        _db_path = db_path
    if _db_path is None:
        _db_path = Path(__file__).resolve().parent.parent / "data" / "inkcal.db"
    _db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = _get_conn()
    _create_schema(conn)
    return conn


def close_db():
    """Close the module-level connection."""
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None


# ── schema ───────────────────────────────────────────────────────────

def _create_schema(conn: sqlite3.Connection):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_id TEXT NOT NULL UNIQUE,
            source_type TEXT NOT NULL DEFAULT 'immich',
            source_id TEXT,
            photo_time TEXT NOT NULL,
            thumbnail_url TEXT,
            original_url TEXT,
            meal TEXT NOT NULL,
            calories REAL NOT NULL DEFAULT 0,
            protein_g REAL NOT NULL DEFAULT 0,
            carbs_g REAL NOT NULL DEFAULT 0,
            fat_g REAL NOT NULL DEFAULT 0,
            confidence TEXT NOT NULL DEFAULT 'low'
                CHECK(confidence IN ('high', 'medium', 'low')),
            analyzed_at TEXT NOT NULL,
            model_used TEXT,
            user_label TEXT CHECK(user_label IN ('correct', 'wrong')),
            replacement_image TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_records_date ON records(date(photo_time));
        CREATE INDEX IF NOT EXISTS idx_records_photo_time ON records(photo_time);
        CREATE INDEX IF NOT EXISTS idx_records_source ON records(source_type, source_id);

        CREATE TABLE IF NOT EXISTS reanalysis_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_id INTEGER NOT NULL REFERENCES records(id) ON DELETE CASCADE,
            meal TEXT NOT NULL,
            calories REAL NOT NULL DEFAULT 0,
            protein_g REAL NOT NULL DEFAULT 0,
            carbs_g REAL NOT NULL DEFAULT 0,
            fat_g REAL NOT NULL DEFAULT 0,
            confidence TEXT NOT NULL DEFAULT 'low',
            notes TEXT,
            reanalyzed_at TEXT NOT NULL,
            history_order INTEGER NOT NULL DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_reanalysis_record_id
            ON reanalysis_history(record_id);

        CREATE TABLE IF NOT EXISTS ignored_assets (
            asset_id TEXT PRIMARY KEY
        );

        CREATE TABLE IF NOT EXISTS classified_non_food (
            asset_id TEXT PRIMARY KEY,
            classified_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_classified_non_food_asset_id
            ON classified_non_food(asset_id);

        -- Full-text search over meal descriptions for quick retrieval
        CREATE VIRTUAL TABLE IF NOT EXISTS records_fts USING fts5(
            meal,
            content='records',
            content_rowid='id'
        );

        -- Triggers keep the FTS index in sync with records writes
        CREATE TRIGGER IF NOT EXISTS records_fts_insert AFTER INSERT ON records BEGIN
            INSERT INTO records_fts(rowid, meal) VALUES (new.id, new.meal);
        END;

        CREATE TRIGGER IF NOT EXISTS records_fts_delete AFTER DELETE ON records BEGIN
            INSERT INTO records_fts(records_fts, rowid, meal) VALUES ('delete', old.id, old.meal);
        END;

        CREATE TRIGGER IF NOT EXISTS records_fts_update AFTER UPDATE OF meal ON records BEGIN
            INSERT INTO records_fts(records_fts, rowid, meal) VALUES ('delete', old.id, old.meal);
            INSERT INTO records_fts(rowid, meal) VALUES (new.id, new.meal);
        END;
        """
    )
    conn.commit()

    # Ensure existing records are indexed (idempotent for new DBs)
    _backfill_fts(conn)


def _backfill_fts(conn: sqlite3.Connection):
    """Backfill FTS index for records created before FTS5 table existed."""
    indexed = conn.execute(
        "SELECT COUNT(*) FROM records_fts"
    ).fetchone()[0]
    total = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
    if indexed >= total:
        return
    logger.info("Backfilling FTS index for %d records...", total - indexed)
    conn.execute("DELETE FROM records_fts")
    conn.execute("INSERT INTO records_fts(rowid, meal) SELECT id, meal FROM records")
    conn.commit()


# ── helpers ──────────────────────────────────────────────────────────

def _extract_date(photo_time: str) -> str:
    """Extract YYYY-MM-DD from ISO 8601 string in HKT."""
    if not photo_time:
        return datetime.now(HKT).strftime("%Y-%m-%d")
    # photo_time format: 2026-05-12T11:49:08.361+08:00
    return photo_time[:10]


def _is_manual(asset_id: str) -> int:
    return 1 if asset_id.startswith("manual-") else 0


def _row_to_dict(row: sqlite3.Row) -> dict:
    """Convert a sqlite3.Row to plain dict (matching existing JSON format)."""
    return dict(row)


def _record_from_row(row: sqlite3.Row, history: list[dict] | None = None) -> dict:
    """Build a record dict matching the existing JSON format."""
    record = {
        "asset_id": row["asset_id"],
        "source_type": row["source_type"],
        "source_id": row["source_id"] or "",
        "photo_time": row["photo_time"],
        "thumbnail_url": row["thumbnail_url"] or "",
        "original_url": row["original_url"] or "",
        "meal": row["meal"],
        "calories": row["calories"],
        "protein_g": row["protein_g"],
        "carbs_g": row["carbs_g"],
        "fat_g": row["fat_g"],
        "confidence": row["confidence"],
        "analyzed_at": row["analyzed_at"],
    }
    if row["model_used"]:
        record["model_used"] = row["model_used"]
    if row["user_label"]:
        record["user_label"] = row["user_label"]
    if row["replacement_image"]:
        record["replacement_image"] = row["replacement_image"]
    if history:
        record["reanalysis_history"] = history
    return record


# ── CRUD: records ────────────────────────────────────────────────────

def insert_record(record: dict) -> dict:
    """Insert a new record. Returns the inserted record (with id added)."""
    conn = _get_conn()
    asset_id = record["asset_id"]
    photo_time = record["photo_time"]

    conn.execute(
        """
        INSERT INTO records (
            asset_id, source_type, source_id, photo_time, thumbnail_url,
            original_url, meal, calories, protein_g, carbs_g, fat_g,
            confidence, analyzed_at, model_used, user_label, replacement_image
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            asset_id,
            record.get("source_type", "immich"),
            record.get("source_id", asset_id),
            photo_time,
            record.get("thumbnail_url", ""),
            record.get("original_url", ""),
            record.get("meal", "unknown"),
            record.get("calories", 0),
            record.get("protein_g", 0),
            record.get("carbs_g", 0),
            record.get("fat_g", 0),
            record.get("confidence", "low"),
            record.get("analyzed_at", datetime.now(HKT).isoformat()),
            record.get("model_used"),
            record.get("user_label"),
            record.get("replacement_image"),
        ),
    )
    conn.commit()

    # Fetch back to get the id and ensure format consistency
    row = conn.execute(
        "SELECT * FROM records WHERE asset_id = ?", (asset_id,)
    ).fetchone()
    return _record_from_row(row)


def get_record_by_asset_id(asset_id: str) -> dict | None:
    """Get a single record by exact asset_id match. Includes reanalysis_history."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM records WHERE asset_id = ?", (asset_id,)
    ).fetchone()
    if row is None:
        return None
    history = get_reanalysis_history(asset_id)
    return _record_from_row(row, history if history else None)


def find_records_by_asset_id_prefix(prefix: str, date_str: str | None = None) -> list[dict]:
    """Find records where asset_id starts with prefix. Optionally filter by date."""
    conn = _get_conn()
    if date_str:
        rows = conn.execute(
            "SELECT * FROM records WHERE asset_id LIKE ? AND date(photo_time) = ?",
            (prefix + "%", date_str),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM records WHERE asset_id LIKE ?", (prefix + "%",)
        ).fetchall()
    return [_record_from_row(r) for r in rows]


def get_records_by_date(date_str: str) -> list[dict]:
    """Get all records for a specific date. Includes reanalysis_history."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM records WHERE date(photo_time) = ? ORDER BY photo_time",
        (date_str,),
    ).fetchall()

    # Batch fetch reanalysis history
    record_ids = [r["id"] for r in rows]
    history_map: dict[int, list[dict]] = {}
    if record_ids:
        placeholders = ",".join("?" * len(record_ids))
        hist_rows = conn.execute(
            f"""
            SELECT h.*, r.asset_id
            FROM reanalysis_history h
            JOIN records r ON h.record_id = r.id
            WHERE r.id IN ({placeholders})
            ORDER BY h.history_order
            """,
            tuple(record_ids),
        ).fetchall()
        for h in hist_rows:
            rid = h["record_id"]
            if rid not in history_map:
                history_map[rid] = []
            history_map[rid].append({
                "meal": h["meal"],
                "calories": h["calories"],
                "protein_g": h["protein_g"],
                "carbs_g": h["carbs_g"],
                "fat_g": h["fat_g"],
                "confidence": h["confidence"],
                "notes": h["notes"],
                "reanalyzed_at": h["reanalyzed_at"],
            })

    return [_record_from_row(r, history_map.get(r["id"])) for r in rows]


def get_records_by_date_range(start: str, end: str) -> list[dict]:
    """Get all records in a date range [start, end]."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM records WHERE date(photo_time) >= ? AND date(photo_time) <= ? ORDER BY photo_time",
        (start, end),
    ).fetchall()
    return [_record_from_row(r) for r in rows]


def search_records(
    keyword: str,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Search meal descriptions using FTS5.

    The keyword is passed through a simple tokenizer helper so callers can
    enter Chinese phrases like "汤咖喱" and still get substring-style hits
    even though FTS5 defaults to token-based matching. We also fall back
    to a LIKE query if FTS5 returns nothing, so partial matches are still shown.
    """
    conn = _get_conn()

    # Build date filter once
    date_filter = ""
    params: list = []
    if start_date and end_date:
        date_filter = " AND date(photo_time) BETWEEN ? AND ?"
        params = [start_date, end_date]
    elif start_date:
        date_filter = " AND date(photo_time) >= ?"
        params = [start_date]
    elif end_date:
        date_filter = " AND date(photo_time) <= ?"
        params = [end_date]

    # Split CJK phrases into individual characters to maximize recall for
    # short/ambiguous queries like "汤咖喱".
    tokens = _tokenize_keyword(keyword)
    fts_query = " ".join(tokens)

    rows = conn.execute(
        f"""
        SELECT r.* FROM records_fts f
        JOIN records r ON r.id = f.rowid
        WHERE f.records_fts MATCH ? {date_filter}
        ORDER BY date(photo_time) DESC, photo_time DESC
        LIMIT ?
        """,
        (fts_query, *params, limit),
    ).fetchall()

    if not rows:
        # Fallback: broad substring search so users still see candidates
        like_pattern = f"%{keyword}%"
        rows = conn.execute(
            f"""
            SELECT * FROM records
            WHERE meal LIKE ? {date_filter}
            ORDER BY photo_time DESC
            LIMIT ?
            """,
            (like_pattern, *params, limit),
        ).fetchall()

    return [_record_from_row(r) for r in rows]


def _tokenize_keyword(keyword: str) -> list[str]:
    """Prepare a keyword for FTS5 MATCH.

    For ASCII words, keep them as tokens. For CJK characters (common in
    meal descriptions), split into individual characters so a query like
    "汤咖喱" matches rows containing any of those characters. This is a
    pragmatic compromise before adding a full CJK tokenizer.
    """
    tokens = []
    for char in keyword.strip():
        if char.isspace():
            continue
        # CJK ranges: Unified Ideographs and Extensions A/B/C/D/E/F
        o = ord(char)
        if (0x4E00 <= o <= 0x9FFF) or (0x3400 <= o <= 0x4DBF) or (
            0x20000 <= o <= 0x2A6DF) or (0x2A700 <= o <= 0x2B73F) or (
            0x2B740 <= o <= 0x2B81F) or (0x2B820 <= o <= 0x2CEAF) or (
            0x2CEB0 <= o <= 0x2EBEF) or (0xF900 <= o <= 0xFAFF):
            tokens.append(char)
        else:
            tokens.append(char)
    return tokens if tokens else [keyword.strip()]


def update_record(asset_id: str, updates: dict) -> bool:
    """Update specific fields of a record. Returns True if found and updated."""
    conn = _get_conn()

    # Map JSON field names to DB columns
    field_map = {
        "thumbnail_url": "thumbnail_url",
        "asset_id": "asset_id",
        "photo_time": "photo_time",
        "original_url": "original_url",
        "meal": "meal",
        "calories": "calories",
        "protein_g": "protein_g",
        "carbs_g": "carbs_g",
        "fat_g": "fat_g",
        "confidence": "confidence",
        "analyzed_at": "analyzed_at",
        "model_used": "model_used",
        "user_label": "user_label",
        "replacement_image": "replacement_image",
    }

    set_clauses = []
    values = []
    new_asset_id = updates.get("asset_id", asset_id)

    for json_key, db_col in field_map.items():
        if json_key in updates:
            if json_key == "asset_id":
                continue  # handled separately
            set_clauses.append(f"{db_col} = ?")
            values.append(updates[json_key])

    if not set_clauses and new_asset_id == asset_id:
        return False

    # If asset_id is changing, update it
    if new_asset_id != asset_id:
        set_clauses.append("asset_id = ?")
        values.append(new_asset_id)

    values.append(asset_id)
    query = f"UPDATE records SET {', '.join(set_clauses)} WHERE asset_id = ?"
    cursor = conn.execute(query, tuple(values))
    conn.commit()
    return cursor.rowcount > 0


def delete_record(asset_id: str) -> dict | None:
    """Delete a record by asset_id. Returns the deleted record (for cleanup) or None."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM records WHERE asset_id = ?", (asset_id,)
    ).fetchone()
    if row is None:
        return None

    record = _record_from_row(row)
    conn.execute("DELETE FROM records WHERE asset_id = ?", (asset_id,))
    conn.commit()
    return record


def move_record(asset_id: str, new_date: str, updates: dict | None = None) -> bool:
    """Move a record to a new date. Updates photo_time date component."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM records WHERE asset_id = ?", (asset_id,)
    ).fetchone()
    if row is None:
        return False

    old_photo_time = row["photo_time"] or ""
    # Preserve time-of-day, change date
    if old_photo_time:
        # Parse: 2026-05-12T11:49:08.361+08:00
        try:
            old_dt = datetime.fromisoformat(old_photo_time)
            tz_offset = old_dt.strftime("%z")  # e.g. +0800
            tz_formatted = f"{tz_offset[:3]}:{tz_offset[3:]}"
            new_photo_time = f"{new_date}T{old_dt.strftime('%H:%M:%S')}{tz_formatted}"
        except ValueError:
            new_photo_time = old_photo_time
    else:
        new_photo_time = f"{new_date}T00:00:00+08:00"

    set_clauses = ["photo_time = ?"]
    values = [new_photo_time]

    if updates:
        field_map = {
            "thumbnail_url": "thumbnail_url",
            "asset_id": "asset_id",
            "photo_time": "photo_time",
            "original_url": "original_url",
            "meal": "meal",
            "calories": "calories",
            "protein_g": "protein_g",
            "carbs_g": "carbs_g",
            "fat_g": "fat_g",
            "confidence": "confidence",
            "replacement_image": "replacement_image",
        }
        for json_key, db_col in field_map.items():
            if json_key in updates:
                if json_key == "asset_id":
                    set_clauses.append("asset_id = ?")
                    values.append(updates[json_key])
                elif json_key == "photo_time":
                    set_clauses.append(f"{db_col} = ?")
                    values.append(updates[json_key])
                else:
                    set_clauses.append(f"{db_col} = ?")
                    values.append(updates[json_key])

    values.append(asset_id)
    cursor = conn.execute(
        f"UPDATE records SET {', '.join(set_clauses)} WHERE asset_id = ?",
        tuple(values),
    )
    conn.commit()
    return cursor.rowcount > 0


# ── reanalysis_history ───────────────────────────────────────────────

def append_reanalysis_history(asset_id: str, entry: dict) -> bool:
    """Append a reanalysis history entry for a record."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT id FROM records WHERE asset_id = ?", (asset_id,)
    ).fetchone()
    if row is None:
        return False

    record_id = row["id"]
    # Determine next order
    max_order = conn.execute(
        "SELECT COALESCE(MAX(history_order), 0) FROM reanalysis_history WHERE record_id = ?",
        (record_id,),
    ).fetchone()[0]

    conn.execute(
        """
        INSERT INTO reanalysis_history (
            record_id, meal, calories, protein_g, carbs_g, fat_g,
            confidence, notes, reanalyzed_at, history_order
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record_id,
            entry.get("meal", "unknown"),
            entry.get("calories", 0),
            entry.get("protein_g", 0),
            entry.get("carbs_g", 0),
            entry.get("fat_g", 0),
            entry.get("confidence", "low"),
            entry.get("notes", ""),
            entry.get("reanalyzed_at", datetime.now(HKT).isoformat()),
            max_order + 1,
        ),
    )
    conn.commit()
    return True


def get_reanalysis_history(asset_id: str) -> list[dict]:
    """Get reanalysis history for a record."""
    conn = _get_conn()
    rows = conn.execute(
        """
        SELECT h.* FROM reanalysis_history h
        JOIN records r ON h.record_id = r.id
        WHERE r.asset_id = ?
        ORDER BY h.history_order
        """,
        (asset_id,),
    ).fetchall()
    return [
        {
            "meal": r["meal"],
            "calories": r["calories"],
            "protein_g": r["protein_g"],
            "carbs_g": r["carbs_g"],
            "fat_g": r["fat_g"],
            "confidence": r["confidence"],
            "notes": r["notes"],
            "reanalyzed_at": r["reanalyzed_at"],
        }
        for r in rows
    ]


# ── ignored_assets ───────────────────────────────────────────────────

def get_ignored_assets() -> set[str]:
    conn = _get_conn()
    rows = conn.execute("SELECT asset_id FROM ignored_assets").fetchall()
    return {r["asset_id"] for r in rows}


def get_classified_non_food() -> set[str]:
    conn = _get_conn()
    rows = conn.execute("SELECT asset_id FROM classified_non_food").fetchall()
    return {r["asset_id"] for r in rows}


def add_classified_non_food(asset_id: str):
    conn = _get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO classified_non_food (asset_id) VALUES (?)",
        (asset_id,),
    )
    conn.commit()


def remove_classified_non_food(asset_id: str):
    conn = _get_conn()
    conn.execute(
        "DELETE FROM classified_non_food WHERE asset_id = ?",
        (asset_id,),
    )
    conn.commit()


def add_ignored_asset(asset_id: str):
    conn = _get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO ignored_assets (asset_id) VALUES (?)",
        (asset_id,),
    )
    conn.commit()


# ── aggregation / utilities ──────────────────────────────────────────

def get_available_dates() -> list[str]:
    """Return dates that have at least one record, newest first."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT DISTINCT date(photo_time) as d FROM records ORDER BY d DESC"
    ).fetchall()
    return [r["d"] for r in rows]


def summarize_records(records: list[dict]) -> dict:
    """Summarize a list of records (same logic as existing _summarize)."""
    return {
        "meals": len(records),
        "calories": sum(r.get("calories", 0) for r in records),
        "protein": sum(r.get("protein_g", 0) for r in records),
        "carbs": sum(r.get("carbs_g", 0) for r in records),
        "fat": sum(r.get("fat_g", 0) for r in records),
    }


def get_processed_asset_ids(date_str: str) -> set[str]:
    """Return set of asset_ids already recorded for a given date."""
    return {r["asset_id"] for r in get_records_by_date(date_str) if r.get("asset_id")}


def get_non_food_asset_ids() -> set[str]:
    """Return set of asset_ids classified as non-food by the local classifier."""
    return get_classified_non_food()


# ── migration ────────────────────────────────────────────────────────

def migrate_from_json(data_dir: Path) -> tuple[int, int, int]:
    """
    Migrate existing JSON files into SQLite.
    Returns (records_migrated, history_entries_migrated, ignored_assets_migrated).
    """
    import json

    conn = _get_conn()
    records_migrated = 0
    history_migrated = 0

    for json_file in sorted(data_dir.glob("*.json")):
        if json_file.stem.count("-") != 2:
            continue  # skip ignored.json and non-date files
        try:
            records = json.loads(json_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            continue

        for record in records:
            asset_id = record.get("asset_id", "")
            if not asset_id:
                continue

            photo_time = record.get("photo_time", "")

            # Insert record
            try:
                conn.execute(
                    """
                    INSERT INTO records (
                        asset_id, source_type, source_id, photo_time, thumbnail_url,
                        original_url, meal, calories, protein_g, carbs_g, fat_g,
                        confidence, analyzed_at, model_used, user_label, replacement_image
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        asset_id,
                        "immich",
                        asset_id,
                        photo_time,
                        record.get("thumbnail_url", ""),
                        "",
                        record.get("meal", "unknown"),
                        record.get("calories", 0),
                        record.get("protein_g", 0),
                        record.get("carbs_g", 0),
                        record.get("fat_g", 0),
                        record.get("confidence", "low"),
                        record.get("analyzed_at", datetime.now(HKT).isoformat()),
                        None,
                        record.get("user_label"),
                        record.get("replacement_image"),
                    ),
                )
                records_migrated += 1
            except sqlite3.IntegrityError:
                # Duplicate asset_id, skip
                continue

            # Migrate reanalysis_history
            history = record.get("reanalysis_history", [])
            if history:
                # Get the record id we just inserted
                row = conn.execute(
                    "SELECT id FROM records WHERE asset_id = ?", (asset_id,)
                ).fetchone()
                if row:
                    record_id = row["id"]
                    for i, entry in enumerate(history):
                        conn.execute(
                            """
                            INSERT INTO reanalysis_history (
                                record_id, meal, calories, protein_g, carbs_g, fat_g,
                                confidence, notes, reanalyzed_at, history_order
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                record_id,
                                entry.get("meal", "unknown"),
                                entry.get("calories", 0),
                                entry.get("protein_g", 0),
                                entry.get("carbs_g", 0),
                                entry.get("fat_g", 0),
                                entry.get("confidence", "low"),
                                entry.get("notes", ""),
                                entry.get("reanalyzed_at", datetime.now(HKT).isoformat()),
                                i,
                            ),
                        )
                        history_migrated += 1

    conn.commit()

    # Migrate ignored.json
    ignored_path = data_dir / "ignored.json"
    ignored_migrated = 0
    if ignored_path.exists():
        try:
            ignored = set(json.loads(ignored_path.read_text(encoding="utf-8")))
            for asset_id in ignored:
                conn.execute(
                    "INSERT OR IGNORE INTO ignored_assets (asset_id) VALUES (?)",
                    (asset_id,),
                )
                ignored_migrated += 1
            conn.commit()
        except (json.JSONDecodeError, FileNotFoundError):
            pass

    return records_migrated, history_migrated, ignored_migrated
