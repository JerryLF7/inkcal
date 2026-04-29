"""
Calorie analysis via OpenAI-compatible API (Gemini / custom endpoint).
Only called for photos already identified as food by local detector.
"""

import base64
import json
import logging
from typing import Any

from openai import OpenAI

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a nutritionist analyzing a food photo.
Return a JSON object with EXACTLY these fields:
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
    def __init__(self, api_key: str, base_url: str | None = None, model: str = "gemini-2.5-flash"):
        client_kwargs = {"api_key": api_key}
        if base_url:
            client_kwargs["base_url"] = base_url
        self.model = model
        self._client = OpenAI(**client_kwargs)

    def analyze(self, image_bytes: bytes) -> dict[str, Any]:
        """
        Send food photo to LLM and get calorie analysis.
        Returns dict with meal, calories, macros, confidence.
        """
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        data_url = f"data:image/jpeg;base64,{b64}"

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

            text = r.choices[0].message.content or "{}"
            result = json.loads(text)
            logger.info("Gemini analysis: %s", result)
            return result

        except Exception as e:
            logger.error("Calorie analysis failed: %s", e)
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
