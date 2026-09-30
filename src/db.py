"""SQLite database layer for inkcal — replaces JSON file storage."""

import json
import os
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
    if _db_path is None and os.environ.get("INKCAL_DB"):
        _db_path = Path(os.environ["INKCAL_DB"])
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
            meal_detail TEXT NOT NULL DEFAULT '',
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
            merged_into TEXT,
            emoji TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_records_local_date ON records(substr(photo_time, 1, 10));
        CREATE INDEX IF NOT EXISTS idx_records_photo_time ON records(photo_time);
        CREATE INDEX IF NOT EXISTS idx_records_source ON records(source_type, source_id);

        CREATE TABLE IF NOT EXISTS reanalysis_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_id INTEGER NOT NULL REFERENCES records(id) ON DELETE CASCADE,
            meal TEXT NOT NULL,
            meal_detail TEXT NOT NULL DEFAULT '',
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

        -- Agent decision audit trail. Business data lives in `records`;
        -- this table persists what the agent decided (including skip
        -- decisions, which have no records row) for auditing and tuning.
        CREATE TABLE IF NOT EXISTS agent_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_date TEXT NOT NULL,
            run_id TEXT,
            asset_ids TEXT NOT NULL,
            action TEXT NOT NULL CHECK(action IN ('add', 'update', 'skip')),
            relation TEXT NOT NULL CHECK(relation IN ('new_meal', 'same_meal', 'rejected')),
            target_asset_id TEXT,
            group_with TEXT,
            result TEXT NOT NULL,
            reasoning TEXT NOT NULL,
            prompt_for_gemini TEXT,
            model_used TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_agent_decisions_date
            ON agent_decisions(session_date);

        -- Daily calorie burn & step counts from wearable sync / manual input
        CREATE TABLE IF NOT EXISTS daily_burn (
            date TEXT PRIMARY KEY,
            active_kcal REAL NOT NULL DEFAULT 0,
            steps INTEGER NOT NULL DEFAULT 0,
            source TEXT NOT NULL DEFAULT 'heytap-ui',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        -- Full-text search over meal title + detail for quick retrieval
        CREATE VIRTUAL TABLE IF NOT EXISTS records_fts USING fts5(
            meal,
            meal_detail,
            content='records',
            content_rowid='id'
        );

        -- Triggers keep the FTS index in sync with records writes
        CREATE TRIGGER IF NOT EXISTS records_fts_insert AFTER INSERT ON records BEGIN
            INSERT INTO records_fts(rowid, meal, meal_detail)
                VALUES (new.id, new.meal, new.meal_detail);
        END;

        CREATE TRIGGER IF NOT EXISTS records_fts_delete AFTER DELETE ON records BEGIN
            INSERT INTO records_fts(records_fts, rowid, meal, meal_detail)
                VALUES ('delete', old.id, old.meal, old.meal_detail);
        END;

        CREATE TRIGGER IF NOT EXISTS records_fts_update
            AFTER UPDATE OF meal, meal_detail ON records BEGIN
            INSERT INTO records_fts(records_fts, rowid, meal, meal_detail)
                VALUES ('delete', old.id, old.meal, old.meal_detail);
            INSERT INTO records_fts(rowid, meal, meal_detail)
                VALUES (new.id, new.meal, new.meal_detail);
        END;
        """
    )
    conn.commit()

    _migrate_schema(conn)

    # Ensure existing records are indexed (idempotent for new DBs)
    _backfill_fts(conn)


def _migrate_schema(conn: sqlite3.Connection):
    """Idempotent column/table additions for databases created before a certain version."""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(classified_non_food)")}
    if "decided_by" not in cols:
        conn.execute(
            "ALTER TABLE classified_non_food "
            "ADD COLUMN decided_by TEXT NOT NULL DEFAULT 'siglip2'"
        )
        conn.commit()

    rcols = {r["name"] for r in conn.execute("PRAGMA table_info(records)")}
    if "merged_into" not in rcols:
        # Same-meal grouping: NULL = 主记录（一餐一行）; 非 NULL = 附属照片行，
        # 指向该餐主记录的 asset_id。附属行有两种形态：
        #   状态延续（同一食物吃前/吃后）→ 数值为 0，总值只在主行；
        #   独立条目（同餐不同食物分开拍）→ 携带自己的数值，组内求和。
        conn.execute("ALTER TABLE records ADD COLUMN merged_into TEXT")
        conn.commit()

    if "meal_detail" not in rcols:
        # 主标题/副标题拆分（2026-09-13）：meal = 短标题（餐型概括），
        # meal_detail = 菜品明细。旧记录不回填，meal 保持整句话、detail 为空。
        conn.execute(
            "ALTER TABLE records ADD COLUMN meal_detail TEXT NOT NULL DEFAULT ''")
        conn.commit()

    hcols = {r["name"] for r in conn.execute("PRAGMA table_info(reanalysis_history)")}
    if "meal_detail" not in hcols:
        conn.execute(
            "ALTER TABLE reanalysis_history "
            "ADD COLUMN meal_detail TEXT NOT NULL DEFAULT ''")
        conn.commit()

    # FTS 表加 meal_detail 列：fts5 不支持 ALTER，整表重建（触发器一并换新），
    # 随后由 _backfill_fts 重新索引。
    fcols = {r["name"] for r in conn.execute("PRAGMA table_info(records_fts)")}
    if "meal_detail" not in fcols:
        conn.executescript("""
            DROP TRIGGER IF EXISTS records_fts_insert;
            DROP TRIGGER IF EXISTS records_fts_delete;
            DROP TRIGGER IF EXISTS records_fts_update;
            DROP TABLE IF EXISTS records_fts;
            CREATE VIRTUAL TABLE records_fts USING fts5(
                meal, meal_detail, content='records', content_rowid='id'
            );
            CREATE TRIGGER records_fts_insert AFTER INSERT ON records BEGIN
                INSERT INTO records_fts(rowid, meal, meal_detail)
                    VALUES (new.id, new.meal, new.meal_detail);
            END;
            CREATE TRIGGER records_fts_delete AFTER DELETE ON records BEGIN
                INSERT INTO records_fts(records_fts, rowid, meal, meal_detail)
                    VALUES ('delete', old.id, old.meal, old.meal_detail);
            END;
            CREATE TRIGGER records_fts_update
                AFTER UPDATE OF meal, meal_detail ON records BEGIN
                INSERT INTO records_fts(records_fts, rowid, meal, meal_detail)
                    VALUES ('delete', old.id, old.meal, old.meal_detail);
                INSERT INTO records_fts(rowid, meal, meal_detail)
                    VALUES (new.id, new.meal, new.meal_detail);
            END;
        """)
        conn.commit()

    dcols = {r["name"] for r in conn.execute("PRAGMA table_info(agent_decisions)")}
    if "group_with" not in dcols:
        # 审计 add 决策的 group_with（形态 B 独立条目入组）
        conn.execute("ALTER TABLE agent_decisions ADD COLUMN group_with TEXT")
        conn.commit()

    if "emoji" not in rcols:
        conn.execute("ALTER TABLE records ADD COLUMN emoji TEXT")
        conn.commit()

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS pipeline_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            run_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            asset_id TEXT,
            payload TEXT,
            consumed INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_events_consumed ON pipeline_events(consumed);

        -- Chat (conversational agent) state. Business data stays in records;
        -- these tables persist conversation history so the Luna Responses
        -- chain (previous_response_id) is only a rebuildable cache.
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
            role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
            content TEXT NOT NULL,
            tool_log TEXT,
            response_id TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_chat_messages_session
            ON chat_messages(session_id, id);

        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS daily_burn (
            date TEXT PRIMARY KEY,
            active_kcal REAL NOT NULL DEFAULT 0,
            steps INTEGER NOT NULL DEFAULT 0,
            source TEXT NOT NULL DEFAULT 'heytap-ui',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    conn.commit()


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
    conn.execute(
        "INSERT INTO records_fts(rowid, meal, meal_detail) "
        "SELECT id, meal, meal_detail FROM records")
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
        "id": row["id"],
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
    try:
        record["meal_detail"] = row["meal_detail"] or ""
    except (KeyError, IndexError):
        record["meal_detail"] = ""  # SELECT 子集不带该列
    if row["model_used"]:
        record["model_used"] = row["model_used"]
    if row["user_label"]:
        record["user_label"] = row["user_label"]
    if row["replacement_image"]:
        record["replacement_image"] = row["replacement_image"]
    try:
        if row["merged_into"]:
            record["merged_into"] = row["merged_into"]
    except (KeyError, IndexError):
        pass  # pre-migration rows / SELECT subsets without the column
    try:
        if row["emoji"]:
            record["emoji"] = row["emoji"]
    except (KeyError, IndexError):
        pass
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
            original_url, meal, meal_detail, calories, protein_g, carbs_g, fat_g,
            confidence, analyzed_at, model_used, user_label, replacement_image,
            merged_into, emoji
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            asset_id,
            record.get("source_type", "immich"),
            record.get("source_id", asset_id),
            photo_time,
            record.get("thumbnail_url", ""),
            record.get("original_url", ""),
            record.get("meal", "unknown"),
            record.get("meal_detail", ""),
            record.get("calories", 0),
            record.get("protein_g", 0),
            record.get("carbs_g", 0),
            record.get("fat_g", 0),
            record.get("confidence", "low"),
            record.get("analyzed_at", datetime.now(HKT).isoformat()),
            record.get("model_used"),
            record.get("user_label"),
            record.get("replacement_image"),
            record.get("merged_into"),
            record.get("emoji", "") or "",
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


def get_record_by_id(record_id: int) -> dict | None:
    """Get a single record by its integer primary key. Includes reanalysis_history."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM records WHERE id = ?", (record_id,)
    ).fetchone()
    if row is None:
        return None
    history = get_reanalysis_history(row["asset_id"])
    return _record_from_row(row, history if history else None)


