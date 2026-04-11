from __future__ import annotations

import os
import re
from typing import Any

from openai import OpenAI

from utils.common import now_iso as _now_iso
from utils.wechat_prompt_builder import build_wechat_article_prompt

DEFAULT_MODEL = "gpt-5.4"


def _split_title_body(text: str, home: str, away: str) -> tuple[str, str]:
    content = (text or "").strip()
    if not content:
        title = f"【金条玩足球】{home}VS{away}：赛前前瞻"
        body = "暂无生成内容。"
        return title, body

    first_line = content.splitlines()[0].strip()
    if first_line.startswith("【金条玩足球】"):
        return first_line, "\n".join(content.splitlines()[1:]).strip() or content

    title = f"【金条玩足球】{home}VS{away}：结构博弈前瞻"
    return title, content


def _s(v: Any, default: str = "") -> str:
    """Convert a value to str, treating NaN / None / 'nan' as empty."""
    if v is None:
        return default
    s = str(v).strip()
    return default if not s or s.lower() == "nan" else s


def _fallback_article(match: dict[str, Any], gemini: dict[str, Any]) -> str:
    home = _s(match.get("home_team"), "主队")
    away = _s(match.get("away_team"), "客队")
    summary = (
        _s(gemini.get("gemini_summary"))
        or _s(gemini.get("gemini_raw_text"))
        or "双方实力接近，临场因素将决定走势。"
    )
    rec = _s(gemini.get("gemini_match_main_pick")) or "主胜"
    s1 = _s(gemini.get("gemini_score_1")) or "1:0"
    s2 = _s(gemini.get("gemini_score_2")) or "2:1"

    return f"""【金条玩足球】{home}VS{away}：结构与节奏决定上限

“这场比赛的核心矛盾，在于主队的主动权能否转化为持续的压制效率。”

1. 基本面分析

**{home}**
近期表现以稳为主，攻防节奏更完整，比赛执行力相对更强。

**{away}**
客场韧性不差，但在高压节奏下容易出现阶段性被动。

2. 比赛走势

**第一，比赛开局更可能围绕中场控制展开。** 主队会优先争取节奏主导，客队则更倾向于降低对抗风险。

**第二，关键点在于转换阶段的效率。** 一旦主队在二次进攻端形成持续冲击，比赛重心会逐步倾向主队。

**第三，若上半场僵持，后程体能与替补质量将放大差距。** 这也是本场最值得关注的时间窗口。

3. 赛果预测

综合来看，这场比赛更倾向于：

推荐：{rec}
比分：{s1}，{s2}

这场球，更像是一场先拉扯、再分层的比赛。\n\n（素材摘要：{summary[:160]}）"""


def parse_article_fields(body: str) -> dict[str, str]:
    """Split article body into structured fields based on fixed section markers."""
    text = (body or "").strip()
    fields: dict[str, str] = {
        "前言": "",
        "主队名称": "",
        "主队分析": "",
        "客队名称": "",
        "客队分析": "",
        "主基调": "",
        "结果": "",
        "score1": "",
        "score2": "",
        "总结": "",
    }

    sec1 = re.search(r'1[\.、]\s*基本面分析', text)
    sec2 = re.search(r'2[\.、]\s*比赛走势', text)
    sec3 = re.search(r'3[\.、]\s*赛果预测', text)

    if not sec1:
        fields["前言"] = text
        return fields

    fields["前言"] = text[:sec1.start()].strip()

    sec2_start = sec2.start() if sec2 else len(text)
    between_12 = text[sec1.end():sec2_start].strip()

    bold_iter = list(re.finditer(r'\*\*(.+?)\*\*', between_12))
    if bold_iter:
        hm = bold_iter[0]
        fields["主队名称"] = hm.group(1).strip()
        if len(bold_iter) >= 2:
            am = bold_iter[1]
            fields["客队名称"] = am.group(1).strip()
            fields["主队分析"] = between_12[hm.end():am.start()].strip()
            fields["客队分析"] = between_12[am.end():].strip()
        else:
            fields["主队分析"] = between_12[hm.end():].strip()
    else:
        fields["主队分析"] = between_12

    if sec2:
        sec3_start = sec3.start() if sec3 else len(text)
        fields["主基调"] = text[sec2.end():sec3_start].strip()

    if sec3:
        sec3_body = text[sec3.end():].strip()
        rec = re.search(r'推荐[：:]\s*(.+)', sec3_body)
        if rec:
            fields["结果"] = rec.group(1).strip()
        score = re.search(r'比分[：:]\s*(\S+?)[,，]\s*(\S+)', sec3_body)
        if score:
            fields["score1"] = score.group(1).strip()
            fields["score2"] = score.group(2).strip()
            fields["总结"] = sec3_body[score.end():].strip()

    return fields


def generate_wechat_article(match: dict[str, Any], gemini: dict[str, Any]) -> dict[str, Any]:
    prompt = build_wechat_article_prompt(match=match, gemini=gemini)
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    model = (os.getenv("OPENAI_MODEL") or "").strip() or DEFAULT_MODEL

    if not api_key:
        article = _fallback_article(match, gemini)
        title, body = _split_title_body(article, str(match.get("home_team", "")), str(match.get("away_team", "")))
        return {
            "ok": True,
            "article_title": title,
            "article_body": body,
            "article_fields": parse_article_fields(body),
            "source_model": "fallback_template",
            "generated_at": _now_iso(),
            "prompt": prompt,
        }

    try:
        client = OpenAI(api_key=api_key)
        resp = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": "你是资深足球公众号主编。"},
                {"role": "user", "content": prompt},
            ],
        )
        text = (getattr(resp, "output_text", None) or "").strip() or str(resp)
        title, body = _split_title_body(text, str(match.get("home_team", "")), str(match.get("away_team", "")))
        return {
            "ok": True,
            "article_title": title,
            "article_body": body,
            "article_fields": parse_article_fields(body),
            "source_model": model,
            "generated_at": _now_iso(),
            "prompt": prompt,
        }
    except Exception:
        article = _fallback_article(match, gemini)
        title, body = _split_title_body(article, str(match.get("home_team", "")), str(match.get("away_team", "")))
        return {
            "ok": True,
            "article_title": title,
            "article_body": body,
            "article_fields": parse_article_fields(body),
            "source_model": "fallback_template_on_error",
            "generated_at": _now_iso(),
            "prompt": prompt,
        }
