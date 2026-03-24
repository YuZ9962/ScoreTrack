from __future__ import annotations

import re
from typing import Any

SCORE_PATTERN = re.compile(r"(?<!\d)(\d{1,2})\s*[-:：]\s*(\d{1,2})(?!\d)")
MATCH_PICK_VALUES = {"主胜", "平", "客胜", "无"}
HANDICAP_PICK_VALUES = {"让胜", "让平", "让负", "无"}



def _normalize_pick(value: str | None, allowed: set[str]) -> str | None:
    if not value:
        return None
    val = re.sub(r"\s+", "", str(value))
    if val in allowed:
        return val
    if "无" in val and "无" in allowed:
        return "无"
    for item in allowed:
        if item != "无" and item in val:
            return item
    return None



def _extract_score(value: str | None) -> str | None:
    if not value:
        return None
    m = SCORE_PATTERN.search(value)
    if not m:
        return None
    return f"{int(m.group(1))}-{int(m.group(2))}"



def _extract_structured_block(text: str) -> dict[str, str | None]:
    patterns = {
        "gemini_match_main_pick": r"胜平负主推\s*[：:]\s*(.+)",
        "gemini_match_secondary_pick": r"胜平负次推\s*[：:]\s*(.+)",
        "gemini_handicap_main_pick": r"让球胜平负主推\s*[：:]\s*(.+)",
        "gemini_handicap_secondary_pick": r"让球胜平负次推\s*[：:]\s*(.+)",
        "score_1_raw": r"比分1\s*[：:]\s*(.+)",
        "score_2_raw": r"比分2\s*[：:]\s*(.+)",
    }
    extracted: dict[str, str | None] = {}
    for key, pattern in patterns.items():
        m = re.search(pattern, text)
        extracted[key] = m.group(1).strip() if m else None
    return extracted



def _extract_first_match(text: str, patterns: list[tuple[str, str]]) -> str | None:
    for pattern, value in patterns:
        if re.search(pattern, text):
            return value
    return None



def _extract_scores_fallback(text: str) -> tuple[str | None, str | None]:
    scores: list[str] = []
    for home, away in SCORE_PATTERN.findall(text):
        score = f"{int(home)}-{int(away)}"
        if score not in scores:
            scores.append(score)
        if len(scores) >= 2:
            break
    return (scores[0] if scores else None, scores[1] if len(scores) > 1 else None)



def _extract_summary_from_analysis(raw_text: str, max_len: int = 140) -> str | None:
    text = (raw_text or "").strip()
    if not text:
        return None
    marker = "胜平负主推"
    analysis_text = text.split(marker)[0].strip() if marker in text else text
    analysis_text = re.sub(r"\s+", " ", analysis_text).strip()
    if not analysis_text:
        return None
    if len(analysis_text) <= max_len:
        return analysis_text
    parts = re.split(r"[。！？；]", analysis_text)
    summary = parts[0].strip() if parts else analysis_text[:max_len]
    if summary and len(summary) <= max_len:
        return summary
    return analysis_text[:max_len].rstrip() + "…"



def parse_gemini_output(raw_text: str) -> dict[str, Any]:
    text = (raw_text or "").strip()
    empty_result = {
        "gemini_match_main_pick": None,
        "gemini_match_secondary_pick": None,
        "gemini_handicap_main_pick": None,
        "gemini_handicap_secondary_pick": None,
        "gemini_score_1": None,
        "gemini_score_2": None,
        "gemini_summary": None,
    }
    if not text:
        return empty_result

    block = _extract_structured_block(text)
    match_main = _normalize_pick(block.get("gemini_match_main_pick"), MATCH_PICK_VALUES)
    match_secondary = _normalize_pick(block.get("gemini_match_secondary_pick"), MATCH_PICK_VALUES)
    handicap_main = _normalize_pick(block.get("gemini_handicap_main_pick"), HANDICAP_PICK_VALUES)
    handicap_secondary = _normalize_pick(block.get("gemini_handicap_secondary_pick"), HANDICAP_PICK_VALUES)
    score_1 = _extract_score(block.get("score_1_raw"))
    score_2 = _extract_score(block.get("score_2_raw"))

    if not match_main:
        match_patterns = [
            (r"(?:胜负结果预测|胜负方向|推荐|看好|倾向|预测|判断)[^。；\n]{0,12}主胜", "主胜"),
            (r"(?:胜负结果预测|胜负方向|推荐|看好|倾向|预测|判断)[^。；\n]{0,12}平", "平"),
            (r"(?:胜负结果预测|胜负方向|推荐|看好|倾向|预测|判断)[^。；\n]{0,12}客胜", "客胜"),
        ]
        match_main = _extract_first_match(text, match_patterns)

    if not handicap_main:
        handicap_patterns = [
            (r"(?:让球胜平负|让球|让平负|让胜平负)[^。；\n]{0,12}让胜", "让胜"),
            (r"(?:让球胜平负|让球|让平负|让胜平负)[^。；\n]{0,12}让平", "让平"),
            (r"(?:让球胜平负|让球|让平负|让胜平负)[^。；\n]{0,12}让负", "让负"),
            (r"受让胜", "让胜"),
            (r"受让平", "让平"),
            (r"受让负", "让负"),
        ]
        handicap_main = _extract_first_match(text, handicap_patterns)

    if not score_1 or not score_2:
        fb_score_1, fb_score_2 = _extract_scores_fallback(text)
        score_1 = score_1 or fb_score_1
        score_2 = score_2 or fb_score_2

    return {
        "gemini_match_main_pick": match_main,
        "gemini_match_secondary_pick": match_secondary,
        "gemini_handicap_main_pick": handicap_main,
        "gemini_handicap_secondary_pick": handicap_secondary,
        "gemini_score_1": score_1,
        "gemini_score_2": score_2,
        "gemini_summary": _extract_summary_from_analysis(text),
    }



def parse_manual_raw_text(raw_text: str) -> dict[str, Any]:
    text = (raw_text or "").strip()
    parsed = parse_gemini_output(text)

    scores = [s for s in [parsed.get("gemini_score_1"), parsed.get("gemini_score_2")] if s]
    score_prediction = " / ".join(scores) if scores else None

    analysis = parsed.get("gemini_summary")
    m = re.search(r"(?:结果分析与预测|分析|观点)[:：]\s*(.+)", text, flags=re.S)
    if m:
        analysis = m.group(1).strip()
    if not analysis:
        analysis = text

    return {
        "result_prediction": parsed.get("gemini_match_main_pick"),
        "handicap_prediction": parsed.get("gemini_handicap_main_pick"),
        "score_prediction": score_prediction,
        "analysis": analysis,
        "raw_text": text,
        "parse_warning": "" if parsed.get("gemini_match_main_pick") or parsed.get("gemini_handicap_main_pick") else "未能完整解析，请手动补充",
    }
