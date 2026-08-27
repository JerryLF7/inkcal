"""One-off: re-run the Luna agent harness on the two lunch photos from
2026-08-26 (records 179/180, which went through the legacy path and got
recorded as two separate meals). Prints decisions WITHOUT applying them.

Run: venv/bin/python scripts/test_luna_lunch.py
"""

import json
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

sys.path.insert(0, ".")
from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from main import load_config  # noqa: E402
from src.agent_harness import AgentHarness  # noqa: E402
from src.calorie_analyzer import CalorieAnalyzer  # noqa: E402
from src.immich_client import ImmichClient, format_photo_time  # noqa: E402

import os  # noqa: E402

import src.db as db  # noqa: E402
import src.agent_harness as ah  # noqa: E402

db.init_db()

# Debug hooks: capture raw Luna output, response status and token usage.
_orig_call = ah.AgentHarness._call_luna

def _spy_call(self, input_items, *, previous_response_id=None):
    resp = _orig_call(self, input_items, previous_response_id=previous_response_id)
    u = getattr(resp, "usage", None)
    cached = getattr(getattr(u, "input_tokens_details", None), "cached_tokens", None)
    print(f"  [resp] status={resp.status} incomplete={getattr(resp, 'incomplete_details', None)} "
          f"in={getattr(u, 'input_tokens', '?')}(cached={cached}) out={getattr(u, 'output_tokens', '?')}")
    return resp

ah.AgentHarness._call_luna = _spy_call

_orig_parse = ah.parse_decisions_json

def _spy_parse(text):
    try:
        return _orig_parse(text)
    except ValueError:
        print(f"  [raw output, {len(text)} chars] >>>{text}<<<")
        raise

ah.parse_decisions_json = _spy_parse

ASSET_IDS = [
    "41ca6def-83eb-4c91-8853-612ad6d9bd25",  # 11:48 外卖便当
    "1a51d328-5cd7-4c4d-98d5-1eb6943e4a8d",  # 11:35 外卖盒饭
]

config = load_config()
client = ImmichClient(config["immich_url"], config["immich_key"])

# Fetch metadata + originals via the client's httpx session.
assets = []
for aid in ASSET_IDS:
    r = client._client.get(f"/api/assets/{aid}")
    r.raise_for_status()
    meta = r.json()
    exif = meta.get("exifInfo", {})
    photo_time = format_photo_time(exif.get("dateTimeOriginal", ""), exif.get("timeZone"))
    original = client.download_original(aid)
    print(f"{aid[:8]}: {photo_time}, {len(original)/1024:.0f} KB")
    assets.append({
        "asset_id": aid,
        "photo_time": photo_time,
        "source": "immich",
        "image_bytes": original,
    })

analyzer = CalorieAnalyzer(
    config["gemini_key"],
    base_url=config["gemini_base_url"],
    model=config["gemini_model"],
)

harness = AgentHarness(
    luna_api_key=os.getenv("LUNA_API_KEY", ""),
    luna_base_url=os.getenv("LUNA_BASE_URL") or None,
    luna_model=os.getenv("LUNA_MODEL", "gpt-5.6-luna"),
    deps={"gemini_analyzer": analyzer},
)

originals = {a["asset_id"]: a["image_bytes"] for a in assets}
decisions = harness.run(assets, lambda aid: originals[aid])

print("\n===== decisions (NOT applied) =====")
if decisions is None:
    print("harness returned None (would fall back to legacy path)")
else:
    for d in decisions:
        print(json.dumps({
            "asset_ids": [a[:8] for a in d.asset_ids],
            "action": d.action,
            "relation": d.relation,
            "target_asset_id": (d.target_asset_id or "")[:8] or None,
            "result": d.result,
            "reasoning": d.reasoning,
            "prompt_for_gemini": d.prompt_for_gemini,
        }, ensure_ascii=False, indent=2))