def find_records_by_asset_id_prefix(prefix: str, date_str: str | None = None) -> list[dict]:
    """Find records where asset_id starts with prefix. Optionally filter by date."""
    conn = _get_conn()
    if date_str:
        rows = conn.execute(
            "SELECT * FROM records WHERE asset_id LIKE ? AND substr(photo_time, 1, 10) = ?",
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
        "SELECT * FROM records WHERE substr(photo_time, 1, 10) = ? ORDER BY photo_time",
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
                "meal_detail": h["meal_detail"] or "",
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
        "SELECT * FROM records WHERE substr(photo_time, 1, 10) >= ? AND substr(photo_time, 1, 10) <= ? ORDER BY photo_time",
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
        date_filter = " AND substr(photo_time, 1, 10) BETWEEN ? AND ?"
        params = [start_date, end_date]
    elif start_date:
        date_filter = " AND substr(photo_time, 1, 10) >= ?"
        params = [start_date]
    elif end_date:
        date_filter = " AND substr(photo_time, 1, 10) <= ?"
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
        ORDER BY substr(photo_time, 1, 10) DESC, photo_time DESC
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
            WHERE (meal LIKE ? OR meal_detail LIKE ?) {date_filter}
            ORDER BY photo_time DESC
            LIMIT ?
            """,
            (like_pattern, like_pattern, *params, limit),
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
        "meal_detail": "meal_detail",
        "calories": "calories",
        "protein_g": "protein_g",
        "carbs_g": "carbs_g",
        "fat_g": "fat_g",
        "confidence": "confidence",
        "analyzed_at": "analyzed_at",
        "model_used": "model_used",
        "user_label": "user_label",
        "replacement_image": "replacement_image",
        "merged_into": "merged_into",
        "emoji": "emoji",
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

    set_clauses.append("updated_at = datetime('now')")
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


def delete_record_group(asset_id: str) -> list[dict] | None:
    """删除整餐：asset_id 所在同餐组的所有行（主+从）。
    返回被删行列表（主行在前），未找到返回 None。"""
    conn = _get_conn()
    root_id = resolve_group_root(asset_id)
    rows = get_group_rows(root_id)
    if not rows:
        return None
    ids = [r["asset_id"] for r in rows]
    placeholders = ",".join("?" for _ in ids)
    conn.execute(f"DELETE FROM records WHERE asset_id IN ({placeholders})", ids)
    conn.commit()
    prim = [r for r in rows if not r.get("merged_into")]
    return prim + [r for r in rows if r.get("merged_into")]


def delete_record_photo(asset_id: str) -> tuple[dict, str | None] | None:
    """仅删除一张照片行。若删的是主行且仍有从行，最早从行晋升为主行
    （形态 A 下晋升行为 0 值，需用户重分析补回数值）。
    返回 (deleted_row, promoted_asset_id|None)，未找到返回 None。"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM records WHERE asset_id = ?", (asset_id,)
    ).fetchone()
    if row is None:
        return None
    record = _record_from_row(row)
    promoted = None
    children: list[str] = []
    if not record.get("merged_into"):
        children = [r["asset_id"] for r in conn.execute(
            "SELECT asset_id FROM records WHERE merged_into = ?"
            " ORDER BY photo_time", (asset_id,)).fetchall()]
    conn.execute("DELETE FROM records WHERE asset_id = ?", (asset_id,))
    if children:
        promoted = children[0]
        conn.execute(
            "UPDATE records SET merged_into = NULL WHERE asset_id = ?",
            (promoted,))
        rest = children[1:]
        if rest:
            placeholders = ",".join("?" for _ in rest)
            conn.execute(
                f"UPDATE records SET merged_into = ?"
                f" WHERE asset_id IN ({placeholders})",
                (promoted, *rest))
    conn.commit()
    return record, promoted


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
            "meal_detail": "meal_detail",
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

    set_clauses.append("updated_at = datetime('now')")
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
            record_id, meal, meal_detail, calories, protein_g, carbs_g, fat_g,
            confidence, notes, reanalyzed_at, history_order
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record_id,
            entry.get("meal", "unknown"),
            entry.get("meal_detail", ""),
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


