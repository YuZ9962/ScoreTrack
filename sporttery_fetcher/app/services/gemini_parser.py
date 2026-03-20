from __future__ import annotations

import re
from typing import Any

SCORE_PATTERN = re.compile(r"(?<!\d)(\d{1,2})\s*[-:：]\s*(\d{1,2})(?!\d)")



def _extract_first_match(text: str, patterns: list[tuple[str, str]]) -> str | None:
    for pattern, value in patterns:
        if re.search(pattern, text):
            return value
    return None



def _extract_scores(text: str) -> tuple[str | None, str | None]:
    scores: list[str] = []
    for home, away in SCORE_PATTERN.findall(text):
        score = f"{int(home)}-{int(away)}"
        if score not in scores:
            scores.append(score)
        if len(scores) >= 2:
            break
    first = scores[0] if scores else None
    second = scores[1] if len(scores) > 1 else None
    return first, second



def _build_summary(text: str, max_len: int = 120) -> str | None:
    clean = re.sub(r"\s+", " ", (text or "")).strip()
    if not clean:
        return None
    if len(clean) <= max_len:
        return clean
    return clean[:max_len].rstrip() + "…"



def parse_gemini_output(raw_text: str) -> dict[str, Any]:
    text = (raw_text or "").strip()
    if not text:
        return {
            "gemini_match_result": None,
            "gemini_handicap_result": None,
            "gemini_score_1": None,
            "gemini_score_2": None,
            "gemini_summary": None,
        }

    match_patterns = [
        (r"(?:推荐|看好|倾向|预测|判断)[^。；\n]{0,12}主胜", "主胜"),
        (r"(?:推荐|看好|倾向|预测|判断)[^。；\n]{0,12}平", "平"),
        (r"(?:推荐|看好|倾向|预测|判断)[^。；\n]{0,12}客胜", "客胜"),
        (r"胜平负[^。；\n]{0,12}主胜", "主胜"),
        (r"胜平负[^。；\n]{0,12}客胜", "客胜"),
        (r"胜平负[^。；\n]{0,12}(?:平局|平)", "平"),
    ]
    handicap_patterns = [
        (r"(?:让球|让平负|让胜平负)[^。；\n]{0,12}让胜", "让胜"),
        (r"(?:让球|让平负|让胜平负)[^。；\n]{0,12}让平", "让平"),
        (r"(?:让球|让平负|让胜平负)[^。；\n]{0,12}让负", "让负"),
        (r"(?:推荐|看好|倾向|预测|判断)[^。；\n]{0,12}让胜", "让胜"),
        (r"(?:推荐|看好|倾向|预测|判断)[^。；\n]{0,12}让平", "让平"),
        (r"(?:推荐|看好|倾向|预测|判断)[^。；\n]{0,12}让负", "让负"),
    ]

    score_1, score_2 = _extract_scores(text)

    return {
        "gemini_match_result": _extract_first_match(text, match_patterns),
        "gemini_handicap_result": _extract_first_match(text, handicap_patterns),
        "gemini_score_1": score_1,
        "gemini_score_2": score_2,
        "gemini_summary": _build_summary(text),
    }
