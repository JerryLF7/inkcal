"""
Agent harness — thin Luna agent loop (OpenAI Responses API).

This is the ONLY layer that would be replaced if we later swap to fx.
It orchestrates: build prompt -> Luna -> tool_call -> execute -> feed back
-> ... until Luna emits a final decision (or we hit a limit).

Transport notes (opencode go upstream, reached via forwarding VPS):
- Uses client.responses.create(), NOT chat.completions: the upstream's
  chat-completions adapter silently drops image content (hollow 400),
  while /responses passes images through natively.
- Conversation history is resent in full on every round (accumulated
  input_items). The current endpoint SILENTLY IGNORES previous_response_id
  (returns 200, no context carried), so chaining is unsafe here. Prefix
  caching still covers the stable leading bytes, images included: measured
  3725/3728 cached on a repeated long-text+image prefix.
- Tool round-trips must replay the function_call item itself before its
  function_call_output; output-only is rejected upstream with 400
  ("No tool call found for function call output with call_id ...").
- The upstream rejects legacy max_tokens/max_completion_tokens params;
  Responses' max_output_tokens is accepted.

Design constraints:
- Loop is thin: no business logic here, only orchestration.
- Tools are pure (agent_tools.py); contract validation is separate
  (agent_contract.py). This keeps the swap surface minimal.
- TOOL_SCHEMAS stay in chat format in the contract layer (MCP-ready);
  converting them to Responses' flat shape happens here.
- Luna decides "same meal vs new meal" purely from image content; time is
  only for ordering, not grouping.
- On any Luna-layer failure (timeout, invalid output, loop exhaustion),
  the caller falls back to the legacy single-photo Gemini path.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from typing import Any

from openai import OpenAI

from src.agent_contract import (
    SYSTEM_PROMPT,
    TOOL_SCHEMAS,
    build_user_prompt,
    enforce_zero_skip,
    parse_decisions_json,
    Decision,
)
from src.agent_tools import call_tool, detect_image_mime

logger = logging.getLogger("inkcal.agent_harness")

MAX_STEPS = 12          # hard cap on model/tool rounds
MAX_TOKENS_PER_CALL = 8192  # reasoning tokens share this budget upstream
LUNA_TIMEOUT_S = 120    # per-call timeout


def _to_responses_tools(chat_schemas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Convert contract-layer tool schemas (chat.completions nesting) to the
    flat shape the Responses API expects. Keeps agent_contract.py unchanged.
    """
    out = []
    for s in chat_schemas:
        f = s.get("function") or {}
        out.append({
            "type": "function",
            "name": f.get("name"),
            "description": f.get("description"),
            "parameters": f.get("parameters") or {"type": "object", "properties": {}},
        })
    return out


def _bounded_result(result, max_bytes=6000):
    """
    Keep a tool result small enough to feed back into context, WITHOUT
    producing invalid JSON. Strategy: shrink list fields first, then as a
    last resort return an explicit error marker (never a corrupted dict).
    """
    s = json.dumps(result, ensure_ascii=False)
    if len(s) <= max_bytes:
        return result

    # Strategy 1: trim list fields in place to at most 3 items
    trimmed = dict(result)
    for k, v in list(trimmed.items()):
        if isinstance(v, list) and len(v) > 3:
            trimmed[k] = v[:3]
            trimmed[k + "_truncated"] = True
    s2 = json.dumps(trimmed, ensure_ascii=False)
    if len(s2) <= max_bytes:
        return trimmed

    # Strategy 2: fall back to an explicit error marker (valid JSON)
    return {"ok": False, "error": "tool result too large", "bytes": len(s)}


