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
