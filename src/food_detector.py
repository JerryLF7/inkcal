"""
Local food detection via SigLIP2 classifier.
Runs on CPU, no data leaves this machine. Base model only, offline-cached.
"""

import io
import logging
import os

from src.env_file import raw_env

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

# 判定线（唯一来源：main.py 与 Web 路径都从这里取）。
# 基础 SigLIP2 对中餐/米饭类漏检严重：2026-09-27 晚餐（真食物）只拿 0.436。
# 标定数据（近两周 175 张拒收样本，Gemini 打真值）：
#   >=0.4 → 真食物 36% | 0.3~0.4 → 33% | 0.2~0.3 → 21% | <0.2 → 7%
# 0.35 捞回 ~6 餐/两周，只多放 8 张非食物进 Luna（Luna 侧 skip 契约兜底）；
# 再降到 0.25 只多捞 2 餐却多放 13 张，收益已衰减。
#
# 2026-10-02 复核（130 张重新打分）：漏放的非食物中位数 0.782，真食物 0.791，
# 两者几乎完全重叠——**往上调阈值救不回漏检**（0.55 只能拦住 9/50，却误杀 12/80）。
# 漏放的主要是截图、自拍、菜单这些「食物相关但不是真餐」的图，模型确实给高分，
# 靠下游 skip 兜底才是有效路径。所以默认值维持 0.35。
DEFAULT_FOOD_THRESHOLD = 0.35
GREY_ZONE_WIDTH = 0.10
_ENV_KEY = "FOOD_THRESHOLD"


def food_threshold() -> float:
    """当前判定线。**每次调用都重新解析**，所以改完 .env 下一次分类就生效，不用重启。

    优先级：`.env` 文件 > 进程环境变量 > 默认值。文件优先是刻意的——用户改的是
    `.env`，而长驻进程的 os.environ 是启动时的快照。

    取值必须是 0~1 的小数。非法值（比如把百分比写成 `35`）一律回退默认值并告警：
    静默按非法值跑会把全部照片判成食物或全判成非食物，而后者是无声的灾难。
    """
    raw = raw_env(_ENV_KEY)
    origin = ".env"
    if raw is None:
        raw = os.getenv(_ENV_KEY)
        origin = "环境变量"
    if raw is None or raw == "":
        return DEFAULT_FOOD_THRESHOLD

    try:
        value = float(raw)
    except ValueError:
        logger.warning(
            "FOOD_THRESHOLD=%r（来自 %s）不是数字，回退默认值 %.2f", raw, origin, DEFAULT_FOOD_THRESHOLD
        )
        return DEFAULT_FOOD_THRESHOLD

    if not 0.0 <= value <= 1.0:
        # 只在看起来确实是把百分比当小数写时才给换算建议（1 < v <= 100），
        # 否则 1.5 / -1 这种会给出「请写 0.01」之类的胡话。
        hint = ""
        if 1.0 < value <= 100.0:
            hint = f"；如果你是想写 {value:g}%，应该写 {value / 100:.2f}"
        logger.warning(
            "FOOD_THRESHOLD=%r（来自 %s）必须是 0~1 之间的小数，已回退默认值 %.2f%s",
            raw, origin, DEFAULT_FOOD_THRESHOLD, hint,
        )
        return DEFAULT_FOOD_THRESHOLD

    return value


def grey_zone() -> float:
    """擦边区下沿：低于判定线但仍值得人看一眼，记 classifier_unsure。"""
    return food_threshold() - GREY_ZONE_WIDTH


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
        return self.score(image_bytes) >= food_threshold()

    def close(self):
        pass
