from __future__ import annotations

import json
import re
from typing import Any


_SCORE_PATTERN = re.compile(r"(?<!\d)(\d{1,2}-\d{1,2})(?!\d)")


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    s = str(v).strip().replace("%", "")
    try:
        return float(s)
    except Exception:
        return None


def _norm_prob_triplet(a: Any, b: Any, c: Any) -> tuple[float | None, float | None, float | None]:
    x, y, z = _to_float(a), _to_float(b), _to_float(c)
    if x is None or y is None or z is None:
        return x, y, z
    total = x + y + z
    if total <= 0:
        return x, y, z
    if abs(total - 100.0) <= 0.5:
        return round(x, 2), round(y, 2), round(z, 2)
    scale = 100.0 / total
    return round(x * scale, 2), round(y * scale, 2), round(z * scale, 2)


def _extract_label_value(text: str, labels: list[str]) -> str | None:
    for label in labels:
        m = re.search(rf"{re.escape(label)}\s*[:：]\s*(.+)", text)
        if m:
            return m.group(1).strip()
    return None


def _extract_prob_block(text: str, title: str, keys: list[str]) -> dict[str, float | None]:
    out = {k: None for k in keys}
    pattern = rf"{re.escape(title)}[\s\S]*?(?=\n【|$)"
    m = re.search(pattern, text)
    if not m:
        return out
    block = m.group(0)
    for k in keys:
        m2 = re.search(rf"{re.escape(k)}\s*[:：]\s*([0-9]+(?:\.[0-9]+)?)%", block)
        if m2:
            out[k] = float(m2.group(1))
    return out


def _normalize_secondary(value: str | None) -> str:
    s = str(value or "").strip()
    if not s:
        return "无"
    if s.lower() in {"none", "null", "nan", "无"}:
        return "无"
    return s


def _normalize_main(value: str | None) -> str | None:
    s = str(value or "").strip()
    if not s or s.lower() in {"none", "null", "nan"}:
        return None
    return s


