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
from services.gemini_parser import parse_gemini_output
from services.gemini_runner import run_gemini_prediction
from services.loader import get_data_context, load_matches_by_date
from services.prediction_store import save_prediction
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

    if result.get("ok"):
        raw_text = result.get("text", "")
        parsed = parse_gemini_output(raw_text)
        structured_result = {
            "gemini_prompt": result.get("prompt", prompt),
            "gemini_raw_text": raw_text,
            **parsed,
            "gemini_model": result.get("model"),
            "gemini_thinking_level": result.get("thinking_level"),
            "gemini_generated_at": result.get("generated_at"),
        }

        row = {
            "issue_date": selected_date,
            "match_no": match.get("match_no", ""),
            "league": match.get("league", ""),
            "home_team": match.get("home_team", ""),
            "away_team": match.get("away_team", ""),
            "kickoff_time": match.get("kickoff_time", ""),
            "handicap": match.get("handicap", ""),
            "raw_id": match.get("raw_id", ""),
            **structured_result,
        }

        try:
            saved_path = save_prediction(row, ROOT)
            result["saved_path"] = str(saved_path)
        except Exception:
            st.warning("预测已生成，但保存到本地文件失败，请稍后重试。")

        result["structured"] = structured_result

    st.session_state["gemini_last_result"] = result

result = st.session_state.get("gemini_last_result")
if result:
    if result.get("ok"):
        st.success("Gemini 返回成功")
        structured = result.get("structured", {})

        st.markdown("### 结构化推荐结果")
        c1, c2 = st.columns(2)
        c1.metric("胜平负主推", structured.get("gemini_match_main_pick") or "未识别")
        c1.metric("胜平负次推", structured.get("gemini_match_secondary_pick") or "无")
        c1.metric("让球胜平负主推", structured.get("gemini_handicap_main_pick") or "未识别")
        c1.metric("让球胜平负次推", structured.get("gemini_handicap_secondary_pick") or "无")

        c2.metric("比分1", structured.get("gemini_score_1") or "未识别")
        c2.metric("比分2", structured.get("gemini_score_2") or "未识别")
        c2.write(f"**模型名**：{structured.get('gemini_model') or '-'}")
        c2.write(f"**thinking level**：{structured.get('gemini_thinking_level') or '-'}")
        c2.write(f"**生成时间**：{structured.get('gemini_generated_at') or '-'}")

        st.write(f"**简短摘要**：{structured.get('gemini_summary') or '未生成'}")

        if result.get("saved_path"):
            st.caption(f"已保存至：{result['saved_path']}")

        with st.expander("查看发送的提示词", expanded=False):
            st.code(result.get("prompt", prompt), language="text")

        with st.expander("查看 Gemini 原始回复", expanded=False):
            st.write(result.get("text", ""))
    else:
        st.error(result.get("error", "Gemini 调用失败"))
