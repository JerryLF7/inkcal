"""
Calorie analysis via OpenAI-compatible API (Gemini / custom endpoint).
Only called for photos already identified as food by local detector.
"""

import base64
import json
import logging
import time
from typing import Any

from openai import OpenAI

from src.prompts.loader import get_analyze_prompt, get_reanalyze_prompt, get_analyze_text_prompt

logger = logging.getLogger(__name__)

MAX_RETRIES = 5
RETRY_BACKOFF = 2  # seconds, doubles each retry

# Prompts live in src/prompts/{analyze,reanalyze}.md and can be overridden
# by ~/.inkcal/prompts/{analyze,reanalyze}.md — see src/prompts/loader.py.


class CalorieAnalyzer:
    def __init__(self, api_key: str, base_url: str | None = None, model: str = "gemini-3-flash-preview"):
        client_kwargs = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        self.model = model
        self._client = OpenAI(max_retries=0, **client_kwargs)

    def analyze(self, image_bytes: bytes) -> dict[str, Any]:
        """
        Send food photo to LLM and get calorie analysis.
        Retries on 429/503 with exponential backoff.
        """
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        data_url = f"data:image/jpeg;base64,{b64}"

        for attempt in range(MAX_RETRIES + 1):
            try:
                r = self._client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "user", "content": [
                            {"type": "text", "text": get_analyze_prompt()},
                            {"type": "image_url", "image_url": {"url": data_url}},
                        ]},
                    ],
                    temperature=0.2,
                    response_format={"type": "json_object"},
                )
                return self._parse_response(r)

            except Exception as e:
                if self._should_retry(e, attempt):
                    delay = RETRY_BACKOFF ** (attempt + 1)
                    logger.warning("API 错误 (attempt %d/%d)，%ds 后重试: %s", attempt + 1, MAX_RETRIES, delay, str(e)[:120])
                    time.sleep(delay)
                    continue
                logger.error("Calorie analysis failed: %s", e)
                return self._empty_result()

        return self._empty_result()

    def _should_retry(self, e: Exception, attempt: int) -> bool:
        if attempt >= MAX_RETRIES:
            return False
        msg = str(e).lower()
        return (
            "429" in msg or "503" in msg or "502" in msg or "504" in msg
            or "rate" in msg or "overloaded" in msg
            or "bad gateway" in msg or "gateway timeout" in msg
            or "connection error" in msg or "timeout" in msg
        )

    def _parse_response(self, r: Any) -> dict[str, Any]:
        if isinstance(r, str):
            text = r
        elif hasattr(r, "choices") and r.choices:
            text = r.choices[0].message.content or "{}"
        elif isinstance(r, dict) and "choices" in r and r["choices"]:
            text = r["choices"][0]["message"]["content"] or "{}"
        else:
            text = str(r)

        text = (text or "").strip()
        if not text:
            logger.warning("API returned empty content, raw response: %s", repr(r)[:500])
            text = "{}"

        # Strip markdown code fences if present
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        try:
            result = json.loads(text)
        except json.JSONDecodeError as e:
            # Try to fix common truncation: missing closing brace
            if not text.endswith("}"):
                try:
                    result = json.loads(text + "}")
                    logger.warning("Fixed truncated JSON by appending '}'")
                except json.JSONDecodeError:
                    logger.error("JSON parse failed: %s | text: %s", e, text[:200])
                    result = self._empty_result()
            elif text.count("{") != text.count("}"):
                # Extra closing brace(s); trim from the end until balanced
                trimmed = text.rstrip("}")
                while trimmed and trimmed.count("{") < trimmed.count("}"):
                    trimmed = trimmed[:-1].rstrip("}")
                try:
                    result = json.loads(trimmed)
                    logger.warning("Fixed unbalanced JSON by trimming extra '}'")
                except json.JSONDecodeError:
                    logger.error("JSON parse failed: %s | text: %s", e, text[:200])
                    result = self._empty_result()
            else:
                logger.error("JSON parse failed: %s | text: %s", e, text[:200])
                result = self._empty_result()

        logger.info("Gemini analysis: %s", result)
        return result

    def reanalyze(self, image_bytes: bytes | list[bytes], current_result: dict[str, Any], notes: str) -> dict[str, Any]:
        """Re-analyze a food photo (or all photos of one meal group) with
        user-provided additional context.

        image_bytes: 单张图，或同餐组的全部照片（联合评估整餐，重复食物只算一次）。
        """
        if isinstance(image_bytes, bytes):
            image_bytes = [image_bytes]
        image_contents = []
        for ib in image_bytes:
            b64 = base64.b64encode(ib).decode("utf-8")
            url = "data" + ":image/jpeg;base64," + b64
            image_contents.append({
                "type": "image_url",
                "image_url": {"url": url},
            })

        prompt = get_reanalyze_prompt().format(
            meal=current_result.get("meal", "unknown"),
            meal_detail=current_result.get("meal_detail", ""),
            calories=current_result.get("calories", 0),
            protein_g=current_result.get("protein_g", 0),
            carbs_g=current_result.get("carbs_g", 0),
            fat_g=current_result.get("fat_g", 0),
            confidence=current_result.get("confidence", "low"),
            notes=notes,
        )

        for attempt in range(MAX_RETRIES + 1):
            try:
                r = self._client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "user", "content":
                            [{"type": "text", "text": prompt}] + image_contents},
                    ],
                    temperature=0.2,
                    response_format={"type": "json_object"},
                )
                return self._parse_response(r)

            except Exception as e:
                if self._should_retry(e, attempt):
                    delay = RETRY_BACKOFF ** (attempt + 1)
                    logger.warning("Reanalysis API error (attempt %d/%d), retrying in %ds: %s",
                                 attempt + 1, MAX_RETRIES, delay, str(e)[:120])
                    time.sleep(delay)
                    continue
                logger.error("Reanalysis failed: %s", e)
                return self._empty_result()

        return self._empty_result()

    def analyze_text(self, description: str, user_calories: float | None = None) -> dict[str, Any]:
        """Estimate calories and macronutrients from a text description of food."""
        prompt = get_analyze_text_prompt().format(description=description)

        for attempt in range(MAX_RETRIES + 1):
            try:
                r = self._client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.2,
                    response_format={"type": "json_object"},
                )
                res = self._parse_response(r)
                if user_calories is not None and user_calories > 0:
                    res["calories"] = float(user_calories)
                return res

            except Exception as e:
                if self._should_retry(e, attempt):
                    delay = RETRY_BACKOFF ** (attempt + 1)
                    logger.warning("Text calorie analysis API error (attempt %d/%d), %ds 后重试: %s",
                                   attempt + 1, MAX_RETRIES, delay, str(e)[:120])
                    time.sleep(delay)
                    continue
                logger.error("Text calorie analysis failed: %s", e)
                return self._empty_result()

        return self._empty_result()

    def _empty_result(self) -> dict[str, Any]:
        return {
            "meal": "unknown",
            "calories": 0,
            "protein_g": 0,
            "carbs_g": 0,
            "fat_g": 0,
            "confidence": "low",
            "emoji": "",
        }

    def close(self):
        pass