def add_classified_non_food(asset_id: str, decided_by: str = "siglip2"):
    conn = _get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO classified_non_food (asset_id, decided_by) VALUES (?, ?)",
        (asset_id, decided_by),
    )
    conn.commit()


def find_classified_non_food(prefix: str | None = None) -> list[dict]:
    """List classified_non_food entries, optionally filtered by asset_id prefix."""
    conn = _get_conn()
    if prefix:
        rows = conn.execute(
            "SELECT * FROM classified_non_food WHERE asset_id LIKE ?",
            (prefix + "%",),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM classified_non_food").fetchall()
    return [dict(r) for r in rows]


def find_ignored_assets(prefix: str | None = None) -> list[str]:
    """List ignored asset_ids, optionally filtered by prefix."""
    conn = _get_conn()
    if prefix:
        rows = conn.execute(
            "SELECT asset_id FROM ignored_assets WHERE asset_id LIKE ?",
            (prefix + "%",),
        ).fetchall()
    else:
        rows = conn.execute("SELECT asset_id FROM ignored_assets").fetchall()
    return [r["asset_id"] for r in rows]


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
        "SELECT DISTINCT substr(photo_time, 1, 10) as d FROM records ORDER BY d DESC"
    ).fetchall()
    return [r["d"] for r in rows]


