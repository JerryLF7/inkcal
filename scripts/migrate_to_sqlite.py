#!/usr/bin/env python3
"""Migrate JSON backup to SQLite."""

import json
import sqlite3
from pathlib import Path

BACKUP_DIR = Path("/home/jerry/Coding/inkcal/data-backup-20260511-223659")
DB_PATH = Path("/home/jerry/Coding/inkcal/inkcal.db")


def init_schema(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_id TEXT NOT NULL,
            source_type TEXT NOT NULL DEFAULT 'immich',
            source_id TEXT,
            photo_time DATETIME NOT NULL,
            thumbnail_url TEXT,
            original_url TEXT,
            meal TEXT,
            calories REAL,
            protein_g REAL,
            carbs_g REAL,
            fat_g REAL,
            confidence TEXT,
            analyzed_at DATETIME,
            model_used TEXT,
            user_label TEXT,
            replacement_image TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(asset_id)
        );
        CREATE INDEX IF NOT EXISTS idx_records_date ON records(date(photo_time));
        CREATE INDEX IF NOT EXISTS idx_records_source ON records(source_type, source_id);
    """)


def migrate():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    init_schema(conn)

    files = sorted(BACKUP_DIR.glob("*.json"))
    total = skipped = inserted = 0

    for f in files:
        records = json.loads(f.read_text())
        for r in records:
            if not isinstance(r, dict):
                skipped += 1
                continue
            total += 1
            try:
                conn.execute("""
                    INSERT INTO records (
                        asset_id, source_type, source_id, photo_time,
                        thumbnail_url, meal, calories, protein_g, carbs_g,
                        fat_g, confidence, analyzed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    r["asset_id"],
                    "immich",
                    r["asset_id"],
                    r.get("photo_time"),
                    r.get("thumbnail_url"),
                    r.get("meal"),
                    r.get("calories"),
                    r.get("protein_g"),
                    r.get("carbs_g"),
                    r.get("fat_g"),
                    r.get("confidence"),
                    r.get("analyzed_at"),
                ))
                inserted += 1
            except sqlite3.IntegrityError:
                skipped += 1

    conn.commit()
    print(f"Total: {total}, Inserted: {inserted}, Skipped: {skipped}")
    conn.close()


if __name__ == "__main__":
    migrate()
