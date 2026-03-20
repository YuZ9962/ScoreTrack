from __future__ import annotations

import pandas as pd
import streamlit as st


def render_league_count_chart(df: pd.DataFrame) -> None:
    if "league" not in df.columns or df.empty:
        st.info("暂无联赛数据可绘图")
        return
    data = df["league"].fillna("未知").value_counts().sort_values(ascending=False)
    st.bar_chart(data)


def render_daily_trend_chart(df: pd.DataFrame) -> None:
    if "issue_date" not in df.columns or df.empty:
        st.info("暂无日期数据可绘图")
        return
    data = df["issue_date"].astype(str).value_counts().sort_index()
    st.line_chart(data)


def render_handicap_distribution(df: pd.DataFrame) -> None:
    if "handicap" not in df.columns or df.empty:
        st.info("暂无让球数据可绘图")
        return
    data = df["handicap"].astype("string").fillna("空").value_counts().sort_index()
    st.bar_chart(data)


def render_odds_distribution(df: pd.DataFrame, cols: list[str], title: str) -> None:
    st.caption(title)
    available = [c for c in cols if c in df.columns]
    if not available:
        st.info("暂无赔率字段")
        return
    numeric = df[available].apply(pd.to_numeric, errors="coerce")
    summary = numeric.describe().T[["count", "mean", "min", "max"]]
    st.dataframe(summary, use_container_width=True)
