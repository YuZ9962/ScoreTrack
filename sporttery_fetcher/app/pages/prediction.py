from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

APP_DIR = Path(__file__).resolve().parents[1]
ROOT = APP_DIR.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from components.data_controls import render_date_file_selector, render_fetch_section
from services.gemini_parser import parse_gemini_output
from services.gemini_runner import run_gemini_prediction
from services.loader import get_data_context, load_matches_by_date
from services.prediction_store import load_predictions, save_prediction
from services.transforms import normalize_dataframe, sort_by_match_no
from utils.prompt_builder import build_simple_prediction_prompt



def _match_label(row: pd.Series) -> str:
    return f"{row.get('match_no', '')} | {row.get('league', '')} | {row.get('home_team', '')} vs {row.get('away_team', '')}"



def _prediction_exists(pred_df: pd.DataFrame, issue_date: str, match_row: pd.Series) -> bool:
    if pred_df.empty:
        return False

    raw_id = str(match_row.get("raw_id", "") or "").strip()
    if raw_id:
        mask = (
            (pred_df["issue_date"].astype(str) == issue_date)
            & (pred_df["raw_id"].astype(str) == raw_id)
        )
        return bool(mask.any())

    mask = (
        (pred_df["issue_date"].astype(str) == issue_date)
        & (pred_df["match_no"].astype(str) == str(match_row.get("match_no", "")))
        & (pred_df["home_team"].astype(str) == str(match_row.get("home_team", "")))
        & (pred_df["away_team"].astype(str) == str(match_row.get("away_team", "")))
    )
    return bool(mask.any())



def _predict_single_match(match: pd.Series, issue_date: str) -> dict[str, object]:
    prompt = build_simple_prediction_prompt(
        league=str(match.get("league", "")),
        home_team=str(match.get("home_team", "")),
        away_team=str(match.get("away_team", "")),
        handicap=match.get("handicap", None),
    )

    result = run_gemini_prediction(prompt)
    if not result.get("ok"):
        return result

    raw_text = result.get("text", "")
    parsed = parse_gemini_output(raw_text)
    structured = {
        "gemini_prompt": result.get("prompt", prompt),
        "gemini_raw_text": raw_text,
        **parsed,
        "gemini_model": result.get("model"),
        "gemini_thinking_level": result.get("thinking_level"),
        "gemini_generated_at": result.get("generated_at"),
    }

    row = {
        "issue_date": issue_date,
        "match_no": match.get("match_no", ""),
        "league": match.get("league", ""),
        "home_team": match.get("home_team", ""),
        "away_team": match.get("away_team", ""),
        "kickoff_time": match.get("kickoff_time", ""),
        "handicap": match.get("handicap", ""),
        "raw_id": match.get("raw_id", ""),
        **structured,
    }
    save_prediction(row, ROOT)

    result["structured"] = structured
    return result



def _render_single_result(result: dict[str, object]) -> None:
    if not result:
        return
    if not result.get("ok"):
        st.error(str(result.get("error", "Gemini 调用失败")))
        return

    structured = result.get("structured", {}) or {}

    c1, c2 = st.columns(2)
    c1.metric("胜平负推荐", structured.get("gemini_match_main_pick") or "未识别")
    c1.write(f"次推：{structured.get('gemini_match_secondary_pick') or '无'}")

    c2.metric("让球胜平负推荐", structured.get("gemini_handicap_main_pick") or "未识别")
    c2.write(f"次推：{structured.get('gemini_handicap_secondary_pick') or '无'}")

    st.write(f"**推荐比分**：{structured.get('gemini_score_1') or '-'} / {structured.get('gemini_score_2') or '-'}")
    st.write(f"**简短摘要**：{structured.get('gemini_summary') or '未生成'}")

    with st.expander("查看发送的提示词", expanded=False):
        st.code(str(result.get("prompt", "")), language="text")

    with st.expander("查看 Gemini 原始回复", expanded=False):
        st.write(str(result.get("text", "")))


