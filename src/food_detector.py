"""
Local food detection via SigLIP2 classifier.
Runs on CPU, no data leaves this machine. Base model only, offline-cached.
"""

import io
import logging
import os

# The base model is fully cached in ~/.cache/huggingface — never phone home.
# On this network huggingface.co is unreachable, and transformers' update
# check would retry for minutes then crash the pipeline (cron went silent
# after the 2026-08-22 reboot for exactly this reason). Must be set before
# transformers is imported / from_pretrained is called.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from PIL import Image

logger = logging.getLogger(__name__)

MODEL_NAME = "prithivMLmods/Food-or-Not-SigLIP2"

# 判定线（唯一来源，main.py 与 Web 路径都从这里取）。
# 基础 SigLIP2 对中餐/米饭类漏检严重：2026-09-27 晚餐（真食物）只拿 0.436。
# 标定数据（近两周 175 张拒收样本，Gemini 打真值）：
#   >=0.4 → 真食物 36% | 0.3~0.4 → 33% | 0.2~0.3 → 21% | <0.2 → 7%
# 0.35 捞回 ~6 餐/两周，只多放 8 张非食物进 Luna（Luna 侧 skip 契约兜底）；
# 再降到 0.25 只多捞 2 餐却多放 13 张，收益已衰减。
FOOD_THRESHOLD = 0.35
GREY_ZONE = FOOD_THRESHOLD - 0.1  # 擦边区下沿：低于线但仍值得人看一眼，记 classifier_unsure


class FoodDetector:
    def __init__(self):
        # Lazy imports so torch/transformers don't block the whole script
        from transformers import AutoImageProcessor, AutoModelForImageClassification
        import torch

        self._torch = torch
        logger.info("Loading food classifier: %s ...", MODEL_NAME)
        self._model = AutoModelForImageClassification.from_pretrained(MODEL_NAME)
        self._processor = AutoImageProcessor.from_pretrained(MODEL_NAME)
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
        return self.score(image_bytes) >= FOOD_THRESHOLD

    def close(self):
        pass
