from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from components.data_controls import render_date_file_selector, render_fetch_section
from components.summary_cards import render_summary_cards
from services.loader import get_data_context, load_matches_by_date
from services.transforms import normalize_dataframe

st.set_page_config(page_title="ScoreTrack Dashboard", page_icon=":soccer:", layout="wide")
st.title("ScoreTrack 足球数据工作台")
st.caption("首页总览 Dashboard")

ctx = get_data_context(ROOT)
render_fetch_section(ROOT)
selected_date = render_date_file_selector(ctx)

if not selected_date:
    st.warning("未找到 CSV 数据文件，请先在左侧点击抓取并加载。")
    st.stop()
else:
    try:
        df = load_matches_by_date(selected_date, ctx)
    except Exception as exc:
        st.error(f"读取文件失败：{exc}")
        st.stop()
    else:
        df = normalize_dataframe(df)

        st.subheader(f"日期：{selected_date}")
        render_summary_cards(df)

        st.markdown("---")
        st.subheader("按联赛分类比赛数")
        if "league" in df.columns and not df.empty:
            league_count = (
                df["league"].fillna("未知").value_counts().rename_axis("league").reset_index(name="count")
            )
            st.dataframe(league_count, use_container_width=True, hide_index=True)
        else:
            st.info("当前数据中无联赛字段")

        st.markdown("---")
        if "scrape_time" in df.columns and not df.empty:
            latest_scrape = pd.to_datetime(df["scrape_time"], errors="coerce").max()
            st.caption(f"最近数据抓取时间：{latest_scrape}")
