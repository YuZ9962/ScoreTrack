from __future__ import annotations

import logging
import os
from typing import Any

from google import genai

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-3-flash-preview"
DEFAULT_THINKING_LEVEL = "medium"
ALLOWED_THINKING_LEVELS = {"minimal", "low", "medium", "high"}


def _resolve_model() -> str:
    model = (os.getenv("GEMINI_MODEL") or "").strip()
    return model or DEFAULT_MODEL


def _resolve_thinking_level() -> str:
    level = (os.getenv("GEMINI_THINKING_LEVEL") or "").strip().lower()
    if level in ALLOWED_THINKING_LEVELS:
        return level
    return DEFAULT_THINKING_LEVEL


def _build_client() -> tuple[genai.Client | None, str | None]:
    api_key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key:
        return None, "未配置 GEMINI_API_KEY"

    try:
        return genai.Client(api_key=api_key), None
    except Exception as exc:
        logger.exception("初始化 Gemini 客户端失败")
        return None, "Gemini 请求失败，请检查模型配置或 API key"


def run_gemini_prediction(prompt: str) -> dict[str, Any]:
    model = _resolve_model()
    thinking_level = _resolve_thinking_level()

    client, err = _build_client()
    if err:
        return {
            "ok": False,
            "model": model,
            "thinking_level": thinking_level,
            "prompt": prompt,
            "text": "",
            "error": err,
        }

    try:
        # Gemini 3 + thinking_level（通过 thinking_config 控制）
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config={
                "thinking_config": {
                    "thinking_level": thinking_level,
                }
            },
        )
        text = (response.text or "").strip()
        if not text:
            return {
                "ok": False,
                "model": model,
                "thinking_level": thinking_level,
                "prompt": prompt,
                "text": "",
                "error": "Gemini 返回为空",
            }

        return {
            "ok": True,
            "model": model,
            "thinking_level": thinking_level,
            "prompt": prompt,
            "text": text,
            "error": "",
        }
    except Exception:
        logger.exception("Gemini 预测请求失败")
        return {
            "ok": False,
            "model": model,
            "thinking_level": thinking_level,
            "prompt": prompt,
            "text": "",
            "error": "Gemini 请求失败，请检查模型配置或 API key",
        }
