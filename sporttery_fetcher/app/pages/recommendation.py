from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

APP_DIR = Path(__file__).resolve().parents[1]
ROOT = APP_DIR.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from services.chatgpt_store import load_chatgpt_predictions
from services.loader import get_data_context, load_matches_by_date
from services.prediction_store import load_predictions
from services.transforms import normalize_dataframe

st.set_page_config(page_title="推荐", page_icon="🧭", layout="wide")
st.title("🧭 推荐")

ctx = get_data_context(ROOT)
options = sorted([f.name.split("_matches.csv")[0] for f in ctx.files])
if not options:
    st.warning("暂无可用比赛数据")
    st.stop()

selected_date = st.selectbox("日期", options=options, index=len(options) - 1)

matches_df = normalize_dataframe(load_matches_by_date(selected_date, ctx))
league_options = ["全部联赛", *sorted(matches_df["league"].fillna("").astype(str).unique().tolist())]
selected_league = st.selectbox("联赛", league_options, index=0)

if selected_league != "全部联赛":
    matches_df = matches_df[matches_df["league"].fillna("").astype(str) == selected_league]

st.info("本页面用于后续“购买方案推荐”扩展，当前为基础骨架版本。")

st.markdown("### 当前数据预览")
col1, col2 = st.columns(2)
with col1:
    st.markdown("**Gemini 推荐（预览）**")
    gdf = load_predictions(ROOT)
    gdf = gdf[gdf["issue_date"].astype(str) == selected_date]
    if selected_league != "全部联赛":
        gdf = gdf[gdf["league"].fillna("").astype(str) == selected_league]
    st.dataframe(gdf.head(20), use_container_width=True, hide_index=True)
with col2:
    st.markdown("**ChatGPT 推荐（预览）**")
    cdf = load_chatgpt_predictions(ROOT)
    cdf = cdf[cdf["issue_date"].astype(str) == selected_date]
    if selected_league != "全部联赛":
        cdf = cdf[cdf["league"].fillna("").astype(str) == selected_league]
    st.dataframe(cdf.head(20), use_container_width=True, hide_index=True)

st.markdown("---")
st.markdown("### 推荐方案（预留）")
pl1, pl2 = st.columns(2)
with pl1:
    st.markdown("- 单关推荐（预留）")
    st.markdown("- 稳健方案（预留）")
with pl2:
    st.markdown("- 串关推荐（预留）")
    st.markdown("- 激进方案（预留）")
