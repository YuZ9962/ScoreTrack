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
    if abs(total - 100.0) <= 0.3:
        return round(x, 2), round(y, 2), round(z, 2)
    scale = 100.0 / total
    return round(x * scale, 2), round(y * scale, 2), round(z * scale, 2)


def parse_chatgpt_output(raw_text: str) -> dict[str, Any]:
    text = (raw_text or "").strip()
    out = {
        "chatgpt_home_win_prob": None,
        "chatgpt_draw_prob": None,
        "chatgpt_away_win_prob": None,
        "chatgpt_handicap_win_prob": None,
        "chatgpt_handicap_draw_prob": None,
        "chatgpt_handicap_lose_prob": None,
        "chatgpt_score_1": None,
        "chatgpt_score_2": None,
        "chatgpt_score_3": None,
        "chatgpt_top_direction": None,
        "chatgpt_upset_probability_text": None,
        "chatgpt_summary": None,
    }
    if not text:
        return out

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
                "chatgpt_top_direction": str(data.get("top_direction") or "").strip() or None,
                "chatgpt_upset_probability_text": str(data.get("upset_probability_text") or "").strip() or None,
                "chatgpt_summary": str(data.get("summary") or "").strip() or None,
            }
        )

        scores = data.get("likely_scores") or []
        if isinstance(scores, list):
            cleaned = [str(s).strip() for s in scores if str(s).strip()]
            if cleaned:
                out["chatgpt_score_1"] = cleaned[0] if len(cleaned) > 0 else None
                out["chatgpt_score_2"] = cleaned[1] if len(cleaned) > 1 else None
                out["chatgpt_score_3"] = cleaned[2] if len(cleaned) > 2 else None

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

    return out
