"""
Local food detection via Ollama + moondream.

Runs on NUC, no data leaves this machine.
"""

import base64
import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class FoodDetector:
    LOCAL = "moondream"
    PROMPT = (
        "Look at this image carefully. Is there food in it? "
        "A meal, a dish, ingredients, snacks, drinks, or any edible items? "
        "Answer with exactly one word: yes or no."
    )

    def __init__(self, ollama_url: str = "http://localhost:11434", model: str = "moondream"):
        self.ollama_url = ollama_url.rstrip("/")
        self.model = model
        self._client = httpx.Client(timeout=60)

    def _image_to_base64(self, image_bytes: bytes) -> str:
        return base64.b64encode(image_bytes).decode("utf-8")

    def is_food(self, image_bytes: bytes) -> bool:
        """Ask moondream if the image contains food. Returns True/False."""
        b64 = self._image_to_base64(image_bytes)

        body = {
            "model": self.model,
            "prompt": FoodDetector.PROMPT,
            "stream": False,
            "images": [b64],
        }

        try:
            r = self._client.post(f"{self.ollama_url}/api/generate", json=body)
            r.raise_for_status()
            data = r.json()
            response_text = data.get("response", "").strip().lower()
            logger.debug("moondream response: %s", response_text)
            return "yes" in response_text
        except Exception as e:
            logger.error("Ollama query failed: %s", e)
            return False

    def close(self):
        self._client.close()
