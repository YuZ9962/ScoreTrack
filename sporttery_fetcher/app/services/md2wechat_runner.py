"""md2wechat CLI wrapper.

Bridges the project's WECHAT_APP_ID / WECHAT_APP_SECRET env vars to the
WECHAT_APPID / WECHAT_SECRET names that wechatpy (and the md2wechat CLI) expect,
then calls the CLI via subprocess.

Supported styles: academic_gray | festival | tech | announcement
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

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

    # Force UTF-8 I/O inside the md2wechat subprocess so it can print
    # Unicode characters (e.g. ✓) without crashing on GBK consoles.
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

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

    # 自动获取封面：md2wechat 上传草稿时封面为必填项
    # 优先级：调用方传入 → 按名搜索微信素材 → 微信素材第一张 URL → 本地默认封面图
    _default_cover_path = Path(__file__).resolve().parent.parent / "assets" / "default_cover.jpg"
    _cover_name = os.environ.get("WECHAT_DEFAULT_COVER_NAME", "test.jpg").strip()
    resolved_cover = cover_path
    if not resolved_cover:
        try:
            from services.wechat_api import get_media_id_by_name, get_default_cover_url
            if _cover_name:
                media_id = get_media_id_by_name(_cover_name, base_dir)
                if media_id:
                    # 有 media_id 则用 Python API 路径（跳过重新上传）
                    resolved_cover = f"__media_id__:{media_id}"
                    logger.info("md2wechat 使用素材库封面 name=%s media_id=%s...", _cover_name, media_id[:12])
            if not resolved_cover:
                url = get_default_cover_url(base_dir) or None
                if url:
                    resolved_cover = url
                    logger.debug("md2wechat 自动获取封面 URL: %s", url)
        except Exception:
            logger.debug("获取封面 URL 失败，跳过", exc_info=True)
    if not resolved_cover:
        if _default_cover_path.exists():
            resolved_cover = str(_default_cover_path)
            logger.info("md2wechat 使用本地默认封面: %s", resolved_cover)
        else:
            logger.warning("md2wechat 未能获取封面，上传可能失败")

    # 如果拿到了 media_id，走 Python API 路径跳过封面重新上传
    if resolved_cover and resolved_cover.startswith("__media_id__:"):
        thumb_media_id = resolved_cover[len("__media_id__:"):]
        return _pyapi_upload(
            markdown_text, tmp_path=tmp_path, title=title, author=author,
            summary=summary, style=style, thumb_media_id=thumb_media_id, base_dir=base_dir,
        )

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
        if resolved_cover:
            cmd += ["--cover", resolved_cover]

        logger.info(
            "md2wechat 开始上传 title=%r style=%s cover=%s",
            title[:64], style, resolved_cover or "(无封面)",
        )
        logger.debug("md2wechat cmd: %s", " ".join(cmd))

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_build_env(base_dir),
            timeout=60,
        )

        raw_output = (result.stdout or "").strip() or (result.stderr or "").strip()

        # CLI returns JSON (possibly with progress lines before it)
        try:
            data = json.loads(raw_output)
        except Exception:
            import re as _re
            _m = _re.search(r"\{.*\}", raw_output, _re.DOTALL)
            if _m:
                try:
                    data = json.loads(_m.group())
                except Exception:
                    data = {"raw_text": raw_output}
            else:
                data = {"raw_text": raw_output}

        if result.returncode == 0 and data.get("success") is not False:
            draft_id = data.get("media_id") or data.get("draft_id") or ""
            logger.info("md2wechat 上传成功 draft_id=%s style=%s", draft_id, style)
            return {"ok": True, "raw": data, "style": style}

        code = data.get("code") or ""
        error_msg = data.get("error") or data.get("message") or raw_output or "md2wechat 调用失败"
        if code and code not in str(error_msg):
            error_msg = f"[{code}] {error_msg}"
        logger.error(
            "md2wechat 上传失败 returncode=%s code=%s error=%r stdout=%r stderr=%r",
            result.returncode, code or "(无)", error_msg,
            (result.stdout or "")[:500], (result.stderr or "")[:500],
        )
        return {"ok": False, "error": str(error_msg), "code": code, "raw": data}

    except subprocess.TimeoutExpired:
        logger.error("md2wechat 调用超时（60s）title=%r", title[:64])
        return {"ok": False, "error": "md2wechat 调用超时（60s）", "raw": {}}
    except FileNotFoundError:
        logger.error("md2wechat 未安装或不在 PATH")
        return {"ok": False, "error": "md2wechat 未安装或不在 PATH，请运行 pip install md2wechat", "raw": {}}
    except Exception as exc:
        logger.error("md2wechat 调用异常 %s: %s", type(exc).__name__, exc, exc_info=True)
        return {"ok": False, "error": f"md2wechat 调用异常：{type(exc).__name__}: {exc}", "raw": {}}
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def _pyapi_upload(
    markdown_text: str,
    *,
    tmp_path: str,
    title: str,
    author: str,
    summary: str,
    style: str,
    thumb_media_id: str,
    base_dir: Path | None,
) -> dict[str, Any]:
    """md2wechat parser で HTML 変換し、プロジェクト固有の wechat_api でドラフト作成。

    wechatpy を一切使わないため、IP ホワイトリスト問題 (errcode=40164) を回避できる。
    プロジェクトの wechat_api はキャッシュ済みトークンを使用する。
    """
    import sys as _sys

    _skills = Path("C:/Users/A/anaconda3/Lib/site-packages/skills/md2wechat/scripts")
    _skills_str = str(_skills)

    # md2wechat の MarkdownParser だけ借用して HTML 変換（wechatpy 不使用）
    _sys.path.insert(0, _skills_str)
    try:
        from parsers import MarkdownParser  # type: ignore
        parse_result = MarkdownParser().parse(tmp_path, style=style)
        html_content = parse_result.content
    except Exception as exc:
        logger.error("md2wechat HTML 変換失敗: %s", exc, exc_info=True)
        return {"ok": False, "error": f"文章 HTML 转换失败: {exc}", "raw": {}}
    finally:
        try:
            _sys.path.remove(_skills_str)
        except ValueError:
            pass
        Path(tmp_path).unlink(missing_ok=True)

    logger.info(
        "md2wechat PyAPI 开始上传 title=%r style=%s media_id=%s...",
        title[:64], style, thumb_media_id[:12],
    )

    # プロジェクト独自の wechat_api を使用（キャッシュ token で IP whitelist 問題を回避）
    from services.wechat_api import create_draft as _create_draft
    result = _create_draft(
        title=title,
        content=html_content,
        author=author,
        digest=summary,
        thumb_media_id=thumb_media_id,
        base_dir=base_dir,
    )

    if result.get("ok"):
        draft_id = str(result.get("draft_id", ""))
        logger.info("md2wechat PyAPI 上传成功 draft_id=%s", draft_id)
        return {"ok": True, "raw": result, "style": style}

    error = result.get("error", "草稿创建失败")
    logger.error("md2wechat PyAPI 上传失败 error=%r", error)
    return {"ok": False, "error": str(error), "raw": result}


def is_available() -> bool:
    """Check whether the md2wechat CLI is on PATH."""
    try:
        r = subprocess.run(["md2wechat", "--help"], capture_output=True, timeout=10)
        return r.returncode in (0, 1)  # --help may exit 0 or 1
    except Exception:
        return False
