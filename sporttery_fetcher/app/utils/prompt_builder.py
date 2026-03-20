from __future__ import annotations

from decimal import Decimal, InvalidOperation

CH_NUM = {
    0: "零",
    1: "一",
    2: "二",
    3: "三",
    4: "四",
    5: "五",
    6: "六",
    7: "七",
    8: "八",
    9: "九",
    10: "十",
}


def _to_int_handicap(value: str | int | float | None) -> int | None:
    if value in (None, "", "nan"):
        return None
    try:
        n = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    try:
        return int(n)
    except Exception:
        return None


def handicap_to_text(handicap: str | int | float | None) -> str:
    v = _to_int_handicap(handicap)
    if v is None or v == 0:
        return "平手"

    abs_v = abs(v)
    num_txt = CH_NUM.get(abs_v, str(abs_v))

    if v < 0:
        return f"让{num_txt}球"
    return f"受让{num_txt}球"


def build_simple_prediction_prompt(league: str, home_team: str, away_team: str, handicap: str | int | float | None) -> str:
    league_text = str(league or "")
    home_text = str(home_team or "主队")
    away_text = str(away_team or "客队")
    handicap_text = handicap_to_text(handicap)
    return (
        f"你是一名足球分析师，针对{league_text}{home_text}vs{away_text}比赛，"
        f"分析并且预测胜负结果和主队{handicap_text}胜负结果以及两个最可能打出的比分。"
    )
