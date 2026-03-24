from __future__ import annotations

import pandas as pd


def fmt_dt(value) -> str:
    if pd.isna(value):
        return "-"
    try:
        return pd.to_datetime(value).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(value)


def fmt_num(value) -> str:
    if pd.isna(value):
        return "-"
    try:
        return f"{float(value):.2f}"
    except Exception:
        return str(value)


def fmt_pct(value) -> str:
    if pd.isna(value):
        return "0.0%"
    try:
        return f"{float(value):.1f}%"
    except Exception:
        return "0.0%"


def semantic_match_labels(home_team: str, away_team: str, single_match: bool) -> list[str]:
    home = str(home_team or "").strip()
    away = str(away_team or "").strip()
    if single_match and home and away:
        return [f"{home}胜", "平局", f"{away}胜"]
    return ["主队胜", "平局", "客队胜"]
