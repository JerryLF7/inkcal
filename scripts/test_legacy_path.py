"""Regression for main._legacy_analyze_single after routing it via pipeline_ops.analyze_asset.

Isolated DB + fake analyzer (no network). Covers: normal record, non-food skip,
unknown skip, duplicate skip, and that a shared analyzer is NOT closed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import db
import main

passed = 0


def ok(cond, label):
    global passed
    assert cond, label
    passed += 1
    print(f"  ok  {label}")


class FakeAnalyzer:
    def __init__(self, result):
        self.result, self.closed = result, False

    def analyze(self, _img):
        return self.result

    def close(self):
        self.closed = True


def item(aid):
    return {"aid": aid, "source": "immich", "photo_time": "2026-09-30T12:00:00+08:00",
            "thumbnail_url": "http://t/" + aid, "original": b"x"}


def events():
    return [r[0] for r in db._get_conn().execute("SELECT event_type FROM pipeline_events")]


test_db = Path("/tmp/test_legacy_path.db")
for p in [test_db, Path(str(test_db) + "-wal"), Path(str(test_db) + "-shm")]:
    p.unlink(missing_ok=True)
db.close_db()
db.init_db(test_db)

a = FakeAnalyzer({"meal": "Rice", "calories": 500, "confidence": "low"})
main._legacy_analyze_single(item("a1"), a, run_id="r")
rec = db.get_record_by_asset_id("a1")
ok(rec and rec["calories"] == 500 and rec["thumbnail_url"] == "http://t/a1", "record saved with given thumbnail")
ok("meal_recorded" in events() and "low_confidence" in events(), "events emitted (incl. low_confidence)")
ok(a.closed is False, "shared analyzer not closed")

main._legacy_analyze_single(item("a1"), a, run_id="r")
ok(len(db.get_records_by_date("2026-09-30")) == 1, "duplicate asset skipped, no second row")

for meal in ("not real food", "unknown"):
    aid = "n-" + meal[:3]
    main._legacy_analyze_single(item(aid), FakeAnalyzer({"meal": meal}), run_id="r")
    ok(db.get_record_by_asset_id(aid) is None, f"'{meal}' creates no record")
ok("gemini_rejected" in events(), "gemini_rejected event emitted")
print(f"{passed} checks passed")
