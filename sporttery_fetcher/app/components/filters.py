from __future__ import annotations

import streamlit as st
import pandas as pd


def render_sidebar_filters(df: pd.DataFrame) -> dict:
    st.sidebar.subheader("筛选条件")
    leagues = sorted([x for x in df.get("league", pd.Series(dtype="string")).dropna().unique().tolist() if str(x).strip()])
    selected_leagues = st.sidebar.multiselect("联赛", leagues, default=[])
    keyword = st.sidebar.text_input("主队/客队关键词", value="")
    only_handicap = st.sidebar.checkbox("仅显示 handicap 非空", value=False)
    only_selling = st.sidebar.checkbox("仅显示开售比赛", value=False)

    sort_by = st.sidebar.selectbox("排序字段", ["开赛时间", "联赛", "场次编号"], index=0)
    asc = st.sidebar.toggle("升序", value=True)

    return {
        "leagues": selected_leagues,
        "keyword": keyword,
        "only_handicap": only_handicap,
        "only_selling": only_selling,
        "sort_by": sort_by,
        "ascending": asc,
    }
