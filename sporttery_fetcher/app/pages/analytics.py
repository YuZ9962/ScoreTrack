from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

APP_DIR = Path(__file__).resolve().parents[1]
ROOT = APP_DIR.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from components.data_controls import render_date_file_selector, render_fetch_section
from components.charts import (
    render_daily_trend_chart,
    render_handicap_distribution,
    render_league_count_chart,
    render_odds_distribution,
)
from services.loader import get_data_context, load_matches_by_date
from services.prediction_store import load_predictions
from services.transforms import normalize_dataframe

st.set_page_config(page_title="统计分析", page_icon="📈", layout="wide")
st.title("📈 统计分析")

ctx = get_data_context(ROOT)
render_fetch_section(ROOT)
selected_date = render_date_file_selector(ctx)
if not selected_date:
    st.warning("未找到 CSV 数据文件")
    st.stop()

try:
    df = load_matches_by_date(selected_date, ctx)
except Exception:
    st.error("读取文件失败，请检查数据文件是否存在且格式正确")
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

st.markdown("---")
st.subheader("Gemini 推荐分析")

pred_df = load_predictions(ROOT)
if pred_df.empty:
    st.info("暂无 Gemini 推荐数据。请先在比赛详情页生成预测。")
    st.stop()

pred_df["issue_date"] = pred_df["issue_date"].astype(str)
available_dates = sorted([d for d in pred_df["issue_date"].dropna().unique().tolist() if d.strip()])
if not available_dates:
    st.info("暂无可用日期数据。")
    st.stop()

selected_pred_date = st.selectbox("选择推荐日期", options=available_dates, index=len(available_dates) - 1)

filtered = pred_df[pred_df["issue_date"] == selected_pred_date].copy()
if filtered.empty:
    st.info("该日期暂无 Gemini 推荐数据。")
    st.stop()

league_options = sorted(filtered["league"].fillna("").astype(str).unique().tolist())
selected_leagues = st.multiselect("联赛筛选", options=league_options)
team_keyword = st.text_input("主队/客队关键词", placeholder="输入球队名关键字")

if selected_leagues:
    filtered = filtered[filtered["league"].astype(str).isin(selected_leagues)]

if team_keyword.strip():
    kw = team_keyword.strip().lower()
    home = filtered["home_team"].fillna("").astype(str).str.lower()
    away = filtered["away_team"].fillna("").astype(str).str.lower()
    filtered = filtered[home.str.contains(kw) | away.str.contains(kw)]

if filtered.empty:
    st.info("筛选后暂无 Gemini 推荐数据。")
    st.stop()

st.markdown("**统计概览**")
c1, c2, c3 = st.columns(3)
c1.metric("推荐总场次", len(filtered))
match_counts = filtered["gemini_match_result"].fillna("未识别").value_counts().to_dict()
handicap_counts = filtered["gemini_handicap_result"].fillna("未识别").value_counts().to_dict()
c2.write({"主胜": match_counts.get("主胜", 0), "平": match_counts.get("平", 0), "客胜": match_counts.get("客胜", 0)})
c3.write({"让胜": handicap_counts.get("让胜", 0), "让平": handicap_counts.get("让平", 0), "让负": handicap_counts.get("让负", 0)})

show_cols = [
    "issue_date",
    "match_no",
    "league",
    "home_team",
    "away_team",
    "kickoff_time",
    "handicap",
    "gemini_match_result",
    "gemini_handicap_result",
    "gemini_score_1",
    "gemini_score_2",
    "gemini_summary",
    "gemini_generated_at",
]

for col in show_cols:
    if col not in filtered.columns:
        filtered[col] = None

display_df = filtered[show_cols].copy()
if "kickoff_time" in display_df.columns:
    display_df["kickoff_time"] = pd.to_datetime(display_df["kickoff_time"], errors="coerce")
    display_df["kickoff_time"] = display_df["kickoff_time"].dt.strftime("%Y-%m-%d %H:%M:%S")

st.dataframe(display_df, use_container_width=True, hide_index=True)
