from __future__ import annotations

import streamlit as st
import pandas as pd


def render_match_detail(match: pd.Series) -> None:
    st.subheader("基础信息")
    c1, c2, c3 = st.columns(3)
    c1.write(f"**场次**：{match.get('match_no', '-')}")
    c2.write(f"**联赛**：{match.get('league', '-')}")
    c3.write(f"**开赛时间**：{match.get('kickoff_time', '-')}")

    c4, c5, c6 = st.columns(3)
    c4.write(f"**主队**：{match.get('home_team', '-')}")
    c5.write(f"**客队**：{match.get('away_team', '-')}")
    c6.write(f"**让球**：{match.get('handicap', '-')}")

    st.subheader("胜平负奖金")
    s1, s2, s3 = st.columns(3)
    s1.metric("胜", value=match.get("spf_win", "-"))
    s2.metric("平", value=match.get("spf_draw", "-"))
    s3.metric("负", value=match.get("spf_lose", "-"))

    st.subheader("让球胜平负奖金")
    r1, r2, r3 = st.columns(3)
    r1.metric("让胜", value=match.get("rqspf_win", "-"))
    r2.metric("让平", value=match.get("rqspf_draw", "-"))
    r3.metric("让负", value=match.get("rqspf_lose", "-"))

    st.subheader("原始抓取信息")
    st.write(f"**sell_status**：{match.get('sell_status', '-')}")
    st.write(f"**source_url**：{match.get('source_url', '-')}")
    st.write(f"**raw_id**：{match.get('raw_id', '-')}")
    st.write(f"**scrape_time**：{match.get('scrape_time', '-')}")
