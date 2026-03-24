from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from openai import OpenAI


DEFAULT_MODEL = "gpt-5.4"
logger = logging.getLogger("chatgpt_runner")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_output_text(response: Any) -> str:
    text = (getattr(response, "output_text", None) or "").strip()
    if text:
        return text
    try:
        return str(response)
    except Exception:
        return ""


def run_chatgpt_prediction(prompt: str) -> dict[str, Any]:
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    model = (os.getenv("OPENAI_MODEL") or "").strip() or DEFAULT_MODEL
    if not api_key:
        return {
            "ok": False,
            "error": "未配置 OPENAI_API_KEY",
            "model": model,
            "prompt": prompt,
            "text": "",
            "generated_at": _now_iso(),
        }

    try:
        client = OpenAI(api_key=api_key)
        # 先优先保证可用性：不启用 JSON mode，直接获取文本回复。
        response = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": "你是专业足球比赛精算分析师。请按用户给定格式回答。"},
                {"role": "user", "content": prompt},
            ],
        )
        text = _extract_output_text(response)
        if not text:
            logger.error("ChatGPT 响应成功但文本为空 model=%s", model)
            return {
                "ok": False,
                "error": "ChatGPT 返回为空，请稍后重试",
                "model": model,
                "prompt": prompt,
                "text": "",
                "generated_at": _now_iso(),
            }
        return {
            "ok": True,
            "error": "",
            "model": model,
            "prompt": prompt,
            "text": text,
            "generated_at": _now_iso(),
        }
    except Exception as exc:
        err_type = type(exc).__name__
        err_msg = str(exc).strip() or "unknown error"
        logger.exception("ChatGPT 请求失败 model=%s err_type=%s err_msg=%s", model, err_type, err_msg)
        return {
            "ok": False,
            "error": f"ChatGPT 请求失败（{err_type}: {err_msg}）",
            "model": model,
            "prompt": prompt,
            "text": "",
            "generated_at": _now_iso(),
        }
