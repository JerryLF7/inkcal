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
        elif hasattr(r, "choices"):
            text = r.choices[0].message.content or "{}"
        elif isinstance(r, dict) and "choices" in r:
            text = r["choices"][0]["message"]["content"] or "{}"
        else:
            text = str(r)

        if not text or text.strip() == "":
            logger.warning("Gemini returned empty content, raw response: %s", repr(r)[:500])
            text = "{}"

        result = json.loads(text)
        logger.info("Gemini analysis: %s", result)
        return result

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
