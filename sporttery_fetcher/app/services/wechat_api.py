from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger("wechat_api")

TOKEN_URL = "https://api.weixin.qq.com/cgi-bin/token"
DRAFT_ADD_URL = "https://api.weixin.qq.com/cgi-bin/draft/add"
DRAFT_UPDATE_URL = "https://api.weixin.qq.com/cgi-bin/draft/update"
DRAFT_BATCHGET_URL = "https://api.weixin.qq.com/cgi-bin/draft/batchget"
MATERIAL_UPLOAD_URL = "https://api.weixin.qq.com/cgi-bin/material/add_material"
MATERIAL_BATCHGET_URL = "https://api.weixin.qq.com/cgi-bin/material/batchget_material"


def _token_cache_file(base_dir: Path | None = None) -> Path:
    root = base_dir or Path(__file__).resolve().parents[2]
    p = root / "data" / "articles" / "wechat_token_cache.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _now_ts() -> int:
    return int(time.time())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_cache(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _get_credentials() -> tuple[str, str]:
    app_id = (os.getenv("WECHAT_APP_ID") or "").strip()
    app_secret = (os.getenv("WECHAT_APP_SECRET") or "").strip()
    return app_id, app_secret


def has_wechat_config() -> bool:
    app_id, app_secret = _get_credentials()
    return bool(app_id and app_secret)


def get_access_token(base_dir: Path | None = None, force_refresh: bool = False) -> dict[str, Any]:
    app_id, app_secret = _get_credentials()
    if not app_id or not app_secret:
        return {"ok": False, "error": "未配置 WECHAT_APP_ID / WECHAT_APP_SECRET", "access_token": ""}

    cache_path = _token_cache_file(base_dir)
    cache = _read_cache(cache_path)
    if not force_refresh:
        token = str(cache.get("access_token", "") or "")
        exp_ts = int(cache.get("expires_at", 0) or 0)
        if token and exp_ts - _now_ts() > 300:
            return {"ok": True, "error": "", "access_token": token, "expires_at": exp_ts}

    try:
        resp = requests.get(
            TOKEN_URL,
            params={"grant_type": "client_credential", "appid": app_id, "secret": app_secret},
            timeout=15,
        )
        data = resp.json()
    except Exception as exc:
        logger.exception("获取微信 token 失败")
        return {"ok": False, "error": f"获取 token 失败: {type(exc).__name__}", "access_token": ""}

    token = str(data.get("access_token", "") or "")
    expires_in = int(data.get("expires_in", 0) or 0)
    if not token:
        err_msg = f"微信 token 接口返回异常 errcode={data.get('errcode')} errmsg={data.get('errmsg')}"
        logger.error(err_msg)
        return {"ok": False, "error": err_msg, "access_token": ""}

    expires_at = _now_ts() + max(0, expires_in)
    _write_cache(cache_path, {"access_token": token, "expires_at": expires_at, "updated_at": _now_iso()})
    return {"ok": True, "error": "", "access_token": token, "expires_at": expires_at}


def upload_image_material(file_path: str, base_dir: Path | None = None) -> dict[str, Any]:
    token_res = get_access_token(base_dir)
    if not token_res.get("ok"):
        return {"ok": False, "error": token_res.get("error", "token 获取失败")}

    token = token_res["access_token"]
    path = Path(file_path)
    if not path.exists():
        return {"ok": False, "error": f"文件不存在: {file_path}"}

    try:
        with path.open("rb") as f:
            resp = requests.post(
                MATERIAL_UPLOAD_URL,
                params={"access_token": token, "type": "image"},
                files={"media": f},
                timeout=25,
            )
        data = resp.json()
    except Exception as exc:
        logger.exception("上传微信封面图失败")
        return {"ok": False, "error": f"上传图片失败: {type(exc).__name__}"}

    if data.get("media_id"):
        return {"ok": True, "media_id": data.get("media_id"), "raw": data}

    return {
        "ok": False,
        "error": f"上传图片失败 errcode={data.get('errcode')} errmsg={data.get('errmsg')}",
        "raw": data,
    }


# 经实测，个人订阅号 draft/add 和 draft/update 的字段上限（UTF-8 字节数）
# 官方文档所标注的"32字/16字"适用于认证服务号，个人号更严
_TITLE_MAX_BYTES = 30   # ≈ 10 个汉字
_AUTHOR_MAX_BYTES = 6   # ≈ 2 个汉字
_DIGEST_MAX_BYTES = 120  # 40 汉字 × 3 bytes，个人订阅号实测上限


def _truncate_bytes(s: str, max_bytes: int) -> str:
    """按 UTF-8 字节数截断，不转 Unicode 转义，不截断多字节字符中间。"""
    encoded = s.encode("utf-8")
    if len(encoded) <= max_bytes:
        return s
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def _build_article_payload(
    *,
    title: str,
    content: str,
    author: str,
    digest: str,
    thumb_media_id: str | None,
) -> dict[str, Any]:
    safe_title = _truncate_bytes(title, _TITLE_MAX_BYTES)
    safe_author = _truncate_bytes(author, _AUTHOR_MAX_BYTES)
    # 若标题被截断，把完整标题存入 digest 供微信后台显示
    if not digest and len(safe_title) < len(title):
        digest = title
    safe_digest = _truncate_bytes(digest, _DIGEST_MAX_BYTES)
    article = {
        "title": safe_title,
        "author": safe_author,
        "content": content,
        "content_source_url": "",
        "need_open_comment": 0,
        "only_fans_can_comment": 0,
    }
    if safe_digest:
        article["digest"] = safe_digest
    if thumb_media_id:
        article["thumb_media_id"] = thumb_media_id
    return {"articles": [article]}


def get_default_thumb_media_id(base_dir: Path | None = None) -> str:
    """从永久素材图片列表取第一张的 media_id，用作草稿封面。"""
    token_res = get_access_token(base_dir)
    if not token_res.get("ok"):
        return ""
    token = token_res["access_token"]
    try:
        resp = requests.post(
            MATERIAL_BATCHGET_URL,
            params={"access_token": token},
            json={"type": "image", "offset": 0, "count": 1},
            timeout=15,
        )
        data = resp.json()
        items = data.get("item", [])
        if items:
            return str(items[0].get("media_id", "") or "")
    except Exception:
        logger.exception("获取默认封面 media_id 失败")
    return ""


def create_draft(
    *,
    title: str,
    content: str,
    author: str,
    digest: str = "",
    thumb_media_id: str | None = None,
    base_dir: Path | None = None,
) -> dict[str, Any]:
    token_res = get_access_token(base_dir)
    if not token_res.get("ok"):
        return {"ok": False, "error": token_res.get("error", "token 获取失败")}

    # thumb_media_id 是必填字段，若未提供则自动从素材库取第一张图片
    if not thumb_media_id:
        thumb_media_id = get_default_thumb_media_id(base_dir) or None

    token = token_res["access_token"]
    payload = _build_article_payload(
        title=title,
        content=content,
        author=author,
        digest=digest,
        thumb_media_id=thumb_media_id,
    )
    _art = payload["articles"][0]
    logger.info(
        "创建草稿 title_bytes=%d content_bytes=%d",
        len(_art["title"].encode("utf-8")),
        len(_art["content"].encode("utf-8")),
    )

    try:
        resp = requests.post(
            DRAFT_ADD_URL,
            params={"access_token": token},
            json=payload,
            timeout=25,
        )
        data = resp.json()
    except Exception as exc:
        logger.exception("创建微信草稿失败")
        return {"ok": False, "error": f"创建草稿失败: {type(exc).__name__}"}

    media_id = str(data.get("media_id", "") or "")
    if not media_id:
        return {
            "ok": False,
            "error": f"创建草稿失败 errcode={data.get('errcode')} errmsg={data.get('errmsg')}",
            "raw": data,
        }

    result: dict[str, Any] = {"ok": True, "draft_id": media_id, "raw": data, "uploaded_at": _now_iso()}

    # 若标题被截断，尝试用 draft/update 写入完整标题
    if len(title.encode("utf-8")) > _TITLE_MAX_BYTES:
        update_res = update_draft(
            media_id=media_id,
            title=title,
            content=content,
            author=author,
            digest=digest,
            thumb_media_id=thumb_media_id,
            token=token,
        )
        result["title_updated"] = update_res.get("ok", False)
        result["title_update_error"] = update_res.get("error", "")

    return result


def update_draft(
    *,
    media_id: str,
    title: str,
    content: str,
    author: str,
    digest: str = "",
    thumb_media_id: str | None = None,
    token: str = "",
    base_dir: Path | None = None,
) -> dict[str, Any]:
    """尝试用 draft/update 更新草稿标题（官方文档对 update 无明确字数限制）。"""
    if not token:
        token_res = get_access_token(base_dir)
        if not token_res.get("ok"):
            return {"ok": False, "error": token_res.get("error", "token 获取失败")}
        token = token_res["access_token"]

    article: dict[str, Any] = {
        "title": _truncate_bytes(title, _TITLE_MAX_BYTES),
        "author": _truncate_bytes(author, _AUTHOR_MAX_BYTES),
        "content": content,
        "content_source_url": "",
        "need_open_comment": 0,
        "only_fans_can_comment": 0,
    }
    if digest:
        article["digest"] = _truncate_bytes(digest, _DIGEST_MAX_BYTES)
    if thumb_media_id:
        article["thumb_media_id"] = thumb_media_id

    payload = {"media_id": media_id, "index": 0, "articles": article}
    try:
        resp = requests.post(
            DRAFT_UPDATE_URL,
            params={"access_token": token},
            json=payload,
            timeout=25,
        )
        data = resp.json()
    except Exception as exc:
        logger.exception("更新微信草稿失败")
        return {"ok": False, "error": f"更新草稿失败: {type(exc).__name__}"}

    if data.get("errcode") == 0 or not data.get("errcode"):
        return {"ok": True, "raw": data}
    return {
        "ok": False,
        "error": f"更新草稿失败 errcode={data.get('errcode')} errmsg={data.get('errmsg')}",
        "raw": data,
    }


def list_drafts(offset: int = 0, count: int = 20, base_dir: Path | None = None) -> dict[str, Any]:
    """获取草稿列表（含模板草稿）。"""
    token_res = get_access_token(base_dir)
    if not token_res.get("ok"):
        return {"ok": False, "error": token_res.get("error", "token 获取失败"), "items": []}

    token = token_res["access_token"]
    try:
        resp = requests.post(
            DRAFT_BATCHGET_URL,
            params={"access_token": token},
            json={"offset": offset, "count": count, "no_content": 0},
            timeout=25,
        )
        data = resp.json()
    except Exception as exc:
        logger.exception("获取草稿列表失败")
        return {"ok": False, "error": f"获取草稿列表失败: {type(exc).__name__}", "items": []}

    if data.get("errcode") and data.get("errcode") != 0:
        return {
            "ok": False,
            "error": f"errcode={data.get('errcode')} errmsg={data.get('errmsg')}",
            "items": [],
            "raw": data,
        }

    items = data.get("item", [])
    return {"ok": True, "items": items, "total": data.get("total_count", 0), "raw": data}


# 预留接口（后续发布能力）
def publish_draft(*args, **kwargs) -> dict[str, Any]:
    return {"ok": False, "error": "publish_draft 未实现（预留）"}
