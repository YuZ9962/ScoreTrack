from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

APP_DIR = Path(__file__).resolve().parents[1]
ROOT = APP_DIR.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from components.filters import render_sidebar_filters
from components.match_table import render_match_selector, render_match_table
from components.detail_cards import render_match_detail
from services.loader import available_date_options, get_data_context, get_latest_date, load_matches_by_date
from services.transforms import apply_filters, normalize_dataframe, sort_matches

st.set_page_config(page_title="比赛列表", page_icon="📋", layout="wide")
st.title("📋 比赛列表")

ctx = get_data_context(ROOT)
options = available_date_options(ctx)
if not options:
    st.warning("未找到 CSV 数据文件，请先抓取数据")
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
filters = render_sidebar_filters(df)
filtered = apply_filters(
    df,
    leagues=filters["leagues"],
    keyword=filters["keyword"],
    only_handicap_non_null=filters["only_handicap"],
    only_selling=filters["only_selling"],
)
filtered = sort_matches(filtered, filters["sort_by"], filters["ascending"])

st.caption(f"共 {len(filtered)} 场（原始 {len(df)} 场）")
if filtered.empty:
    st.info("当前筛选条件下无比赛数据")
    st.stop()

render_match_table(filtered)

st.markdown("---")
st.subheader("单场详情")
selected = render_match_selector(filtered)
if selected is not None:
    render_match_detail(selected)
