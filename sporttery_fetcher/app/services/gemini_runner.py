from __future__ import annotations

import os
from typing import Any

import requests


def call_gemini_text(prompt: str, model: str = "gemini-1.5-flash") -> dict[str, Any]:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return {
            "ok": False,
            "text": "",
            "error": "未配置 GEMINI_API_KEY",
        }

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                ]
            }
        ]
    }

    try:
        resp = requests.post(url, json=payload, timeout=45)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        return {
            "ok": False,
            "text": "",
            "error": f"Gemini 请求失败: {exc}",
        }

    text = _extract_text(data)
    if not text:
        return {
            "ok": False,
            "text": "",
            "error": "Gemini 返回为空",
            "raw": data,
        }

    return {
        "ok": True,
        "text": text,
        "error": "",
        "raw": data,
    }


def _extract_text(data: dict[str, Any]) -> str:
    try:
        candidates = data.get("candidates", [])
        if not candidates:
            return ""
        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            return ""
        return "\n".join([str(p.get("text", "")) for p in parts if p.get("text")]).strip()
    except Exception:
        return ""
