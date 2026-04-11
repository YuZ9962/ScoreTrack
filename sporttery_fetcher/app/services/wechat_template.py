from __future__ import annotations

import html as html_lib
import re
from pathlib import Path
from typing import Any

from .wechat_api import list_drafts

# ---- 总结占位符：模板中用那不勒斯文章的结尾段作为样本 ----
_SUMMARY_PLACEHOLDER = (
    "这场意甲焦点战，米兰不会轻易缴械，但在孔蒂体系加持下的那不勒斯，"
    "确实更值得信任。对于这场强强对话，金条更愿意把支持票投给主场作战的那不勒斯。"
)


def _fix_mojibake(s: str) -> str:
    """修正 requests 将 UTF-8 字节误读为 Latin-1 导致的乱码。"""
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return s


def _md_bold_to_html(text: str) -> str:
    """将 **text** 转换为 <strong>text</strong>，再做 HTML 转义。"""
    # 先转义，再处理 bold（避免转义破坏 <strong> 标签）
    # 策略：先提取 bold 段，转义其余文字，再拼回
    parts = re.split(r'\*\*(.+?)\*\*', text)
    out = []
    for i, part in enumerate(parts):
        if i % 2 == 1:  # 奇数位是 bold 内容
            out.append(f"<strong>{html_lib.escape(part)}</strong>")
        else:
            out.append(html_lib.escape(part))
    return "".join(out)


def _text_to_inline_html(text: str) -> str:
    """将纯文本（支持 **bold**）转为内联 HTML，换行变 <br>。"""
    result = _md_bold_to_html(text or "")
    return result.replace("\n", "<br>")


def get_template_html(base_dir: Path | None = None) -> dict[str, Any]:
    """从微信草稿列表拉取日常公众号模板（空标题草稿）的 HTML 内容。"""
    result = list_drafts(offset=0, count=20, base_dir=base_dir)
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error", "获取草稿列表失败")}

    for item in result.get("items", []):
        for article in item.get("content", {}).get("news_item", []):
            title_fixed = _fix_mojibake(article.get("title", ""))
            # 匹配：标题为空（模板）或标题含"日常公众号模板"
            if not title_fixed or "日常公众号模板" in title_fixed:
                content_fixed = _fix_mojibake(article.get("content", ""))
                return {"ok": True, "title": title_fixed, "content": content_fixed}

    return {"ok": False, "error": "未在草稿列表找到日常公众号模板（空标题草稿）"}


def render_template(template_html: str, fields: dict[str, str]) -> str:
    """
    将模板 HTML 中的占位符替换为实际字段内容。

    字段映射：
        前言        → 开场引用段
        主队名称    → 粗体队名
        主队分析    → 主队分析正文
        客队名称    → 粗体队名
        客队分析    → 客队分析正文
        主基调      → 比赛走势整体内容
        结果        → 推荐结论
        score1/2    → 比分
        总结        → 末段收尾
    """
    html = template_html

    # 1. 前言（顶部普通 span）
    html = html.replace(
        '<span leaf="">前言</span>',
        f'<span leaf="">{_text_to_inline_html(fields.get("前言", ""))}</span>',
        1,
    )

    # 2. 主队名称（粗体大字 span）
    html = html.replace(
        '<span textstyle="" style="font-size: 18px;font-weight: bold;">主队名称</span>',
        f'<span textstyle="" style="font-size: 18px;font-weight: bold;">'
        f'{html_lib.escape(fields.get("主队名称", ""))}</span>',
        1,
    )

    # 3. 主队分析（带完整 style 的 span，第一个）
    html = html.replace(
        '<span leaf="" style="-webkit-tap-highlight-color: rgba(0, 0, 0, 0);'
        'outline: 0px;visibility: visible;">主队分析</span>',
        f'<span leaf="" style="-webkit-tap-highlight-color: rgba(0, 0, 0, 0);'
        f'outline: 0px;visibility: visible;">'
        f'{_text_to_inline_html(fields.get("主队分析", ""))}</span>',
        1,
    )

    # 4. 客队名称（粗体大字 span，第二个）
    html = html.replace(
        '<span textstyle="" style="font-size: 18px;font-weight: bold;">客队名称</span>',
        f'<span textstyle="" style="font-size: 18px;font-weight: bold;">'
        f'{html_lib.escape(fields.get("客队名称", ""))}</span>',
        1,
    )

    # 5. 客队分析（带完整 style 的 span，第二个）
    html = html.replace(
        '<span leaf="" style="-webkit-tap-highlight-color: rgba(0, 0, 0, 0);'
        'outline: 0px;visibility: visible;">客队分析</span>',
        f'<span leaf="" style="-webkit-tap-highlight-color: rgba(0, 0, 0, 0);'
        f'outline: 0px;visibility: visible;">'
        f'{_text_to_inline_html(fields.get("客队分析", ""))}</span>',
        1,
    )

    # 6. 比赛走势主基调（粗体 span）
    html = html.replace(
        '<span leaf="">这场比赛的主基调</span>',
        f'<span leaf="">{_text_to_inline_html(fields.get("主基调", ""))}</span>',
        1,
    )

    # 7. 推荐（红色粗体 span）
    html = html.replace(
        '<span leaf="">推荐：结果</span>',
        f'<span leaf="">推荐：{html_lib.escape(fields.get("结果", ""))}</span>',
        1,
    )

    # 8. 比分（红色粗体 span）
    score1 = html_lib.escape(fields.get("score1", ""))
    score2 = html_lib.escape(fields.get("score2", ""))
    html = html.replace(
        '<span leaf="">比分：1:1，2:1</span>',
        f'<span leaf="">比分：{score1}，{score2}</span>',
        1,
    )

    # 9. 总结（模板中使用那不勒斯文章结尾段作为样本占位）
    html = html.replace(
        _SUMMARY_PLACEHOLDER,
        _text_to_inline_html(fields.get("总结", "")),
        1,
    )

    # 10. 移除末尾包含 <img> 的 section（图片来自其他文章素材库，API 提交会触发 40007）
    #     保留文字内容，图片可在微信后台手动补充
    html = re.sub(r'<section[^>]*>\s*<section[^>]*>\s*<span[^>]*><img[^>]+></span>\s*</section>\s*</section>', '', html)

    # 11. 压缩标签间空白，减少 content 字节数（微信 draft/add 有 ~20000 byte 限制）
    html = re.sub(r'>\s+<', '><', html)

    return html


def build_draft_from_template(
    article_title: str,
    fields: dict[str, str],
    base_dir: Path | None = None,
) -> dict[str, Any]:
    """
    完整流程：拉取模板 → 替换字段 → 返回 (title, content_html)。
    不直接上传，由调用方决定是否调 create_draft。
    """
    tmpl = get_template_html(base_dir)
    if not tmpl.get("ok"):
        return {"ok": False, "error": tmpl.get("error")}

    rendered = render_template(tmpl["content"], fields)
    return {"ok": True, "title": article_title, "content_html": rendered}