def summarize_records(records: list[dict]) -> dict:
    """Summarize a list of records (same logic as existing _summarize).

    数值：所有行直接求和——同餐组的附属行要么是 0 值（状态延续），
    要么携带自己的数值（独立条目），两种形态求和都正确。
    餐数：只数主记录（merged_into 为空）。
    """
    return {
        "meals": sum(1 for r in records if not r.get("merged_into")),
        "calories": sum(r.get("calories", 0) for r in records),
        "protein": sum(r.get("protein_g", 0) for r in records),
        "carbs": sum(r.get("carbs_g", 0) for r in records),
        "fat": sum(r.get("fat_g", 0) for r in records),
    }


# ── same-meal grouping (merged_into) ─────────────────────────────────

def resolve_group_root(asset_id: str) -> str:
    """Walk merged_into to the group's primary asset_id (returns input if
    already primary / not found)."""
    conn = _get_conn()
    current, seen = asset_id, set()
    while current and current not in seen:
        seen.add(current)
        row = conn.execute(
            "SELECT merged_into FROM records WHERE asset_id = ?", (current,)
        ).fetchone()
        if row is None or not row["merged_into"]:
            return current
        current = row["merged_into"]
    return asset_id


def get_group_rows(primary_asset_id: str) -> list[dict]:
    """Primary + merged rows of one meal group, sorted by photo_time."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM records WHERE asset_id = ? OR merged_into = ?"
        " ORDER BY photo_time",
        (primary_asset_id, primary_asset_id),
    ).fetchall()
    return [_record_from_row(r) for r in rows]


def group_meals(records: list[dict]) -> list[dict]:
    """Group raw record rows into meals: returns only primary records, each
    with a `photos` array (primary first, then merged rows by photo_time).

    Cross-date safe: merged rows whose photo_time falls outside the queried
    range (cross-midnight meals) are fetched via one extra query.
    Orphan merged rows (primary missing) are dropped from top level.
    """
    primaries = []
    by_asset = {}
    stray: list[dict] = []
    for r in records:
        if r.get("merged_into"):
            stray.append(r)
        else:
            p_record = dict(r)  # 浅拷贝，避免原地修改传入的原始记录列表污染外部统计
            p_record["photos"] = [{
                "asset_id": r["asset_id"],
                "thumbnail_url": r.get("thumbnail_url", ""),
                "photo_time": r.get("photo_time", ""),
                "meal": r.get("meal", ""),
                "meal_detail": r.get("meal_detail", ""),
                "calories": r.get("calories", 0),
                "protein_g": r.get("protein_g", 0),
                "carbs_g": r.get("carbs_g", 0),
                "fat_g": r.get("fat_g", 0),
                "emoji": r.get("emoji", "") or "",
            }]
            primaries.append(p_record)
            by_asset[r["asset_id"]] = p_record

    if not primaries:
        return []

    # Merged rows can live outside the queried date range (cross-midnight)
    conn = _get_conn()
    placeholders = ",".join("?" for _ in primaries)
    extra = conn.execute(
        f"SELECT * FROM records WHERE merged_into IN ({placeholders})",
        tuple(r["asset_id"] for r in primaries),
    ).fetchall()
    members = [r for r in stray]
    seen = {r["asset_id"] for r in stray}
    for row in extra:
        d = _record_from_row(row)
        if d["asset_id"] not in seen:
            members.append(d)
            seen.add(d["asset_id"])

    for m in sorted(members, key=lambda x: x.get("photo_time") or ""):
        root = by_asset.get(m["merged_into"])
        if root is None:
            continue  # orphan: primary不在本次查询范围，属于另一天的卡片
        root["photos"].append({
            "asset_id": m["asset_id"],
            "thumbnail_url": m.get("thumbnail_url", ""),
            "photo_time": m.get("photo_time", ""),
            "meal": m.get("meal", ""),
            "meal_detail": m.get("meal_detail", ""),
            "calories": m.get("calories", 0),
            "protein_g": m.get("protein_g", 0),
            "carbs_g": m.get("carbs_g", 0),
            "fat_g": m.get("fat_g", 0),
            "emoji": m.get("emoji", "") or "",
        })

    # 形态 B 组头聚合（数值累加 + 餐名与明细拼接）
    for root in primaries:
        photos = root.get("photos", [])
        if len(photos) <= 1:
            continue

        has_form_b = False
        item_names = []
        detail_parts = []

        main_meal = (root.get("meal") or "").strip()
        if main_meal and main_meal not in ("📷", "?"):
            item_names.append(main_meal)
        main_detail = (root.get("meal_detail") or "").strip()
        if main_detail:
            detail_parts.append(main_detail)

        for p in photos:
            if p["asset_id"] == root["asset_id"]:
                continue
            is_form_b_row = bool(
                p.get("calories") or p.get("protein_g") or p.get("carbs_g") or p.get("fat_g")
            )
            if is_form_b_row:
                has_form_b = True
                p_meal = (p.get("meal") or "").strip()
                if p_meal and p_meal not in ("📷", "?") and p_meal not in item_names:
                    item_names.append(p_meal)
                p_detail = (p.get("meal_detail") or "").strip()
                if p_detail:
                    if p_meal and p_meal != main_meal:
                        detail_parts.append(f"{p_meal}: {p_detail}")
                    else:
                        detail_parts.append(p_detail)

        if has_form_b:
            # 组头数值为组内所有照片合计（对齐 summarize_records）
            root["calories"] = round(sum(p.get("calories", 0) for p in photos), 1)
            root["protein_g"] = round(sum(p.get("protein_g", 0) for p in photos), 1)
            root["carbs_g"] = round(sum(p.get("carbs_g", 0) for p in photos), 1)
            root["fat_g"] = round(sum(p.get("fat_g", 0) for p in photos), 1)

            # 主标题体现独立条目组合
            if len(item_names) > 1:
                root["meal"] = " + ".join(item_names)

            # 明细体现组合明细
            if detail_parts:
                root["meal_detail"] = "；".join(detail_parts)

    return primaries


def get_processed_asset_ids(date_str: str) -> set[str]:
    """Return set of asset_ids already recorded for a given date."""
    return {r["asset_id"] for r in get_records_by_date(date_str) if r.get("asset_id")}


def get_non_food_asset_ids() -> set[str]:
    """Return set of asset_ids classified as non-food by the local classifier."""
    return get_classified_non_food()


# ── pipeline_events ──────────────────────────────────────────────────

def add_event(run_id: str, event_type: str, asset_id: str | None = None,
              payload: dict | None = None):
    """Record a pipeline event for later consumption by the agent."""
    import json
    conn = _get_conn()
    conn.execute(
        """INSERT INTO pipeline_events (run_id, event_type, asset_id, payload)
           VALUES (?, ?, ?, ?)""",
        (run_id, event_type, asset_id,
         json.dumps(payload, ensure_ascii=False) if payload else None),
    )
    conn.commit()


def get_unconsumed_events() -> list[dict]:
    """Fetch all unconsumed events, newest first."""
    import json
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM pipeline_events WHERE consumed = 0 ORDER BY id DESC"
    ).fetchall()
    events = []
    for r in rows:
        d = dict(r)
        if d.get("payload") and isinstance(d["payload"], str):
            try:
                d["payload"] = json.loads(d["payload"])
            except json.JSONDecodeError:
                pass
        events.append(d)
    return events


def mark_events_consumed(event_ids: list[int]):
    """Mark a batch of events as consumed."""
    if not event_ids:
        return
    conn = _get_conn()
    placeholders = ",".join("?" * len(event_ids))
    conn.execute(
        f"UPDATE pipeline_events SET consumed = 1 WHERE id IN ({placeholders})",
        tuple(event_ids),
    )
    conn.commit()


# ── agent decisions (audit trail) ────────────────────────────────────

def insert_agent_decision(session_date: str, decision: dict, *,
                          run_id: str | None = None,
                          model_used: str | None = None) -> int:
    """
    Persist one validated agent Decision (dict with asset_ids/action/relation/
    target_asset_id/result/reasoning/prompt_for_gemini). Skip decisions have
    no records row, so this table is their only landing place.
    """
    conn = _get_conn()
    cur = conn.execute(
        """INSERT INTO agent_decisions
           (session_date, run_id, asset_ids, action, relation, target_asset_id,
            group_with, result, reasoning, prompt_for_gemini, model_used)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (session_date, run_id,
         json.dumps(decision["asset_ids"], ensure_ascii=False),
         decision["action"], decision["relation"], decision.get("target_asset_id"),
         decision.get("group_with"),
         json.dumps(decision["result"], ensure_ascii=False),
         decision["reasoning"], decision.get("prompt_for_gemini"), model_used),
    )
    conn.commit()
    return cur.lastrowid


