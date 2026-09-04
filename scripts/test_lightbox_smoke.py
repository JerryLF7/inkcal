#!/usr/bin/env python3
"""Smoke test: photos[] macro fields + DELETE /api/record promoted response.

Runs against an isolated temp DB (production data untouched).
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("INKCAL_SKIP_AGENT", "1")
# .env 会被 server.py 的 load_dotenv 读入；预置空串使 load_dotenv 不覆盖
# （默认 override=False），从而走无认证测试路径
os.environ["INKCAL_USER"] = ""
os.environ["INKCAL_PASS"] = ""

from src import db  # noqa: E402


def insert(aid, photo_time, meal, kcal, p=0, c=0, f=0, merged_into=None):
    db.insert_record({
        "asset_id": aid, "source_type": "immich", "source_id": aid,
        "photo_time": photo_time, "thumbnail_url": f"https://x/{aid}",
        "meal": meal, "calories": kcal, "protein_g": p, "carbs_g": c,
        "fat_g": f, "confidence": "medium",
        "analyzed_at": photo_time, "merged_into": merged_into,
    })


def main():
    tmp = Path(tempfile.mkdtemp()) / "smoke.db"
    db.init_db(tmp)
    conn = db._get_conn()
    conn.execute("INSERT INTO users (username, password_hash) VALUES ('t', 'x')") if False else None
    conn.commit()

    # ── fixture: 形态 A 组（主行 845，从行 0）+ 形态 B 组（主 720，从行带自己数值）──
    insert("a-primary", "2026-08-29T12:20:00+08:00", "红烧肉套餐", 845, 32, 90, 28)
    insert("a-follow",  "2026-08-29T12:35:00+08:00", "红烧肉套餐", 0, 0, 0, 0,
           merged_into="a-primary")
    insert("b-primary", "2026-08-29T18:00:00+08:00", "轻食三明治", 720, 28, 74, 22)
    insert("b-beer",    "2026-08-29T18:10:00+08:00", "青岛啤酒", 125, 1, 9, 0,
           merged_into="b-primary")
    insert("b-fruit",   "2026-08-29T18:20:00+08:00", "苹果", 80, 0, 20, 0,
           merged_into="b-primary")

    from web.server import app
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as s:
        s["_fresh"] = True

    ok = 0
    def check(name, cond):
        nonlocal ok
        print(("  ok  " if cond else "  FAIL  ") + name)
        assert cond, name
        ok += 1

    # ── 1. /api/records photos 带 P/C/F ──
    d = client.get("/api/records?date=2026-08-29").get_json()
    groups = {g["asset_id"]: g for g in d["records"]}
    pa = groups["a-primary"]["photos"]
    check("A 组 photos 数量", len(pa) == 2)
    check("A 主行 photos 宏营养素", pa[0]["protein_g"] == 32 and pa[0]["carbs_g"] == 90)
    check("A 从行 photos 零值", pa[1]["calories"] == 0 and pa[1]["protein_g"] == 0)
    pb = groups["b-primary"]["photos"]
    pb = groups["b-primary"]["photos"]
    check("B 组 3 张", len(pb) == 3)
    check("B 从行 photos 自带数值", pb[1]["calories"] == 125 and pb[1]["fat_g"] == 0)
    check("photos 无 confidence 字段（按设计省略）", "confidence" not in pa[0])

    # ── 2. 删从行 → promoted null，原地刷新锚点不变 ──
    r = client.delete("/api/record", json={"asset_id": "b-beer", "mode": "photo"})
    j = r.get_json()
    check("删从行 ok", j["ok"] and j["promoted"] is None)
    d = client.get("/api/records?date=2026-08-29").get_json()
    groups = {g["asset_id"]: g for g in d["records"]}
    check("B 组剩 2 张", len(groups["b-primary"]["photos"]) == 2)
    check("B 组合计仍 720", groups["b-primary"]["calories"] == 720)

    # ── 3. 删形态 B 主行 → 最早从行晋升，merged_into 重挂 ──
    r = client.delete("/api/record", json={"asset_id": "b-primary", "mode": "photo"})
    j = r.get_json()
    check("删主行 promoted=b-fruit", j["promoted"] == "b-fruit")
    d = client.get("/api/records?date=2026-08-29").get_json()
    groups = {g["asset_id"]: g for g in d["records"]}
    check("b-fruit 成为主记录", "b-fruit" in groups)
    check("b-fruit 数值保留", groups["b-fruit"]["calories"] == 80)

    # ── 4. 删形态 A 主行 → 从行晋升为 0 值（前端应提示重估）──
    r = client.delete("/api/record", json={"asset_id": "a-primary", "mode": "photo"})
    j = r.get_json()
    check("A 删主行 promoted=a-follow", j["promoted"] == "a-follow")
    d = client.get("/api/records?date=2026-08-29").get_json()
    groups = {g["asset_id"]: g for g in d["records"]}
    check("A 晋升行 0 值", groups["a-follow"]["calories"] == 0)
    check("A 晋升行 merged_into 为空", not groups["a-follow"].get("merged_into"))

    # ── 5. 整餐删除 → promoted null，ignored_assets 写入 ──
    r = client.delete("/api/record", json={"asset_id": "a-follow", "mode": "meal"})
    j = r.get_json()
    check("整餐删除 ok promoted=null", j["ok"] and j["promoted"] is None)
    check("ignored_assets 记录", "a-follow" in db.get_ignored_assets())
    d = client.get("/api/records?date=2026-08-29").get_json()
    ids = {g["asset_id"] for g in d["records"]}
    check("A 组已清空（b-fruit 是第 3 步晋升的主记录，应留存）",
          "a-follow" not in ids and "a-primary" not in ids and "b-fruit" in ids)

    # ── 6. 404 ──
    check("404 record not found",
          client.delete("/api/record", json={"asset_id": "nope", "mode": "photo"}).status_code == 404)

    print(f"\nall passed ({ok} checks)")


if __name__ == "__main__":
    main()
