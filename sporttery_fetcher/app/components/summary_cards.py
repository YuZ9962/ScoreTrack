from __future__ import annotations

import streamlit as st
import pandas as pd

from utils.formatting import fmt_dt


def render_summary_cards(df: pd.DataFrame) -> None:
    total = len(df)
    handicap_count = int(df.get("handicap", pd.Series(dtype="object")).notna().sum()) if "handicap" in df.columns else 0
    selling_count = int(df.get("sell_status", pd.Series(dtype="object")).astype(str).str.contains("开售", na=False).sum()) if "sell_status" in df.columns else 0

    min_time = df["kickoff_time"].min() if "kickoff_time" in df.columns and len(df) else None
    max_time = df["kickoff_time"].max() if "kickoff_time" in df.columns and len(df) else None
    latest_scrape = df["scrape_time"].max() if "scrape_time" in df.columns and len(df) else None

    c1, c2, c3 = st.columns(3)
    c1.metric("总比赛数", total)
    c2.metric("handicap 非空场次", handicap_count)
    c3.metric("已开售场次", selling_count)

    c4, c5, c6 = st.columns(3)
    c4.metric("最早开赛", fmt_dt(min_time))
    c5.metric("最晚开赛", fmt_dt(max_time))
    c6.metric("最近抓取时间", fmt_dt(latest_scrape))
