from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from google import genai

try:
    from google.genai import types as genai_types
except Exception:  # pragma: no cover
    genai_types = None

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-3-flash-preview"
DEFAULT_THINKING_LEVEL = "high"
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
    except Exception:
        logger.exception("初始化 Gemini 客户端失败")
        return None, "Gemini 请求失败，请检查模型配置或 API key"



def _is_thinking_config_error(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    keywords = ["thinking_config", "extra inputs are not permitted", "extra_forbidden", "validationerror"]
    return any(k in text for k in keywords)



def _build_thinking_config(thinking_level: str):
    if genai_types is None:
        raise RuntimeError("google.genai.types 不可用")
    return genai_types.GenerateContentConfig(
        thinking_config=genai_types.ThinkingConfig(thinking_level=thinking_level)
    )



def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()



def run_gemini_prediction(prompt: str) -> dict[str, Any]:
    model = _resolve_model()
    thinking_level = _resolve_thinking_level()

    client, err = _build_client()
    if err:
        return {
            "ok": False,
            "model": model,
            "thinking_level": thinking_level,
            "thinking_applied": False,
            "prompt": prompt,
            "text": "",
            "generated_at": _now_iso(),
            "error": err,
        }

    try:
        config = _build_thinking_config(thinking_level)
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=config,
        )
        text = (response.text or "").strip()
        if not text:
            return {
                "ok": False,
                "model": model,
                "thinking_level": thinking_level,
                "thinking_applied": True,
                "prompt": prompt,
                "text": "",
                "generated_at": _now_iso(),
                "error": "Gemini 返回为空",
            }
        return {
            "ok": True,
            "model": model,
            "thinking_level": thinking_level,
            "thinking_applied": True,
            "prompt": prompt,
            "text": text,
            "generated_at": _now_iso(),
            "error": "",
        }
    except Exception as exc:
        if _is_thinking_config_error(exc):
            logger.warning("Gemini thinking_config 不兼容，自动回退无 thinking 模式: %s", type(exc).__name__)
        else:
            logger.exception("Gemini（thinking 模式）请求失败")
            return {
                "ok": False,
                "model": model,
                "thinking_level": thinking_level,
                "thinking_applied": False,
                "prompt": prompt,
                "text": "",
                "generated_at": _now_iso(),
                "error": "Gemini 请求失败，请检查模型配置或 API key",
            }

    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
        )
        text = (response.text or "").strip()
        if not text:
            return {
                "ok": False,
                "model": model,
                "thinking_level": thinking_level,
                "thinking_applied": False,
                "prompt": prompt,
                "text": "",
                "generated_at": _now_iso(),
                "error": "Gemini 返回为空",
            }
        return {
            "ok": True,
            "model": model,
            "thinking_level": thinking_level,
            "thinking_applied": False,
            "prompt": prompt,
            "text": text,
            "generated_at": _now_iso(),
            "error": "",
        }
    except Exception:
        logger.exception("Gemini（回退无 thinking 模式）请求失败")
        return {
            "ok": False,
            "model": model,
            "thinking_level": thinking_level,
            "thinking_applied": False,
            "prompt": prompt,
            "text": "",
            "generated_at": _now_iso(),
            "error": "Gemini 请求失败，请检查模型配置或 API key",
        }