st.set_page_config(page_title="预测", page_icon="🔮", layout="wide")
st.title("🔮 预测")

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
    st.info("当前日期没有比赛数据")
    st.stop()

st.markdown("### 页面筛选区")
league_options = ["全部联赛", *sorted(df["league"].fillna("").astype(str).unique().tolist())]
selected_league = st.selectbox("联赛筛选", options=league_options, index=0)

filtered_df = df.copy()
if selected_league != "全部联赛":
    filtered_df = filtered_df[filtered_df["league"].fillna("").astype(str) == selected_league]

if filtered_df.empty:
    st.info("当前筛选下没有比赛")
    st.stop()

filtered_df = sort_by_match_no(filtered_df)
labels = [_match_label(row) for _, row in filtered_df.iterrows()]
selected_index = st.selectbox("场次选择", options=list(range(len(filtered_df))), format_func=lambda i: labels[i])
selected_match = filtered_df.iloc[int(selected_index)]

pred_df = load_predictions(ROOT)
only_missing = st.checkbox("仅预测尚未生成 Gemini 结果的比赛", value=False)

st.markdown("---")
col_a, col_b = st.columns(2)

with col_a:
    if st.button("预测当前场次", type="primary"):
        with st.spinner("正在预测当前场次..."):
            try:
                result = _predict_single_match(selected_match, selected_date)
            except Exception:
                result = {"ok": False, "error": "预测失败，请稍后重试"}
        st.session_state["prediction_single_result"] = result

with col_b:
    if st.button("一键预测当日全部场次"):
        target_df = filtered_df.copy()
        if only_missing and not pred_df.empty:
            target_df = target_df[
                ~target_df.apply(lambda r: _prediction_exists(pred_df, selected_date, r), axis=1)
            ]

        total = len(target_df)
        if total == 0:
            st.info("当前筛选下没有需要预测的比赛。")
        else:
            progress = st.progress(0)
            status = st.empty()
            success_count = 0
            failed_matches: list[str] = []

            for i, (_, row) in enumerate(target_df.iterrows(), start=1):
                status.info(f"正在预测第 {i} / {total} 场：{row.get('match_no', '')}")
                try:
                    result = _predict_single_match(row, selected_date)
                    if result.get("ok"):
                        success_count += 1
                    else:
                        failed_matches.append(str(row.get("match_no", "")))
                except Exception:
                    failed_matches.append(str(row.get("match_no", "")))

                progress.progress(i / total)

            status.success(f"已完成 {total} / {total} 场")
            st.success(f"批量预测完成：成功 {success_count} 场，失败 {len(failed_matches)} 场")
            if failed_matches:
                st.warning(f"失败场次：{', '.join(failed_matches)}")

single_result = st.session_state.get("prediction_single_result")
if single_result:
    st.markdown("### 当前场次预测结果")
    _render_single_result(single_result)

st.markdown("---")
st.markdown("### 当日已生成 Gemini 推荐")

latest_pred_df = load_predictions(ROOT)
if latest_pred_df.empty:
    st.info("当前暂无 Gemini 预测记录")
    st.stop()

show_df = latest_pred_df[latest_pred_df["issue_date"].astype(str) == selected_date].copy()
if selected_league != "全部联赛":
    show_df = show_df[show_df["league"].fillna("").astype(str) == selected_league]

if show_df.empty:
    st.info("当前日期/联赛暂无已生成预测")
    st.stop()

show_cols = [
    "issue_date",
    "match_no",
    "league",
    "home_team",
    "away_team",
    "handicap",
    "gemini_match_main_pick",
    "gemini_match_secondary_pick",
    "gemini_handicap_main_pick",
    "gemini_handicap_secondary_pick",
    "gemini_score_1",
    "gemini_score_2",
    "gemini_generated_at",
]

for col in show_cols:
    if col not in show_df.columns:
        show_df[col] = None

show_df = sort_by_match_no(show_df[show_cols])
st.dataframe(show_df, use_container_width=True, hide_index=True)
