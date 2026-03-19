from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

APP_DIR = Path(__file__).resolve().parents[1]
ROOT = APP_DIR.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from components.detail_cards import render_match_detail
from services.loader import available_date_options, get_data_context, get_latest_date, load_matches_by_date
from services.transforms import normalize_dataframe

st.set_page_config(page_title="比赛详情", page_icon="🔎", layout="wide")
st.title("🔎 比赛详情")

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
    st.info("当前文件没有比赛数据")
    st.stop()

label_series = (
    df["match_no"].astype(str)
    + " | "
    + df["home_team"].astype(str)
    + " vs "
    + df["away_team"].astype(str)
)
idx = st.selectbox("选择比赛", options=list(range(len(df))), format_func=lambda i: label_series.iloc[i])

render_match_detail(df.iloc[int(idx)])
