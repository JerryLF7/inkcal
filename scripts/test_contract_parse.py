"""Regression tests for agent_contract.parse_decisions_json.

Covers the 2026-08-27 production finding: Luna reliably appends extra
closing brackets ("...}]}]}") on longer decisions — valid envelope followed
by stray closers. parse must tolerate that while still rejecting genuine
garbage.

Run: PYTHONPATH=. venv/bin/python scripts/test_contract_parse.py
"""

import sys

sys.path.insert(0, ".")

from src.agent_contract import parse_decisions_json  # noqa: E402

# Real Luna output captured 2026-08-27 (2-photo lunch batch), note the
# trailing extra "]}" after the complete envelope.
REAL_EXTRA_CLOSERS = (
    '{"decisions":[{"asset_ids":["1a51d328-5cd7-4c4d-98d5-1eb6943e4a8d",'
    '"41ca6def-83eb-4c91-8853-612ad6d9bd25"],"action":"skip","relation":"rejected",'
    '"result":{"meal":"unknown","calories":0,"protein_g":0,"carbs_g":0,"fat_g":0,'
    '"confidence":"low"},"reasoning":"两张照片是同一顿午餐的连续状态，内容为外卖盒饭'
    '及食用后的剩余部分。但 Gemini 返回 unknown 且热量和宏量营养均为 0，无法形成'
    '可靠的餐食记录，因此跳过。","prompt_for_gemini":"请识别这两张同一顿午餐的照片，'
    '并结合前后状态估算实际食用量。"}]}]}'
)

VALID = (
    '{"decisions":[{"asset_ids":["a1"],"action":"add","relation":"new_meal",'
    '"result":{"meal":"饺子","calories":720,"protein_g":25,"carbs_g":80,'
    '"fat_g":30,"confidence":"high"},"reasoning":"r","prompt_for_gemini":"p"}]}'
)

failures = []


def check(name, fn):
    try:
        fn()
        print(f"  ok  {name}")
    except AssertionError as e:
        failures.append(name)
        print(f" FAIL {name}: {e}")


def test_valid():
    ds = parse_decisions_json(VALID)
    assert len(ds) == 1 and ds[0].action == "add" and ds[0].result["calories"] == 720


def test_extra_closers_real_capture():
    ds = parse_decisions_json(REAL_EXTRA_CLOSERS)
    assert len(ds) == 1
    assert ds[0].action == "skip" and ds[0].relation == "rejected"
    assert len(ds[0].asset_ids) == 2


def test_markdown_fence():
    ds = parse_decisions_json("```json\n" + VALID + "\n```")
    assert ds[0].action == "add"


def test_truncated_missing_closer():
    # Existing tolerance: missing final "}" gets one appended.
    ds = parse_decisions_json(VALID[:-1])
    assert ds[0].action == "add"


def test_trailing_garbage_rejected():
    try:
        parse_decisions_json(VALID + " DROP TABLE records;")
    except ValueError:
        return
    raise AssertionError("trailing SQL junk was not rejected")


def test_nonsense_rejected():
    for bad in ("", "not json at all", '{"decisions": []}', '{"foo": 1}]'):
        try:
            parse_decisions_json(bad)
        except ValueError:
            continue
        raise AssertionError(f"accepted bad input: {bad!r}")


print("parse_decisions_json regression tests")
for t in (test_valid, test_extra_closers_real_capture, test_markdown_fence,
          test_truncated_missing_closer, test_trailing_garbage_rejected,
          test_nonsense_rejected):
    check(t.__name__, t)

if failures:
    print(f"\n{len(failures)} FAILED")
    sys.exit(1)
print("\nall passed")
