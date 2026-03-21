from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

APP_DIR = Path(__file__).resolve().parents[1]
ROOT = APP_DIR.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from components.data_controls import render_fetch_section
from services.loader import get_data_context, load_all_matches
from services.prediction_store import load_predictions
from services.transforms import (
    ensure_issue_date_columns,
    filter_by_time_and_league,
    normalize_dataframe,
    sort_by_match_no,
)


TIME_MODES = ["按日", "按月", "按年"]



def _time_options(df: pd.DataFrame, mode: str) -> list[str]:
    col_map = {"按日": "_date", "按月": "_month", "按年": "_year"}
    col = col_map[mode]
    if col not in df.columns:
        return []
    return sorted([str(v) for v in df[col].dropna().unique().tolist() if str(v).strip()])



def _collect_leagues(match_df: pd.DataFrame, pred_df: pd.DataFrame) -> list[str]:
    series_list = []
    if "league" in match_df.columns:
        series_list.append(match_df["league"].fillna("").astype(str))
    if "league" in pred_df.columns:
        series_list.append(pred_df["league"].fillna("").astype(str))

    if not series_list:
        return ["全部联赛"]

    merged = pd.concat(series_list, ignore_index=True)
    leagues = sorted([x for x in merged.unique().tolist() if x.strip()])
    return ["全部联赛", *leagues]


st.set_page_config(page_title="统计分析", page_icon="📈", layout="wide")
st.title("📈 统计分析")

ctx = get_data_context(ROOT)
render_fetch_section(ROOT)

match_df = load_all_matches(ctx)
match_df = normalize_dataframe(match_df)
match_df = ensure_issue_date_columns(match_df, source_col="issue_date")

pred_df = load_predictions(ROOT)
pred_df = ensure_issue_date_columns(pred_df, source_col="issue_date")

if match_df.empty and pred_df.empty:
    st.info("暂无可分析数据。请先抓取比赛数据并生成 Gemini 推荐。")
    st.stop()

st.markdown("### 分析筛选区")
col1, col2, col3 = st.columns(3)

with col1:
    time_mode = st.selectbox("时间维度", options=TIME_MODES, index=0)

base_time_df = match_df if not match_df.empty else pred_df
options = _time_options(base_time_df, time_mode)
if not options:
    st.info("当前没有可用时间选项。")
    st.stop()

with col2:
    time_value = st.selectbox("时间选择", options=options, index=len(options) - 1)

league_options = _collect_leagues(match_df, pred_df)
with col3:
    selected_league = st.selectbox("联赛筛选", options=league_options, index=0)

filtered_matches = filter_by_time_and_league(match_df, time_mode, time_value, selected_league)
filtered_preds = filter_by_time_and_league(pred_df, time_mode, time_value, selected_league)

st.markdown("---")
st.markdown("### 基础分析")
metric_col1, metric_col2 = st.columns(2)

label_map = {"按日": "每日比赛数", "按月": "每月比赛总数", "按年": "每年比赛总数"}
metric_col1.metric(label_map[time_mode], len(filtered_matches))

league_label = "全部联赛比赛数" if selected_league == "全部联赛" else f"{selected_league} 比赛数"
metric_col2.metric(league_label, len(filtered_matches))

st.markdown("---")
st.markdown("### Gemini 推荐分析")

if filtered_preds.empty:
    st.info("当前筛选条件下暂无 Gemini 推荐数据。")
    st.stop()

st.metric("推荐总场次", len(filtered_preds))

show_cols = [
    "issue_date",
    "match_no",
    "league",
    "home_team",
    "away_team",
    "kickoff_time",
    "handicap",
    "gemini_match_main_pick",
    "gemini_match_secondary_pick",
    "gemini_handicap_main_pick",
    "gemini_handicap_secondary_pick",
    "gemini_score_1",
    "gemini_score_2",
    "gemini_summary",
    "gemini_generated_at",
]

for col in show_cols:
    if col not in filtered_preds.columns:
        filtered_preds[col] = None

display_df = sort_by_match_no(filtered_preds[show_cols].copy())
if "kickoff_time" in display_df.columns:
    display_df["kickoff_time"] = pd.to_datetime(display_df["kickoff_time"], errors="coerce")
    display_df["kickoff_time"] = display_df["kickoff_time"].dt.strftime("%Y-%m-%d %H:%M:%S")

st.dataframe(display_df, use_container_width=True, hide_index=True)
