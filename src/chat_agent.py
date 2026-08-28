"""
Chat agent — thin conversational loop around Luna (OpenAI Responses API).

Same architecture as agent_harness.py (the ONLY layer that changes if we
swap to fx), but for the long-lived conversational session:

- Business state lives in SQLite (records / chat_* tables). The Responses
  chain (previous_response_id) is a rebuildable server-side cache, not the
  source of truth: if the chain breaks (upstream TTL, relay hiccup), we
  rebuild context from the last N chat_messages and start a fresh chain.
- Sliding window (chat_window setting, default 20 turns) only applies at
  rebuild time — while the chain is alive, context lives server-side and
  prompt cache carries it (measured 98-99.99% hit rate).
- Write tools go through the same audited paths as CLI/web; delete is
  never executed by the agent, only surfaced as a confirmation card.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from openai import OpenAI

from src import db
from src.agent_contract import CHAT_SYSTEM_PROMPT, CHAT_TOOL_SCHEMAS
from src.agent_harness import _bounded_result, _to_responses_tools
from src.agent_tools import call_chat_tool

logger = logging.getLogger("inkcal.chat_agent")

HKT = timezone(timedelta(hours=8))

MAX_STEPS = 8             # model/tool rounds per user message
MAX_TOKENS_PER_CALL = 8192
LUNA_TIMEOUT_S = 120
DEFAULT_WINDOW = 20       # turns; user-configurable via app_settings


class ChatAgent:
    """Conversational loop: user text in -> (tool calls) -> reply text out.

    Returns a dict {reply, tool_log, response_id} on success, or
    {"error": ...} on failure. Persists both sides of the turn to
    chat_messages regardless (the user's message is kept even if the
    model call fails, so history reflects what was actually said).
    """

    def __init__(self, *, luna_api_key: str, luna_base_url: str | None = None,
                 luna_model: str = "gpt-5.6-luna", deps: dict | None = None):
        client_kwargs: dict[str, Any] = {"api_key": luna_api_key}
        if luna_base_url:
            client_kwargs["base_url"] = luna_base_url
        self._client = OpenAI(max_retries=0, **client_kwargs)
        self._model = luna_model
        self._deps = deps or {}
        self._tools = _to_responses_tools(CHAT_TOOL_SCHEMAS)

    # ── public API ────────────────────────────────────────────────────

    def send(self, session_id: int, user_text: str) -> dict:
        user_text = (user_text or "").strip()
        if not user_text:
            return {"error": "empty message"}

        window = self._window()
        db.add_chat_message(session_id, "user", user_text)
        self._maybe_set_title(session_id, user_text)

        input_items: list[dict[str, Any]] = [
            {"role": "user", "content": user_text}
        ]
        prev_id = db.get_last_response_id(session_id)
        rebuilt = False
        tool_log: list[dict[str, Any]] = []

        for step in range(1, MAX_STEPS + 1):
            try:
                resp = self._call_luna(input_items, previous_response_id=prev_id)
            except Exception as e:
                if prev_id and not rebuilt and self._looks_like_stale_chain(e):
                    logger.info("response chain stale, rebuilding from SQLite: %s", e)
                    input_items = self._rebuild_context(session_id, window)
                    prev_id = None
                    rebuilt = True
                    continue
                logger.error("chat Luna call failed at step %d: %s", step, e)
                return {"error": f"model call failed: {e}", "tool_log": tool_log}
            prev_id = resp.id

            calls = [it for it in resp.output if getattr(it, "type", None) == "function_call"]
            if calls:
                deltas: list[dict[str, Any]] = []
                for tc in calls:
                    try:
                        args = json.loads(tc.arguments or "{}")
                    except json.JSONDecodeError as e:
                        result = {"ok": False, "error": f"invalid args JSON: {e}"}
                        args = {}
                    else:
                        logger.info("chat tool call: %s(%s)", tc.name,
                                    json.dumps(args, ensure_ascii=False)[:200])
                        result = call_chat_tool(tc.name, args, self._deps)
                    result = _bounded_result(result)
                    tool_log.append({"name": tc.name, "args": args, "result": result})
                    deltas.append({
                        "type": "function_call_output",
                        "call_id": tc.call_id,
                        "output": json.dumps(result, ensure_ascii=False),
                    })
                input_items = deltas
                continue

            reply = self._extract_output_text(resp)
            if not reply:
                logger.warning("chat Luna empty output at step %d", step)
                return {"error": "empty model output", "tool_log": tool_log}

            db.add_chat_message(session_id, "assistant", reply,
                                tool_log=tool_log, response_id=resp.id)
            return {"reply": reply, "tool_log": tool_log, "response_id": resp.id}

        logger.warning("chat loop exhausted (%d steps)", MAX_STEPS)
        return {"error": "loop exhausted", "tool_log": tool_log}

    # ── internals ─────────────────────────────────────────────────────

    def _window(self) -> int:
        try:
            n = int(db.get_setting("chat_window", str(DEFAULT_WINDOW)))
        except ValueError:
            n = DEFAULT_WINDOW
        return max(5, min(50, n))

    def _maybe_set_title(self, session_id: int, user_text: str):
        """First user message becomes the session title (truncated)."""
        msgs = db.get_chat_messages(session_id, limit=2)
        if len(msgs) == 1:  # only the one we just added
            db.set_chat_session_title(session_id, user_text[:20])

    def _rebuild_context(self, session_id: int, window: int) -> list[dict]:
        """Reconstruct model input from the last `window` turns in SQLite.
        Tool-call detail from old turns is dropped (facts are re-queryable);
        only user/assistant text is replayed."""
        msgs = db.get_chat_messages(session_id, limit=window * 2)
        return [{"role": m["role"], "content": m["content"]} for m in msgs]

    @staticmethod
    def _looks_like_stale_chain(e: Exception) -> bool:
        msg = str(e).lower()
        return "previous_response" in msg or "not found" in msg

    def _instructions(self) -> str:
        now = datetime.now(HKT)
        return CHAT_SYSTEM_PROMPT.format(
            now=now.strftime("%Y-%m-%d %H:%M"),
            today=now.strftime("%Y-%m-%d"),
        )

    def _extract_output_text(self, resp) -> str:
        parts: list[str] = []
        for item in resp.output or []:
            if getattr(item, "type", None) != "message":
                continue
            for p in getattr(item, "content", None) or []:
                if getattr(p, "type", None) == "output_text":
                    parts.append(p.text or "")
        return "".join(parts).strip()

    def _call_luna(self, input_items: list[dict[str, Any]], *,
                   previous_response_id: str | None = None):
        """Single Responses call with retry on transient errors."""
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                kwargs: dict[str, Any] = {
                    "model": self._model,
                    "instructions": self._instructions(),
                    "input": input_items,
                    "tools": self._tools,
                    "tool_choice": "auto",
                    "max_output_tokens": MAX_TOKENS_PER_CALL,
                    "timeout": LUNA_TIMEOUT_S,
                }
                if previous_response_id:
                    kwargs["previous_response_id"] = previous_response_id
                return self._client.responses.create(**kwargs)
            except Exception as e:
                last_err = e
                # Stale-chain errors are handled by the caller (rebuild);
                # retrying them here would be pointless.
                if self._looks_like_stale_chain(e):
                    raise
                msg = str(e).lower()
                transient = any(k in msg for k in (
                    "429", "503", "502", "504", "rate", "overloaded",
                    "timeout", "connection",
                ))
                if not transient or attempt == 2:
                    raise
                delay = 2 ** (attempt + 1)
                logger.warning("chat Luna transient error (attempt %d/3), "
                               "retry in %ds: %s", attempt + 1, delay, str(e)[:120])
                time.sleep(delay)
        raise last_err  # unreachable, but satisfies type checker
