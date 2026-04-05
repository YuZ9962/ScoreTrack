from __future__ import annotations

import logging
import os
from typing import Any

import requests

from utils.common import now_iso

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-3-flash-preview"
DEFAULT_THINKING_LEVEL = "high"
ALLOWED_THINKING_LEVELS = {"minimal", "low", "medium", "high"}

_THINKING_BUDGETS = {
    "minimal": 512,
    "low": 1024,
    "medium": 8192,
    "high": 24576,
}

_GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def _resolve_model() -> str:
    model = (os.getenv("GEMINI_MODEL") or "").strip()
    return model or DEFAULT_MODEL


def _resolve_thinking_level() -> str:
    level = (os.getenv("GEMINI_THINKING_LEVEL") or "").strip().lower()
    if level in ALLOWED_THINKING_LEVELS:
        return level
    return DEFAULT_THINKING_LEVEL


def _make_result(
    ok: bool,
    *,
    model: str,
    thinking_level: str,
    thinking_applied: bool,
    prompt: str,
    text: str,
    error: str,
) -> dict[str, Any]:
    return {
        "ok": ok,
        "model": model,
        "thinking_level": thinking_level,
        "thinking_applied": thinking_applied,
        "prompt": prompt,
        "text": text,
        "generated_at": now_iso(),
        "error": error,
    }


def _extract_text(data: dict) -> str:
    candidates = data.get("candidates") or []
    if not candidates:
        return ""
    parts = candidates[0].get("content", {}).get("parts") or []
    return "".join(p.get("text", "") for p in parts if "text" in p).strip()


def _call_rest(model: str, api_key: str, prompt: str, with_thinking: bool, thinking_level: str) -> str:
    url = _GEMINI_URL.format(model=model)
    body: dict[str, Any] = {
        "contents": [{"parts": [{"text": prompt}]}]
    }
    if with_thinking:
        budget = _THINKING_BUDGETS.get(thinking_level, 8192)
        body["generationConfig"] = {
            "thinkingConfig": {"thinkingBudget": budget}
        }
    resp = requests.post(url, params={"key": api_key}, json=body, timeout=60)
    resp.raise_for_status()
    return _extract_text(resp.json())


def run_gemini_prediction(prompt: str) -> dict[str, Any]:
    model = _resolve_model()
    thinking_level = _resolve_thinking_level()

    api_key = (os.getenv("GEMINI_API_KEY") or "").strip()
    if not api_key:
        return _make_result(False, model=model, thinking_level=thinking_level,
                            thinking_applied=False, prompt=prompt, text="",
                            error="未配置 GEMINI_API_KEY")

    # 第一次：带 thinking 调用
    try:
        text = _call_rest(model, api_key, prompt, with_thinking=True, thinking_level=thinking_level)
        if text:
            return _make_result(True, model=model, thinking_level=thinking_level,
                                thinking_applied=True, prompt=prompt, text=text, error="")
        logger.warning("Gemini（thinking 模式）返回为空，回退无 thinking 模式")
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code in (400, 422):
            logger.warning("Gemini thinking_config 不兼容（%s），自动回退无 thinking 模式", exc.response.status_code)
        else:
            err = _http_error_msg(exc)
            logger.exception("Gemini（thinking 模式）请求失败")
            return _make_result(False, model=model, thinking_level=thinking_level,
                                thinking_applied=False, prompt=prompt, text="", error=err)
    except Exception as exc:
        err = _exc_msg(exc)
        logger.exception("Gemini（thinking 模式）请求失败")
        return _make_result(False, model=model, thinking_level=thinking_level,
                            thinking_applied=False, prompt=prompt, text="", error=err)

    # 回退：不带 thinking
    try:
        text = _call_rest(model, api_key, prompt, with_thinking=False, thinking_level=thinking_level)
        if not text:
            return _make_result(False, model=model, thinking_level=thinking_level,
                                thinking_applied=False, prompt=prompt, text="",
                                error="Gemini 返回为空")
        return _make_result(True, model=model, thinking_level=thinking_level,
                            thinking_applied=False, prompt=prompt, text=text, error="")
    except Exception as exc:
        err = _exc_msg(exc)
        logger.exception("Gemini（回退无 thinking 模式）请求失败")
        return _make_result(False, model=model, thinking_level=thinking_level,
                            thinking_applied=False, prompt=prompt, text="", error=err)


def _http_error_msg(exc: requests.HTTPError) -> str:
    if exc.response is not None:
        try:
            detail = exc.response.json().get("error", {}).get("message", "")
        except Exception:
            detail = exc.response.text[:200]
        return f"Gemini API 错误 {exc.response.status_code}：{detail}"
    return f"Gemini HTTP 错误：{exc}"


def _exc_msg(exc: Exception) -> str:
    name = type(exc).__name__.lower()
    if "timeout" in name or "connect" in name:
        return f"Gemini 网络超时（{type(exc).__name__}），请检查网络连接"
    return f"Gemini 请求失败：{type(exc).__name__}"
