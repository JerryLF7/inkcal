"""Group-aware reanalyze regression (2026-09-21 pasta double-count fix).

Verifies reanalyze_record():
  1. resolves the group root and jointly re-analyzes ALL group photos
  2. writes the joint result to the primary row
  3. zeroes stale 形态 B merged-row values so the group sum can't double count

Isolated DB + monkeypatched Gemini + monkeypatched image fetch (no network).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import db
from src import pipeline_ops

passed = 0


def ok(cond, label):
    global passed
    assert cond, label
    passed += 1
    print(f"  ok  {label}")


def main():
    test_db = Path("/tmp/test_group_reanalyze.db")
    for p in [test_db, Path(str(test_db) + "-wal"), Path(str(test_db) + "-shm")]:
        if p.exists():
            p.unlink()
    db.close_db()
    db.init_db(test_db)

    # 形态 B group: primary pasta 580 + merged chicken combo 1050 (the
    # exact 2026-09-21 shape that double counted to 2020).
    db.insert_record({
        "asset_id": "root-pasta", "source_type": "manual", "source_id": "root-pasta",
        "photo_time": "2026-09-21T11:44:58+08:00", "thumbnail_url": "",
        "meal": "意面配饮料", "meal_detail": "青酱意面+可乐",
        "calories": 580, "protein_g": 22, "carbs_g": 85, "fat_g": 16,
        "confidence": "high",
    })
    db.insert_record({
        "asset_id": "merge-combo", "source_type": "manual", "source_id": "merge-combo",
        "photo_time": "2026-09-21T11:47:31+08:00", "thumbnail_url": "",
        "meal": "西式意面套餐", "meal_detail": "意面+鸡排+可乐",
        "calories": 1050, "protein_g": 50, "carbs_g": 100, "fat_g": 50,
        "confidence": "high", "merged_into": "root-pasta",
    })

    # Monkeypatch: no network — fake image bytes + fake joint Gemini result.
    seen = {}

    def fake_get_image_bytes(record, config):
        seen.setdefault("fetched", []).append(record["asset_id"])
        import io as _io
        from PIL import Image as _Image
        buf = _io.BytesIO()
        _Image.new("RGB", (8, 8), (120, 90, 60)).save(buf, format="JPEG")
        return buf.getvalue()

    class FakeAnalyzer:
        def __init__(self, *a, **k):
            pass

        def reanalyze(self, image_bytes, current_result, notes):
            seen["image_count"] = len(image_bytes)
            seen["notes"] = notes
            return {"meal": "意面鸡排套餐", "meal_detail": "青酱意面、鸡排、可乐（整餐仅计一次）",
                    "calories": 1400, "protein_g": 58, "carbs_g": 105,
                    "fat_g": 80, "confidence": "high"}

        def close(self):
            pass

    orig_gib = pipeline_ops._get_image_bytes
    import src.calorie_analyzer as ca
    orig_analyzer = ca.CalorieAnalyzer
    pipeline_ops._get_image_bytes = fake_get_image_bytes
    ca.CalorieAnalyzer = FakeAnalyzer
    try:
        # Call with the MERGED row id — must resolve up to the root.
        updated = pipeline_ops.reanalyze_record(
            "merge-combo", "两张照片是同一份意面，只计算一次",
            {"gemini_key": "x"},
        )
    finally:
        pipeline_ops._get_image_bytes = orig_gib
        ca.CalorieAnalyzer = orig_analyzer

    ok(updated is not None, "reanalyze returns the primary record")
    ok(updated["asset_id"] == "root-pasta", "merged-row call resolves to group root")
    ok(seen["image_count"] == 2, "joint reanalyze received ALL group photos (2)")
    ok(updated["calories"] == 1400, "primary updated with joint result (1400)")

    rows = db.get_group_rows("root-pasta")
    merged = next(r for r in rows if r["asset_id"] == "merge-combo")
    ok(merged["calories"] == 0, "stale 形态 B merged value zeroed (1050 -> 0)")
    ok(merged["merged_into"] == "root-pasta", "merged row still attached to group")

    total = sum(r["calories"] for r in rows)
    ok(total == 1400, f"group sum == joint result only, no double count ({total})")

    hist_rec = db.get_record_by_asset_id("root-pasta")
    hist = hist_rec.get("reanalysis_history") or []
    ok(len(hist) == 1 and "只计算一次" in hist[0]["notes"], "history appended on primary")

    print(f"\nall passed ({passed} checks)")


if __name__ == "__main__":
    main()
