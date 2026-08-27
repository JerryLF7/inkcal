"""One-off: measure prompt-cache hit rate on the Luna Responses channel.

Simulates a chat-shaped workload: same instructions + tool schemas every
turn, conversation continued via previous_response_id chaining. Prints
per-call usage so we can see how much of the prefix is served from cache.

Run: venv/bin/python scripts/test_luna_cache.py
"""

import os
import sys

# Load .env the same way the app does (no secrets printed).
for line in open(".env"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

from openai import OpenAI  # noqa: E402

from src.agent_contract import SYSTEM_PROMPT, TOOL_SCHEMAS  # noqa: E402
from src.agent_harness import _to_responses_tools  # noqa: E402

client = OpenAI(
    api_key=os.environ["LUNA_API_KEY"],
    base_url=os.environ.get("LUNA_BASE_URL") or None,
    max_retries=0,
)
MODEL = os.environ.get("LUNA_MODEL", "gpt-5.6-luna")
TOOLS = _to_responses_tools(TOOL_SCHEMAS)

# Rough size of the stable prefix (instructions + tool schemas).
prefix_chars = len(SYSTEM_PROMPT) + sum(len(str(t)) for t in TOOLS)
print(f"prefix size: ~{prefix_chars} chars (instructions + {len(TOOLS)} tools)")

TURNS = [
    "测试连通性。请只回复：收到。",
    "再问一次：请只回复：收到。",
    "最后一次：请只回复：收到。",
]

prev_id = None
for i, text in enumerate(TURNS, 1):
    kwargs = {
        "model": MODEL,
        "instructions": SYSTEM_PROMPT,
        "input": [{"role": "user", "content": text}],
        "tools": TOOLS,
        "tool_choice": "auto",
        "max_output_tokens": 8192,
        "timeout": 120,
    }
    if prev_id:
        kwargs["previous_response_id"] = prev_id
    resp = client.responses.create(**kwargs)
    prev_id = resp.id

    u = resp.usage
    cached = None
    details = getattr(u, "input_tokens_details", None)
    if details is not None:
        cached = getattr(details, "cached_tokens", None)
    print(
        f"turn {i}: input={u.input_tokens} cached={cached} "
        f"output={u.output_tokens} status={resp.status}"
    )

print("done")
