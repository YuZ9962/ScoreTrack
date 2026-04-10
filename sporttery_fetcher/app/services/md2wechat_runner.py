"""md2wechat CLI wrapper.

Bridges the project's WECHAT_APP_ID / WECHAT_APP_SECRET env vars to the
WECHAT_APPID / WECHAT_SECRET names that wechatpy (and the md2wechat CLI) expect,
then calls the CLI via subprocess.

Supported styles: academic_gray | festival | tech | announcement
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

STYLE_LABELS: dict[str, str] = {
    "academic_gray": "学术灰（默认）",
    "festival": "节日暖色系",
    "tech": "科技品蓝色系",
    "announcement": "重大通知橙色系",
}

DEFAULT_STYLE = "tech"


def _build_env(base_dir: Path | None = None) -> dict[str, str]:
    """Return an env dict with WECHAT_APPID / WECHAT_SECRET bridged from project vars."""
    env = os.environ.copy()

    # Bridge project credentials → wechatpy names
    app_id = (env.get("WECHAT_APP_ID") or "").strip()
    app_secret = (env.get("WECHAT_APP_SECRET") or "").strip()
    if app_id:
        env["WECHAT_APPID"] = app_id
    if app_secret:
        env["WECHAT_SECRET"] = app_secret

    return env


def convert_and_upload(
    markdown_text: str,
    *,
    title: str,
    author: str = "",
    summary: str = "",
    style: str = DEFAULT_STYLE,
    cover_path: str | None = None,
    base_dir: Path | None = None,
) -> dict[str, Any]:
    """Convert markdown to WeChat HTML and upload as draft via md2wechat CLI.

    Returns:
        {"ok": True, "raw": <cli json output>}
        {"ok": False, "error": "...", "raw": <cli output>}
    """
    if style not in STYLE_LABELS:
        style = DEFAULT_STYLE

    # Write markdown to a temp file
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write(markdown_text)
        tmp_path = f.name

    try:
        cmd = [
            "md2wechat",
            "--markdown", tmp_path,
            "--title", title[:64],
            "--style", style,
        ]
        if author:
            cmd += ["--author", author[:16]]
        if summary:
            cmd += ["--summary", summary[:120]]
        if cover_path:
            cmd += ["--cover", cover_path]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=_build_env(base_dir),
            timeout=60,
        )

        raw_output = result.stdout.strip() or result.stderr.strip()

        # CLI returns JSON
        try:
            data = json.loads(raw_output)
        except Exception:
            data = {"raw_text": raw_output}

        if result.returncode == 0 and data.get("success") is not False:
            return {"ok": True, "raw": data, "style": style}

        error_msg = data.get("error") or data.get("message") or raw_output or "md2wechat 调用失败"
        return {"ok": False, "error": str(error_msg), "code": data.get("code"), "raw": data}

    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "md2wechat 调用超时（60s）", "raw": {}}
    except FileNotFoundError:
        return {"ok": False, "error": "md2wechat 未安装或不在 PATH，请运行 pip install md2wechat", "raw": {}}
    except Exception as exc:
        return {"ok": False, "error": f"md2wechat 调用异常：{type(exc).__name__}: {exc}", "raw": {}}
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def is_available() -> bool:
    """Check whether the md2wechat CLI is on PATH."""
    try:
        r = subprocess.run(["md2wechat", "--help"], capture_output=True, timeout=10)
        return r.returncode in (0, 1)  # --help may exit 0 or 1
    except Exception:
        return False
