"""Apply-logic tests for same-meal grouping (merged_into / group_with).

No network: AgentHarness is stubbed to return synthetic Decisions, so only
the DB landing logic in main._run_agent_batch is exercised. Uses a fresh
throwaway DB per run.

Run: PYTHONPATH=. venv/bin/python scripts/test_merge_groups.py
"""

import os
import sys
import tempfile

sys.path.insert(0, ".")

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["INKCAL_DB"] = _tmp.name

import src.db as db  # noqa: E402
import src.agent_harness as ah  # noqa: E402
from src.agent_contract import Decision  # noqa: E402

db.init_db()

failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok  {name}")
    else:
        failures.append(name)
        print(f" FAIL {name}: {detail}")


def make_dec(asset_ids, action="add", relation="new_meal", target=None,
             group_with=None, meal="测试餐", cal=500):
    return Decision(
        asset_ids=asset_ids, action=action, target_asset_id=target,
        relation=relation, group_with=group_with,
        result={"meal": meal, "calories": cal, "protein_g": 20,
                "carbs_g": 50, "fat_g": 10, "confidence": "high"},
        reasoning="synthetic test", prompt_for_gemini=None,
    )


class StubHarness:
    """Drop-in for AgentHarness: returns canned decisions."""
    decisions: list = []

    def __init__(self, **kw): pass

    def run(self, assets, image_getter): return StubHarness.decisions

    def close(self): pass


ah.AgentHarness = StubHarness  # main._run_agent_batch does a local import

import main  # noqa: E402  (after stub so the local import picks it up)


class FakeAnalyzer:
    model = "fake-gemini"


def run_batch(batch, decisions):
    StubHarness.decisions = decisions
    main._run_agent_batch("2026-09-03", batch, FakeAnalyzer(), run_id="test")


def item(aid, pt):
    return {"aid": aid, "source": "immich", "photo_time": pt,
            "thumbnail_url": "", "original": b""}


# ── 形态 A：一条 add 覆盖两张照片（状态延续）────────────────────────
batch = [item("a1", "2026-09-03T11:48:00+08:00"),
         item("a2", "2026-09-03T11:35:00+08:00")]  # 注意顺序：a2 更早
run_batch(batch, [make_dec(["a1", "a2"], cal=820)])

prim = db.get_record_by_asset_id("a2")   # 最早拍摄 → 主记录
sec = db.get_record_by_asset_id("a1")
check("A: 主记录是最早拍摄的照片", prim and prim["calories"] == 820)
check("A: 从行 0 值且指向主记录",
      sec and sec["calories"] == 0 and sec.get("merged_into") == "a2")

meals = db.group_meals(db.get_records_by_date("2026-09-03"))
check("A: group_meals 只出一张卡", len(meals) == 1)
check("A: 卡片带两张照片", len(meals[0]["photos"]) == 2)
s = db.summarize_records(db.get_records_by_date("2026-09-03"))
check("A: 汇总 1 餐 820kcal", s["meals"] == 1 and s["calories"] == 820, s)

# ── 形态 B：两个 add，第二个 group_with 第一个（同餐独立条目）────────
batch = [item("b1", "2026-09-03T12:30:00+08:00"),
         item("b2", "2026-09-03T12:31:00+08:00")]
# 故意把 group_with 决策放前面——验证两遍处理的顺序无关性
run_batch(batch, [
    make_dec(["b2"], group_with="b1", meal="奶茶", cal=300),
    make_dec(["b1"], meal="面", cal=500),
])

b1, b2 = db.get_record_by_asset_id("b1"), db.get_record_by_asset_id("b2")
check("B: b1 主记录带自己的数值", b1 and not b1.get("merged_into")
      and b1["calories"] == 500)
check("B: b2 从行携带自己的数值", b2 and b2.get("merged_into") == "b1"
      and b2["calories"] == 300)
s = db.summarize_records(db.get_records_by_date("2026-09-03"))
check("B: 汇总 2 餐(a组+b组) 1620kcal",
      s["meals"] == 2 and s["calories"] == 1620, s)

# ── update：目标存在 → 更新 + 新照片落 0 值从行（幂等修复）──────────
batch = [item("c1", "2026-09-03T13:00:00+08:00")]
run_batch(batch, [make_dec(["c1"], action="update", relation="same_meal",
                           target="a2", cal=900)])

a2 = db.get_record_by_asset_id("a2")
c1 = db.get_record_by_asset_id("c1")
check("U: 目标记录数值被更新", a2["calories"] == 900, a2["calories"])
check("U: 新照片落 0 值从行指向目标",
      c1 and c1["calories"] == 0 and c1.get("merged_into") == "a2")
processed = db.get_processed_asset_ids("2026-09-03")
check("U: 新照片已被标记已处理（下轮 cron 不再重跑）", "c1" in processed)

# ── group_with 指向从行 → 解析到组根 ────────────────────────────────
batch = [item("d1", "2026-09-03T14:00:00+08:00")]
run_batch(batch, [make_dec(["d1"], group_with="c1", meal="甜点", cal=200)])
d1 = db.get_record_by_asset_id("d1")
check("G: group_with 指向从行时挂到组根 a2",
      d1 and d1.get("merged_into") == "a2", d1 and d1.get("merged_into"))

# ── group_with 目标不存在 → 降级为独立记录 ──────────────────────────
batch = [item("e1", "2026-09-03T15:00:00+08:00")]
run_batch(batch, [make_dec(["e1"], group_with="ghost", meal="孤儿", cal=100)])
e1 = db.get_record_by_asset_id("e1")
check("G: 孤儿 group_with 降级为独立记录", e1 and not e1.get("merged_into"))

# ── 跨零点组：从行在次日，group_meals 仍能挂上 ──────────────────────
batch = [item("f1", "2026-09-03T23:55:00+08:00"),
         item("f2", "2026-09-04T00:05:00+08:00")]
run_batch(batch, [make_dec(["f1", "f2"], cal=600)])
day1 = db.group_meals(db.get_records_by_date("2026-09-03"))
f1card = next((m for m in day1 if m["asset_id"] == "f1"), None)
check("X: 跨零点从行挂上前一天的卡片",
      f1card and len(f1card["photos"]) == 2)
day2 = db.group_meals(db.get_records_by_date("2026-09-04"))
check("X: 次日不产生孤儿卡",
      all(not m["asset_id"] == "f2" for m in day2))

os.unlink(_tmp.name)
if failures:
    print(f"\n{len(failures)} FAILED")
    sys.exit(1)
print("\nall passed")
