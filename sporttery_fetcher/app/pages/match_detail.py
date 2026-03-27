from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

APP_DIR = Path(__file__).resolve().parents[1]
ROOT = APP_DIR.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from components.data_controls import render_date_file_selector, render_fetch_section
from components.detail_cards import render_match_detail
from services.loader import get_data_context, load_matches_by_date
from services.transforms import normalize_dataframe

st.set_page_config(page_title="比赛详情", page_icon="🔎", layout="wide")
st.title("🔎 比赛详情")

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

match = df.iloc[int(idx)]
render_match_detail(match)
