from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from openai import OpenAI


DEFAULT_MODEL = "gpt-5.4"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
        response = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": "你是专业足球比赛精算分析师。请严格按要求返回 JSON。"},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
        )
        text = (getattr(response, "output_text", None) or "").strip()
        if not text:
            text = str(response)
        return {
            "ok": True,
            "error": "",
            "model": model,
            "prompt": prompt,
            "text": text,
            "generated_at": _now_iso(),
        }
    except Exception:
        return {
            "ok": False,
            "error": "ChatGPT 请求失败，请检查 OPENAI_API_KEY 或模型配置",
            "model": model,
            "prompt": prompt,
            "text": "",
            "generated_at": _now_iso(),
        }
