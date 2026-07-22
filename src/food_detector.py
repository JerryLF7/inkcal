"""
Local food detection via SigLIP2 classifier.
Runs on CPU, no data leaves this machine.
Prefers fine-tuned local model over HuggingFace base.
"""

import io
import logging
from pathlib import Path
from typing import Any

from PIL import Image

logger = logging.getLogger(__name__)

MODEL_NAME = "prithivMLmods/Food-or-Not-SigLIP2"
LOCAL_MODEL = Path(__file__).resolve().parent.parent / "data" / "finetuned-model"


def _model_path():
    """Return the best available model path: local fine-tuned > HuggingFace."""
    if LOCAL_MODEL.exists() and (LOCAL_MODEL / "model.safetensors").exists():
        return str(LOCAL_MODEL)
    return MODEL_NAME


class FoodDetector:
    def __init__(self, model_path=None):
        # Lazy imports so torch/transformers don't block the whole script
        from transformers import AutoImageProcessor, AutoModelForImageClassification
        import torch

        self._torch = torch
        path = model_path or _model_path()
        logger.info("Loading food classifier: %s ...", path)
        self._model = AutoModelForImageClassification.from_pretrained(path)
        self._processor = AutoImageProcessor.from_pretrained(path)
        self._model.eval()

    def _preprocess(self, image_bytes: bytes):
        """Convert raw bytes to RGB PIL Image."""
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        return self._processor(images=img, return_tensors="pt")

    def score(self, image_bytes: bytes) -> float:
        """Return food-class probability (0.0–1.0) from softmax over logits."""
        try:
            inputs = self._preprocess(image_bytes)
            with self._torch.no_grad():
                outputs = self._model(**inputs)
                # id2label: {"0": "food", "1": "not-food"}
                probs = self._torch.softmax(outputs.logits, dim=1)
                food_prob = probs[0, 0].item()
            logger.debug("Food classifier score: %.3f", food_prob)
            return food_prob
        except Exception as e:
            logger.error("Food classification failed: %s", e)
            return 0.0

    def is_food(self, image_bytes: bytes) -> bool:
        """Classify the image: True = food, False = not food."""
        return self.score(image_bytes) >= 0.5

    def close(self):
        pass
