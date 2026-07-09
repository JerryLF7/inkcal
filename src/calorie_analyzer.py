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

logger = logging.getLogger(__name__)

MAX_RETRIES = 5
RETRY_BACKOFF = 2  # seconds, doubles each retry

SYSTEM_PROMPT = """You are a nutritionist analyzing a food photo. Carefully inspect the image first.

IMPORTANT — reject non-real-food images. Return all-zero values (calories=0, protein_g=0, carbs_g=0, fat_g=0, meal="not real food", confidence="low") if the image contains ANY of the following:
- Screenshots (chat, social media, web pages, camera roll grids, app interfaces)
- Product packaging, food posters, advertisements, menus, or billboards
- Food displayed on a screen (monitor, TV, phone)
- Drawings, paintings, or illustrations of food
- Food in a video game or virtual environment
- Printed photos of food (e.g., a physical print held up to the camera)

Only analyze REAL food that was directly photographed with a camera — a meal, dish, or ingredients physically in front of the lens.

If it IS real food, return a JSON object with EXACTLY these fields:
{
  "meal": "brief description of the food in Chinese",
  "calories": <estimated number>,
  "protein_g": <estimated grams>,
  "carbs_g": <estimated grams>,
  "fat_g": <estimated grams>,
  "confidence": "high|medium|low"
}

Be conservative with calorie estimates. Use common sense portion sizes."""

REANALYSIS_PROMPT = """You are a nutritionist re-evaluating a food photo based on additional user-provided context.

PREVIOUS ANALYSIS (for reference only — may be incorrect):
- Meal: {meal}
- Calories: {calories} kcal
- Protein: {protein_g}g
- Carbs: {carbs_g}g
- Fat: {fat_g}g
- Confidence: {confidence}

USER'S ADDITIONAL NOTES (take these as primary truth):
{notes}

INSTRUCTIONS:
1. Re-examine the image carefully, incorporating the user's notes.
2. The user's notes should OVERRIDE any assumptions from the previous analysis.
3. If the user describes portions, ingredients, or preparation methods not visible in the image, trust the user and adjust accordingly.
4. Be conservative with estimates. Use common sense portion sizes unless the user specifies otherwise.
5. Return a JSON object with EXACTLY these fields:
   {{
     "meal": "brief description of the food in Chinese",
     "calories": <estimated number>,
     "protein_g": <estimated grams>,
     "carbs_g": <estimated grams>,
     "fat_g": <estimated grams>,
     "confidence": "high|medium|low"
   }}

IMPORTANT — reject non-real-food images. Return all-zero values (calories=0, protein_g=0, carbs_g=0, fat_g=0, meal="not real food", confidence="low") if the image contains screenshots, packaging, drawings, or other non-real food content."""


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
                            {"type": "text", "text": SYSTEM_PROMPT},
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
        return "429" in msg or "503" in msg or "rate" in msg or "overloaded" in msg

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

    def reanalyze(self, image_bytes: bytes, current_result: dict[str, Any], notes: str) -> dict[str, Any]:
        """Re-analyze a food photo with user-provided additional context."""
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        data_url = f"data:image/jpeg;base64,{b64}"

        prompt = REANALYSIS_PROMPT.format(
            meal=current_result.get("meal", "unknown"),
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
                        {"role": "user", "content": [
                            {"type": "text", "text": prompt},
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
                    logger.warning("Reanalysis API error (attempt %d/%d), retrying in %ds: %s",
                                 attempt + 1, MAX_RETRIES, delay, str(e)[:120])
                    time.sleep(delay)
                    continue
                logger.error("Reanalysis failed: %s", e)
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
        }

    def close(self):
        pass
