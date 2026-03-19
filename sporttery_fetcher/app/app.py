from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from components.summary_cards import render_summary_cards
from services.loader import available_date_options, get_data_context, get_latest_date, load_matches_by_date
from services.transforms import normalize_dataframe

st.set_page_config(page_title="竞彩足球仪表盘", page_icon="⚽", layout="wide")
st.title("⚽ 竞彩足球数据工作台")
st.caption("首页总览（Dashboard）")

ctx = get_data_context(ROOT)
options = available_date_options(ctx)

if not options:
    st.warning("未找到 CSV 数据文件，请先运行抓取命令生成 data/processed/*.csv")
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

st.subheader(f"日期：{selected_date}")
render_summary_cards(df)

st.markdown("---")
st.subheader("按联赛分类比赛数")
if "league" in df.columns and not df.empty:
    league_count = df["league"].fillna("未知").value_counts().rename_axis("league").reset_index(name="count")
    st.dataframe(league_count, use_container_width=True, hide_index=True)
else:
    st.info("当前数据中无联赛字段")

st.markdown("---")
if "scrape_time" in df.columns and not df.empty:
    latest_scrape = pd.to_datetime(df["scrape_time"], errors="coerce").max()
    st.caption(f"最近数据抓取时间：{latest_scrape}")
