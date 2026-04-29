"""
Local food detection via SigLIP2 classifier.
Runs on CPU, no data leaves this machine.
"""

import io
import logging
from typing import Any

from PIL import Image

logger = logging.getLogger(__name__)

MODEL_NAME = "prithivMLmods/Food-or-Not-SigLIP2"


class FoodDetector:
    def __init__(self):
        # Lazy imports so torch/transformers don't block the whole script
        from transformers import AutoImageProcessor, SiglipForImageClassification
        import torch

        self._torch = torch
        logger.info("Loading food classifier: %s ...", MODEL_NAME)
        self._model = SiglipForImageClassification.from_pretrained(MODEL_NAME)
        self._processor = AutoImageProcessor.from_pretrained(MODEL_NAME)
        self._model.eval()

    def _preprocess(self, image_bytes: bytes):
        """Convert raw bytes to RGB PIL Image."""
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        return self._processor(images=img, return_tensors="pt")

    def is_food(self, image_bytes: bytes) -> bool:
        """Classify the image: True = food, False = not food."""
        try:
            inputs = self._preprocess(image_bytes)
            with self._torch.no_grad():
                outputs = self._model(**inputs)
                # id2label: {"0": "food", "1": "not-food"}
                pred = self._torch.argmax(outputs.logits, dim=1).item()
            logger.debug("Food classifier: %s", "food" if pred == 0 else "not-food")
            return pred == 0
        except Exception as e:
            logger.error("Food classification failed: %s", e)
            return False

    def close(self):
        pass
