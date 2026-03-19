from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

APP_DIR = Path(__file__).resolve().parents[1]
ROOT = APP_DIR.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from components.charts import (
    render_daily_trend_chart,
    render_handicap_distribution,
    render_league_count_chart,
    render_odds_distribution,
)
from services.loader import available_date_options, get_data_context, get_latest_date, load_matches_by_date
from services.transforms import normalize_dataframe

st.set_page_config(page_title="统计分析", page_icon="📈", layout="wide")
st.title("📈 统计分析")

ctx = get_data_context(ROOT)
options = available_date_options(ctx)
if not options:
    st.warning("未找到 CSV 数据文件")
    st.stop()

latest = get_latest_date(ctx)
default_idx = options.index(latest) if latest in options else len(options) - 1
selected_date = st.sidebar.selectbox("选择日期文件", options=options, index=default_idx)

try:
    df = load_matches_by_date(selected_date, ctx)
except Exception as exc:
    st.error(f"读取文件失败：{exc}")
    st.stop()

df = normalize_dataframe(df)
if df.empty:
    st.info("当前文件无可分析数据")
    st.stop()

st.subheader("每日比赛数")
render_daily_trend_chart(df)

st.subheader("按联赛统计比赛数")
render_league_count_chart(df)

st.subheader("handicap 分布")
render_handicap_distribution(df)

st.subheader("胜平负奖金分布")
render_odds_distribution(df, ["spf_win", "spf_draw", "spf_lose"], "胜平负赔率（count/mean/min/max）")

st.subheader("让球胜平负奖金分布")
render_odds_distribution(df, ["rqspf_win", "rqspf_draw", "rqspf_lose"], "让球胜平负赔率（count/mean/min/max）")
