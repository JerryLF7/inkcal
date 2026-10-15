"""
Calorie analysis via OpenAI-compatible API (Gemini / custom endpoint).
Only called for photos already identified as food by local detector.
"""

import base64
import json
import logging
import os
import time
from typing import Any

from openai import OpenAI

from src.env_file import raw_env
from src.prompts.loader import get_analyze_prompt, get_reanalyze_prompt, get_analyze_text_prompt

logger = logging.getLogger(__name__)

MAX_RETRIES = 5
RETRY_BACKOFF = 2  # seconds, doubles each retry

# ── 推理强度（thinking budget）────────────────────────────────────────
# 网关只认 OpenAI 的 `reasoning_effort`，其他形状——reasoning.effort、
# reasoning.max_tokens、thinking_level、thinking_config、thinking_budget、
# thinking.budget_tokens、thinkingConfig.thinkingBudget、
# generationConfig.thinkingConfig——**全部被静默丢弃**，而且未知字段名
# （甚至乱填的 key）都返回 200 不报错，`reasoning_effort` 传非法值同样不 400，
# 所以只能靠 usage.completion_tokens_details.reasoning_tokens 做行为判别。
# 探测日期 2026-10-15，模型 gemini-3.1-pro-preview。
#
# 可选档位（写在 .env 的 GEMINI_REASONING_EFFORT）：
#   none / minimal / low   思考归零。最快，但估算最不稳，不推荐用于入库。
#   medium                 等于网关不传参数时的默认档。
#   high                   默认值。比默认档多约 2.2 倍思考量。
#
# 真实餐照实测（四菜一饭盒饭，入库值 1040 kcal）：
#   默认/medium  17–28s，reasoning 780–810，confidence 多为 medium
#   high         30–36s，reasoning 1470–2240，confidence 出现过 high
# 三图同餐组 high 32s / reasoning 2781；纯文本补录 high 14.5s。
# 代价约每次调用 +10s，换的是估算稳定性——这是入库数值，值得。
DEFAULT_REASONING_EFFORT = "high"
VALID_REASONING_EFFORTS = ("none", "minimal", "low", "medium", "high")
_ENV_KEY = "GEMINI_REASONING_EFFORT"


def get_reasoning_effort() -> str:
    """当前推理强度。**每次调用都重新解析**，所以改完 .env 下一次分析就生效，不用重启。

    优先级：`.env` 文件 > 进程环境变量 > 默认值 `high`。文件优先是刻意的——用户改的是
    `.env`，而长驻进程（Flask）的 os.environ 是启动时的快照。

    档位名大小写不敏感。非法值一律回退默认值并告警：网关对无法识别的档位不报错、
    而是静默按高档跑，所以写错的代价是每次调用都白烧一倍以上的思考量，且没有任何
    报错——必须自己拦住。
    """
    raw = raw_env(_ENV_KEY)
    origin = ".env"
    if raw is None:
        raw = os.getenv(_ENV_KEY)
        origin = "环境变量"
    if raw is None or raw == "":
        return DEFAULT_REASONING_EFFORT

    value = raw.strip().lower()
    if value not in VALID_REASONING_EFFORTS:
        logger.warning(
            "GEMINI_REASONING_EFFORT=%r（来自 %s）不是合法档位，回退默认值 %s。可选：%s",
            raw, origin, DEFAULT_REASONING_EFFORT, " / ".join(VALID_REASONING_EFFORTS),
        )
        return DEFAULT_REASONING_EFFORT
    return value

# Prompts live in src/prompts/*.md — see src/prompts/loader.py.


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
                    reasoning_effort=get_reasoning_effort(),
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
                    reasoning_effort=get_reasoning_effort(),
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
                    reasoning_effort=get_reasoning_effort(),
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
