from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

APP_DIR = Path(__file__).resolve().parents[1]
ROOT = APP_DIR.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from components.recommendation_card import render_recommendation_card
from components.strategy_detail_panel import render_strategy_detail_panel
from components.strategy_selector import render_strategy_selector
from services.loader import get_data_context, load_recommendation_inputs
from services.recommendation_engine import generate_strategy_recommendations
from services.transforms import normalize_dataframe
from strategies.registry import get_default_strategy, get_strategy, list_strategies

st.set_page_config(page_title="推荐中心", page_icon="🧭", layout="wide")
st.title("🧭 推荐中心 / Strategy Recommendation Hub")

ctx = get_data_context(ROOT)
options = sorted([f.name.split("_matches.csv")[0] for f in ctx.files])
if not options:
    st.warning("暂无可用比赛数据")
    st.stop()

st.markdown("### 筛选条件")
filter_col1, filter_col2, filter_col3 = st.columns(3)
with filter_col1:
    selected_date = st.selectbox("日期", options=options, index=len(options) - 1)

matches_df, gemini_df, chatgpt_df = load_recommendation_inputs(selected_date, ctx, ROOT)
matches_df = normalize_dataframe(matches_df)

league_options = ["全部联赛", *sorted(matches_df["league"].fillna("").astype(str).unique().tolist())]
with filter_col2:
    selected_league = st.selectbox("联赛", league_options, index=0)

with filter_col3:
    view_filter = st.selectbox("推荐结果筛选", ["全部", "只看建议不跳过", "只看高置信度(>=75)", "只看高风险"])

if selected_league != "全部联赛":
    matches_df = matches_df[matches_df["league"].fillna("").astype(str) == selected_league].copy()
    if not gemini_df.empty:
        gemini_df = gemini_df[gemini_df["league"].fillna("").astype(str) == selected_league].copy()
    if not chatgpt_df.empty:
        chatgpt_df = chatgpt_df[chatgpt_df["league"].fillna("").astype(str) == selected_league].copy()

st.markdown("---")
st.markdown("### 策略选择区")
strategies = list_strategies()
default_strategy = get_default_strategy()
selected_strategy_id = render_strategy_selector(strategies, default_strategy.id)
selected_strategy = get_strategy(selected_strategy_id) or default_strategy

st.markdown("---")
with st.expander("查看当前策略说明", expanded=False):
    render_strategy_detail_panel(selected_strategy)

st.markdown("---")
st.markdown("### 比赛推荐列表")

rec_df = generate_strategy_recommendations(
    strategy_id=selected_strategy.id,
    matches_df=matches_df,
    gemini_df=gemini_df,
    chatgpt_df=chatgpt_df,
)

if rec_df.empty:
    st.info("当前筛选条件下暂无可推荐比赛。")
    st.stop()

if view_filter == "只看建议不跳过":
    rec_df = rec_df[rec_df["should_skip"] == False]
elif view_filter == "只看高置信度(>=75)":
    rec_df = rec_df[pd.to_numeric(rec_df["confidence_score"], errors="coerce").fillna(0) >= 75]
elif view_filter == "只看高风险":
    rec_df = rec_df[rec_df["risk_level"].astype(str) == "high"]

if rec_df.empty:
    st.info("筛选后暂无结果。")
    st.stop()

summary_col1, summary_col2, summary_col3, summary_col4 = st.columns(4)
summary_col1.metric("比赛数", len(rec_df))
summary_col2.metric("建议跳过", int(rec_df["should_skip"].sum()))
summary_col3.metric(
    "平均置信度",
    f"{pd.to_numeric(rec_df['confidence_score'], errors='coerce').fillna(0).mean():.1f}",
)
summary_col4.metric(
    "高风险占比",
    f"{(rec_df['risk_level'].astype(str).eq('high').mean() * 100):.1f}%",
)

for _, row in rec_df.sort_values(by=["confidence_score", "fit_score"], ascending=[False, False]).iterrows():
    render_recommendation_card(row.to_dict())