def get_decisions_by_date(date_str: str) -> list[dict]:
    """All agent decisions anchored to a date (HKT), oldest first."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM agent_decisions WHERE session_date = ? ORDER BY id",
        (date_str,),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["asset_ids"] = json.loads(d["asset_ids"])
            d["result"] = json.loads(d["result"])
        except (json.JSONDecodeError, TypeError):
            pass
        out.append(d)
    return out


# ── chat (conversational agent) ──────────────────────────────────────

def create_chat_session(title: str = "") -> int:
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO chat_sessions (title) VALUES (?)", (title,)
    )
    conn.commit()
    return cur.lastrowid


def list_chat_sessions() -> list[dict]:
    """All sessions, newest first, with message count and last activity."""
    conn = _get_conn()
    rows = conn.execute(
        """
        SELECT s.id, s.title, s.created_at,
               COUNT(m.id) AS message_count,
               MAX(m.created_at) AS last_active
        FROM chat_sessions s
        LEFT JOIN chat_messages m ON m.session_id = s.id
        GROUP BY s.id
        ORDER BY s.id DESC
        """
    ).fetchall()
    return [dict(r) for r in rows]


def get_chat_session(session_id: int) -> dict | None:
    conn = _get_conn()
    row = conn.execute("SELECT * FROM chat_sessions WHERE id = ?", (session_id,)).fetchone()
    return dict(row) if row else None


def get_latest_chat_session_id() -> int | None:
    conn = _get_conn()
    # 优先返回有消息记录的最新 session，避免空 session 抢占
    row = conn.execute(
        """SELECT s.id FROM chat_sessions s
           INNER JOIN chat_messages m ON m.session_id = s.id
           ORDER BY s.id DESC LIMIT 1"""
    ).fetchone()
    if row and row["id"] is not None:
        return row["id"]
    row = conn.execute("SELECT MAX(id) AS id FROM chat_sessions").fetchone()
    return row["id"] if row and row["id"] is not None else None


def set_chat_session_title(session_id: int, title: str):
    conn = _get_conn()
    conn.execute("UPDATE chat_sessions SET title = ? WHERE id = ?",
                 (title, session_id))
    conn.commit()


def add_chat_message(session_id: int, role: str, content: str, *,
                     tool_log: list | None = None,
                     response_id: str | None = None) -> int:
    conn = _get_conn()
    cur = conn.execute(
        """INSERT INTO chat_messages (session_id, role, content, tool_log, response_id)
           VALUES (?, ?, ?, ?, ?)""",
        (session_id, role, content,
         json.dumps(tool_log, ensure_ascii=False) if tool_log else None,
         response_id),
    )
    conn.commit()
    return cur.lastrowid


def get_chat_messages(session_id: int, limit: int | None = None) -> list[dict]:
    """Messages of a session, oldest first. limit returns the most recent N."""
    conn = _get_conn()
    if limit:
        rows = conn.execute(
            """SELECT * FROM (SELECT * FROM chat_messages
               WHERE session_id = ? ORDER BY id DESC LIMIT ?)
               ORDER BY id""",
            (session_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM chat_messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["tool_log"] = json.loads(d["tool_log"]) if d["tool_log"] else []
        except json.JSONDecodeError:
            d["tool_log"] = []
        out.append(d)
    return out


def get_last_response_id(session_id: int) -> str | None:
    """End-of-chain Responses id for continuing via previous_response_id."""
    conn = _get_conn()
    row = conn.execute(
        """SELECT response_id FROM chat_messages
           WHERE session_id = ? AND response_id IS NOT NULL
           ORDER BY id DESC LIMIT 1""",
        (session_id,),
    ).fetchone()
    return row["response_id"] if row else None


def get_setting(key: str, default: str = "") -> str:
    conn = _get_conn()
    row = conn.execute("SELECT value FROM app_settings WHERE key = ?",
                       (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str):
    conn = _get_conn()
    conn.execute(
        "INSERT INTO app_settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()


def compute_bmr(height: float, weight: float, birthdate: str,
                gender: str = "male") -> float | None:
    """Compute Basal Metabolic Rate (BMR) using Mifflin-St Jeor equation."""
    if not (height > 0 and weight > 0 and birthdate):
        return None
    try:
        birth = datetime.strptime(birthdate[:10], "%Y-%m-%d").date()
        today = datetime.now(HKT).date()
        age = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
        if age < 0 or age > 120:
            return None
        if str(gender).lower() == "female":
            bmr = 10.0 * weight + 6.25 * height - 5.0 * age - 161.0
        else:
            bmr = 10.0 * weight + 6.25 * height - 5.0 * age + 5.0
        return round(bmr, 1)
    except Exception:
        return None


def get_user_bmr() -> float | None:
    """Get calculated BMR based on user profile stored in app_settings."""
    try:
        h_str = get_setting("user_height", "")
        w_str = get_setting("user_weight", "")
        b_str = get_setting("user_birthdate", "")
        g_str = get_setting("user_gender", "male")
        if not (h_str and w_str and b_str):
            return None
        return compute_bmr(float(h_str), float(w_str), b_str, g_str)
    except (ValueError, TypeError):
        return None


# ── daily burn ───────────────────────────────────────────────────────

def upsert_daily_burn(date_str: str, active_kcal: float, steps: int = 0,
                      source: str = "heytap-ui") -> dict:
    conn = _get_conn()
    cur = conn.execute(
        """
        INSERT INTO daily_burn (date, active_kcal, steps, source, created_at, updated_at)
        VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))
        ON CONFLICT(date) DO UPDATE SET
            active_kcal = excluded.active_kcal,
            steps = excluded.steps,
            source = excluded.source,
            updated_at = datetime('now')
        RETURNING *;
        """,
        (date_str, round(float(active_kcal), 1), int(steps), source),
    )
    row = cur.fetchone()
    conn.commit()
    return _row_to_dict(row)


def get_daily_burn(date_str: str) -> dict | None:
    conn = _get_conn()
    cur = conn.execute("SELECT * FROM daily_burn WHERE date = ?", (date_str,))
    row = cur.fetchone()
    return _row_to_dict(row) if row else None


def get_daily_burn_range(start_date: str, end_date: str) -> dict[str, dict]:
    conn = _get_conn()
    cur = conn.execute(
        "SELECT * FROM daily_burn WHERE date >= ? AND date <= ? ORDER BY date ASC",
        (start_date, end_date),
    )
    return {row["date"]: _row_to_dict(row) for row in cur.fetchall()}


def get_data_version() -> str:
    """
    Cheap fingerprint of all meal-data writes (insert / update / delete /
    relabel / reanalyze / burn). The web frontend polls this to detect background
    writes from cron runs (agent or legacy path) and refresh stale views.
    COUNT covers deletes; timestamps cover in-place updates.
    """
    conn = _get_conn()
    row = conn.execute(
        """
        SELECT
          (SELECT COUNT(*) FROM records)                        AS n,
          (SELECT MAX(created_at) FROM records)                 AS c,
          (SELECT MAX(updated_at) FROM records)                 AS u,
          (SELECT MAX(reanalyzed_at) FROM reanalysis_history)   AS r,
          (SELECT COUNT(*) FROM daily_burn)                     AS bn,
          (SELECT TOTAL(active_kcal) FROM daily_burn)           AS bk,
          (SELECT MAX(updated_at) FROM daily_burn)              AS b
        """
    ).fetchone()
    return f"{row['n']}:{row['c']}:{row['u']}:{row['r']}:{row['bn']}:{row['bk']}:{row['b']}"


def get_run_summary(run_id: str) -> dict:
    """Aggregate stats for a single run from its events."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT event_type, COUNT(*) as cnt FROM pipeline_events "
        "WHERE run_id = ? GROUP BY event_type",
        (run_id,),
    ).fetchall()
    return {r["event_type"]: r["cnt"] for r in rows}