class AgentHarness:
    """
    Thin orchestration loop around Luna (cheap vision model) that:
      1. Presents a batch of new food photos (with metadata) to Luna.
      2. Lets Luna call tools (query_food_database, get_recent_meals,
         analyze_with_gemini) as needed.
      3. Extracts validated Decisions from Luna's final output.

    If Luna fails to produce a valid decision within MAX_STEPS, returns None
    so the caller can fall back to the legacy per-photo Gemini path.
    """

    def __init__(self, *, luna_api_key: str, luna_base_url: str | None = None,
                 luna_model: str = "gpt-5.6-luna", deps: dict | None = None):
        client_kwargs: dict[str, Any] = {"api_key": luna_api_key}
        if luna_base_url:
            client_kwargs["base_url"] = luna_base_url
        self._client = OpenAI(max_retries=0, **client_kwargs)
        self._model = luna_model
        # deps carries everything tools need (db is implicit via src.db,
        # gemini_analyzer, image_getter, assets)
        self._deps = deps or {}
        self._tools = _to_responses_tools(TOOL_SCHEMAS)

    # ── public API ────────────────────────────────────────────────────

    def run(self, assets: list[dict[str, Any]], image_getter) -> list[Decision] | None:
        """
        Run the Luna loop on a batch of new food-photo assets.

        assets: list of dicts with keys asset_id, photo_time, source, image_bytes
        image_getter: callable(asset_id) -> bytes  (original image for Gemini)

        Returns a list of validated Decisions, or None on failure (caller should
        fall back to legacy path).
        """
        if not assets:
            logger.warning("AgentHarness.run called with empty assets")
            return None

        # Store batch assets + getter in deps so tools can access them
        self._deps["assets"] = assets
        self._deps["image_getter"] = image_getter

        # Resend the full accumulated history every round: previous_response_id
        # is IGNORED by the current endpoint (HTTP 200, no context carried), so
        # sending only the delta would drop the images and the original prompt
        # after the first tool call. Multi-MB originals are re-uploaded per
        # round as a result; prefix caching still covers them (see module doc).
        input_items: list[dict[str, Any]] = [self._build_user_message(assets)]

        for step in range(1, MAX_STEPS + 1):
            logger.info("Luna step %d/%d", step, MAX_STEPS)
            try:
                resp = self._call_luna(input_items)
            except Exception as e:
                logger.error("Luna call failed at step %d: %s", step, e)
                return None  # caller falls back

            # ── function calls → execute and feed back ──
            calls = [it for it in resp.output if getattr(it, "type", None) == "function_call"]
            if calls:
                deltas: list[dict[str, Any]] = []
                for tc in calls:
                    result = self._execute_tool(tc.call_id, tc.name, tc.arguments)
                    # Without previous_response_id the model has no record of
                    # what it called, so replay the call item itself right
                    # before its output (Responses expects this pairing).
                    deltas.append({
                        "type": "function_call",
                        "call_id": tc.call_id,
                        "name": tc.name,
                        "arguments": tc.arguments or "{}",
                    })
                    deltas.append({
                        "type": "function_call_output",
                        "call_id": tc.call_id,
                        "output": json.dumps(result, ensure_ascii=False),
                    })
                input_items += deltas
                continue

            # ── final text → try to parse as decision ──
            if getattr(resp, "status", "completed") != "completed":
                reason = getattr(getattr(resp, "incomplete_details", None), "reason", None)
                logger.warning("Luna response %s at step %d (reason=%s)",
                               resp.status, step, reason)
                return None

            content = self._extract_output_text(resp)
            if not content:
                logger.warning("Luna returned empty output_text at step %d", step)
                return None

            try:
                decisions = parse_decisions_json(content)
                # Hard safety net: all-zero / not-real-food results must be
                # skip, regardless of what Luna decided (todo-2 guarantee).
                decisions = enforce_zero_skip(decisions)
                logger.info(
                    "Luna decisions: %d total (actions=%s)",
                    len(decisions),
                    [d.action for d in decisions],
                )
                return decisions
            except ValueError as e:
                logger.warning("Luna output not a valid decision at step %d: %s", step, e)
                # Give Luna one chance to correct itself (append, do not reset)
                input_items += [{
                    "role": "user",
                    "content": (
                        "你的输出不符合契约。请只输出一个符合契约的 JSON 对象，"
                        "不要 markdown 代码块，不要解释性文字。"
                    ),
                }]
                # loop continues; next iteration should produce valid JSON

        logger.warning("Luna loop exhausted (%d steps), no valid decision", MAX_STEPS)
        return None

    # ── internals ─────────────────────────────────────────────────────

    def _build_user_message(self, assets: list[dict[str, Any]]) -> dict:
        """Build the user input item: text listing assets + all images inline."""
        content: list[dict[str, Any]] = [
            {"type": "input_text", "text": build_user_prompt(assets)}
        ]
        for a in assets:
            img_bytes = a.get("image_bytes")
            if img_bytes:
                b64 = base64.b64encode(img_bytes).decode("utf-8")
                mime = detect_image_mime(img_bytes)
                content.append({
                    "type": "input_image",
                    "image_url": f"data:{mime};base64,{b64}",
                })
        return {"role": "user", "content": content}

    def _extract_output_text(self, resp) -> str:
        """Join all output_text parts across the response's message items."""
        parts: list[str] = []
        for item in resp.output or []:
            if getattr(item, "type", None) != "message":
                continue
            for p in getattr(item, "content", None) or []:
                if getattr(p, "type", None) == "output_text":
                    parts.append(p.text or "")
        return "".join(parts).strip()

    def _call_luna(self, input_items: list[dict[str, Any]]):
        """Single Luna Responses-API call with retry on transient errors.

        NOTE: previous_response_id is deliberately NOT sent. The current
        endpoint accepts it but ignores it (HTTP 200, no context carried),
        which silently drops all history after the first tool round. The
        caller accumulates the full input instead.
        """
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                kwargs: dict[str, Any] = {
                    "model": self._model,
                    "instructions": SYSTEM_PROMPT,
                    "input": input_items,
                    "tools": self._tools,
                    "tool_choice": "auto",
                    # NOTE: no temperature — reasoning-model upstreams often
                    # reject non-default values; keep gateway defaults.
                    "max_output_tokens": MAX_TOKENS_PER_CALL,
                    "timeout": LUNA_TIMEOUT_S,
                }
                # commented out: previous_response_id is ignored by the
                # current endpoint, so chaining would lose the history.
                # if previous_response_id:
                #     kwargs["previous_response_id"] = previous_response_id
                return self._client.responses.create(**kwargs)
            except Exception as e:
                last_err = e
                msg = str(e).lower()
                transient = any(k in msg for k in (
                    "429", "503", "502", "504", "rate", "overloaded",
                    "timeout", "connection",
                ))
                if not transient or attempt == 2:
                    raise
                delay = 2 ** (attempt + 1)
                logger.warning("Luna transient error (attempt %d/3), retry in %ds: %s",
                               attempt + 1, delay, str(e)[:120])
                time.sleep(delay)
        raise last_err  # unreachable, but satisfies type checker

    def _execute_tool(self, call_id: str, name: str, args_json: str | None) -> dict:
        """Execute one tool call and return a bounded plain result dict."""
        try:
            args = json.loads(args_json or "{}")
        except json.JSONDecodeError as e:
            logger.error("tool %s invalid args JSON: %s", name, e)
            return {"ok": False, "error": f"invalid args JSON: {e}"}

        logger.info("tool call: %s(%s)", name, json.dumps(args, ensure_ascii=False)[:200])
        result = call_tool(name, args, self._deps)
        # Keep results bounded WITHOUT breaking JSON validity
        # (bounded lists are more useful than truncated strings).
        return _bounded_result(result)

    def close(self):
        """No-op; kept for interface symmetry with other components."""
        pass
