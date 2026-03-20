from __future__ import annotations

import streamlit as st
import pandas as pd

TABLE_COLUMNS = [
    "match_no",
    "league",
    "home_team",
    "away_team",
    "kickoff_time",
    "handicap",
    "spf_win",
    "spf_draw",
    "spf_lose",
    "rqspf_win",
    "rqspf_draw",
    "rqspf_lose",
    "sell_status",
]


def render_match_table(df: pd.DataFrame) -> None:
    cols = [c for c in TABLE_COLUMNS if c in df.columns]
    st.dataframe(df[cols], use_container_width=True, hide_index=True)


def render_match_selector(df: pd.DataFrame) -> pd.Series | None:
    if df.empty:
        return None
    options = [f"{r.match_no} | {r.home_team} vs {r.away_team}" for r in df.itertuples()]
    idx = st.selectbox("选择比赛查看详情", options=list(range(len(options))), format_func=lambda i: options[i])
    return df.iloc[int(idx)]