def parse_chatgpt_output(raw_text: str) -> dict[str, Any]:
    text = (raw_text or "").strip()
    out = {
        "chatgpt_home_win_prob": None,
        "chatgpt_draw_prob": None,
        "chatgpt_away_win_prob": None,
        "chatgpt_handicap_win_prob": None,
        "chatgpt_handicap_draw_prob": None,
        "chatgpt_handicap_lose_prob": None,
        "chatgpt_match_main_pick": None,
        "chatgpt_match_secondary_pick": "无",
        "chatgpt_handicap_main_pick": None,
        "chatgpt_handicap_secondary_pick": "无",
        "chatgpt_score_1": None,
        "chatgpt_score_2": None,
        "chatgpt_score_3": None,
        "chatgpt_top_direction": None,
        "chatgpt_upset_probability_text": None,
        "chatgpt_summary": None,
    }
    if not text:
        return out

    # 1) 优先提取固定尾部字段
    tail_match_main = _extract_label_value(text, ["胜平负主推", "胜平负主方向"])
    tail_match_secondary = _extract_label_value(text, ["胜平负次推"])
    tail_hcap_main = _extract_label_value(text, ["让球主推", "让球主方向"])
    tail_hcap_secondary = _extract_label_value(text, ["让球次推"])
    tail_s1 = _extract_label_value(text, ["比分1"])
    tail_s2 = _extract_label_value(text, ["比分2"])
    tail_s3 = _extract_label_value(text, ["比分3"])
    tail_max_dir = _extract_label_value(text, ["最大概率方向", "胜平负主方向", "让球主方向"])
    tail_upset_def = _extract_label_value(text, ["爆冷方向定义"])
    tail_upset_prob = _extract_label_value(text, ["爆冷概率数值"])

    out["chatgpt_match_main_pick"] = _normalize_main(tail_match_main)
    out["chatgpt_match_secondary_pick"] = _normalize_secondary(tail_match_secondary)
    out["chatgpt_handicap_main_pick"] = _normalize_main(tail_hcap_main)
    out["chatgpt_handicap_secondary_pick"] = _normalize_secondary(tail_hcap_secondary)
    out["chatgpt_top_direction"] = _normalize_main(tail_max_dir)

    if tail_s1:
        m = _SCORE_PATTERN.search(tail_s1)
        out["chatgpt_score_1"] = m.group(1) if m else None
    if tail_s2:
        m = _SCORE_PATTERN.search(tail_s2)
        out["chatgpt_score_2"] = m.group(1) if m else None
    if tail_s3:
        m = _SCORE_PATTERN.search(tail_s3)
        out["chatgpt_score_3"] = m.group(1) if m else None

    if tail_upset_def or tail_upset_prob:
        upset = f"{tail_upset_def or ''} {tail_upset_prob or ''}".strip()
        out["chatgpt_upset_probability_text"] = upset

    # 2) 提取正文概率块
    mprob = _extract_prob_block(text, "【比赛结果概率】", ["主胜", "平局", "客胜"])
    hprob = _extract_prob_block(text, "【让球结果概率】", ["让胜", "让平", "让负"])

    h, d, a = _norm_prob_triplet(mprob["主胜"], mprob["平局"], mprob["客胜"])
    hw, hd, hl = _norm_prob_triplet(hprob["让胜"], hprob["让平"], hprob["让负"])

    out["chatgpt_home_win_prob"] = h
    out["chatgpt_draw_prob"] = d
    out["chatgpt_away_win_prob"] = a
    out["chatgpt_handicap_win_prob"] = hw
    out["chatgpt_handicap_draw_prob"] = hd
    out["chatgpt_handicap_lose_prob"] = hl

    # 3) 兼容旧 JSON 回复（回退）
    if all(out[k] is None for k in ["chatgpt_home_win_prob", "chatgpt_draw_prob", "chatgpt_away_win_prob"]):
        data: dict[str, Any] | None = None
        try:
            data = json.loads(text)
        except Exception:
            m = re.search(r"\{[\s\S]*\}", text)
            if m:
                try:
                    data = json.loads(m.group(0))
                except Exception:
                    data = None

        if data:
            mr = data.get("match_result_prob", {}) or {}
            hp = data.get("handicap_result_prob", {}) or {}
            h, d, a = _norm_prob_triplet(mr.get("home_win"), mr.get("draw"), mr.get("away_win"))
            hw, hd, hl = _norm_prob_triplet(hp.get("handicap_win"), hp.get("handicap_draw"), hp.get("handicap_lose"))
            out.update(
                {
                    "chatgpt_home_win_prob": h,
                    "chatgpt_draw_prob": d,
                    "chatgpt_away_win_prob": a,
                    "chatgpt_handicap_win_prob": hw,
                    "chatgpt_handicap_draw_prob": hd,
                    "chatgpt_handicap_lose_prob": hl,
                    "chatgpt_top_direction": out["chatgpt_top_direction"] or str(data.get("top_direction") or "").strip() or None,
                    "chatgpt_upset_probability_text": out["chatgpt_upset_probability_text"]
                    or str(data.get("upset_probability_text") or "").strip()
                    or None,
                }
            )
            scores = data.get("likely_scores") or []
            if isinstance(scores, list):
                cleaned = [str(s).strip() for s in scores if str(s).strip()]
                if cleaned:
                    out["chatgpt_score_1"] = out["chatgpt_score_1"] or (cleaned[0] if len(cleaned) > 0 else None)
                    out["chatgpt_score_2"] = out["chatgpt_score_2"] or (cleaned[1] if len(cleaned) > 1 else None)
                    out["chatgpt_score_3"] = out["chatgpt_score_3"] or (cleaned[2] if len(cleaned) > 2 else None)

    # 4) 比分最终回退
    if not out["chatgpt_score_1"]:
        scores = []
        for m in _SCORE_PATTERN.findall(text):
            if m not in scores:
                scores.append(m)
            if len(scores) >= 3:
                break
        if scores:
            out["chatgpt_score_1"] = scores[0]
            out["chatgpt_score_2"] = scores[1] if len(scores) > 1 else None
            out["chatgpt_score_3"] = scores[2] if len(scores) > 2 else None

    # 5) summary 保持简短
    summary = text.split("在上述分析结束后")[0].strip()
    summary = re.sub(r"\s+", " ", summary)
    out["chatgpt_summary"] = (summary[:120] + "…") if len(summary) > 121 else summary

    # 6) 主推缺失时从 top direction 回填
    if not out["chatgpt_match_main_pick"] and out["chatgpt_top_direction"]:
        out["chatgpt_match_main_pick"] = out["chatgpt_top_direction"]

    return out
