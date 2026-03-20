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
from services.gemini_runner import run_gemini_prediction
from services.loader import get_data_context, load_matches_by_date
from services.transforms import normalize_dataframe
from utils.prompt_builder import build_simple_prediction_prompt

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

match = df.iloc[int(idx)]
render_match_detail(match)

st.markdown("---")
st.subheader("Gemini 预测")

prompt = build_simple_prediction_prompt(
    league=str(match.get("league", "")),
    home_team=str(match.get("home_team", "")),
    away_team=str(match.get("away_team", "")),
    handicap=match.get("handicap", None),
)

if st.button("生成 Gemini 预测", type="primary"):
    with st.spinner("正在调用 Gemini 生成预测..."):
        result = run_gemini_prediction(prompt)
    st.session_state["gemini_last_result"] = result

result = st.session_state.get("gemini_last_result")
if result:
    st.markdown("**发送给 Gemini 的提示词：**")
    st.code(result.get("prompt", prompt), language="text")

    if result.get("ok"):
        st.success("Gemini 返回成功")
        st.caption(f"模型：{result.get('model')} | thinking_level：{result.get('thinking_level')}")
        st.markdown("**Gemini 返回结果：**")
        st.write(result.get("text", ""))
    else:
        st.error(result.get("error", "Gemini 调用失败"))
