from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

APP_DIR = Path(__file__).resolve().parents[1]
ROOT = APP_DIR.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.manual_entry_store import (
    load_existing_match,
    load_existing_prediction,
    load_existing_result,
    save_history_entry,
    upsert_history_fetch_results,
)
from src.fetchers.zqsgkj_fetcher import fetch_zqsgkj_matches

st.set_page_config(page_title="历史补录", page_icon="🗂️", layout="wide")
st.title("🗂️ 历史补录")
st.caption("手动补录历史比赛、Gemini 预测、真实赛果；并支持按 issue_date 抓取官方历史赛果。")


def _today() -> str:
    return datetime.now().date().isoformat()


if "history_fetch_preview" not in st.session_state:
    st.session_state["history_fetch_preview"] = []
if "history_fetch_issue_date" not in st.session_state:
    st.session_state["history_fetch_issue_date"] = _today()

st.subheader("A. 按 issue_date 抓取历史赛果（官方 zqsgkj）")
st.caption("仅用于历史补录：按竞彩编号日 issue_date 抓取并预览，再手动确认写入。")

with st.form("history_fetch_form", clear_on_submit=False):
    fetch_issue_date = st.date_input("抓取 issue_date", value=datetime.now().date(), key="history_fetch_date").isoformat()
    fetch_clicked = st.form_submit_button("抓取历史赛果", type="primary")

if fetch_clicked:
    with st.spinner(f"正在抓取 {fetch_issue_date} 的历史赛果..."):
        try:
            records = fetch_zqsgkj_matches(fetch_issue_date)
            st.session_state["history_fetch_preview"] = records
            st.session_state["history_fetch_issue_date"] = fetch_issue_date
            if records:
                st.success(f"抓取成功：issue_date={fetch_issue_date}，共 {len(records)} 场")
            else:
                st.warning("抓取完成但无可用赛果，请检查 issue_date 或网络环境")
        except Exception as exc:
            st.session_state["history_fetch_preview"] = []
            st.error(f"抓取失败：{type(exc).__name__}")

preview = st.session_state.get("history_fetch_preview", [])
if preview:
    st.markdown("**抓取结果预览（确认后才写入）**")
    preview_df = pd.DataFrame(preview)
    st.dataframe(preview_df, use_container_width=True, hide_index=True)

    if st.button("写入历史结果文件", key="write_history_results"):
        stats = upsert_history_fetch_results(preview, ROOT)
        st.success(
            f"写入完成：总计 {stats['total']} 场，新增 {stats['inserted']} 场，覆盖更新 {stats['updated']} 场（data_source=history_fetch）"
        )
        st.info(
            f"自动补算：result_match {stats.get('auto_result_match', 0)} 场，result_handicap {stats.get('auto_result_handicap', 0)} 场"
        )

st.markdown("---")
st.subheader("B. 手动补录（比赛 + Gemini + 赛果）")

with st.form("history_entry_form", clear_on_submit=False):
    st.markdown("### 1) 比赛基础信息")
    c1, c2, c3 = st.columns(3)
    with c1:
        issue_date = st.date_input("issue_date *", value=datetime.now().date(), key="manual_issue_date").isoformat()
        match_no = st.text_input("match_no *", value="")
        league = st.text_input("league", value="")
    with c2:
        home_team = st.text_input("home_team *", value="")
        away_team = st.text_input("away_team *", value="")
        kickoff_time = st.text_input("kickoff_time", value=f"{_today()} 19:35", help="如 2026-03-01 19:35")
    with c3:
        handicap = st.text_input("handicap", value="")
        raw_id = st.text_input("raw_id（选填）", value="")

    st.caption("可选赔率补充")
    o1, o2, o3 = st.columns(3)
    with o1:
        spf_win = st.text_input("spf_win", value="")
        rqspf_win = st.text_input("rqspf_win", value="")
    with o2:
        spf_draw = st.text_input("spf_draw", value="")
        rqspf_draw = st.text_input("rqspf_draw", value="")
    with o3:
        spf_lose = st.text_input("spf_lose", value="")
        rqspf_lose = st.text_input("rqspf_lose", value="")

    st.markdown("### 2) Gemini 预测信息")
    g1, g2 = st.columns(2)
    with g1:
        gemini_match_main_pick = st.selectbox("gemini_match_main_pick *", ["主胜", "平", "客胜"])
        gemini_match_secondary_pick = st.selectbox("gemini_match_secondary_pick（选填）", ["", "无", "主胜", "平", "客胜"])
        gemini_handicap_main_pick = st.selectbox("gemini_handicap_main_pick *", ["让胜", "让平", "让负"])
        gemini_handicap_secondary_pick = st.selectbox(
            "gemini_handicap_secondary_pick（选填）", ["", "无", "让胜", "让平", "让负"]
        )
    with g2:
        gemini_score_1 = st.text_input("gemini_score_1", value="")
        gemini_score_2 = st.text_input("gemini_score_2", value="")
        gemini_summary = st.text_area("gemini_summary", value="", height=100)

    gemini_raw_text = st.text_area("gemini_raw_text（选填）", value="", height=120)
    gemini_prompt = st.text_area("gemini_prompt（选填）", value="", height=100)

    st.markdown("### 3) 比赛真实结果（可后补）")
    r1, r2, r3 = st.columns(3)
    with r1:
        full_time_score = st.text_input("full_time_score", value="", placeholder="如 2:1")
    with r2:
        result_match = st.selectbox("result_match", ["", "主胜", "平", "客胜", "未开奖"])
    with r3:
        result_handicap = st.selectbox("result_handicap", ["", "让胜", "让平", "让负", "未开奖"])

    save_clicked = st.form_submit_button("保存历史场次", type="primary")

if st.button("清空手动补录表单"):
    st.rerun()

if save_clicked:
    required_missing = [
        name
        for name, value in {
            "issue_date": issue_date,
            "match_no": match_no,
            "home_team": home_team,
            "away_team": away_team,
            "gemini_match_main_pick": gemini_match_main_pick,
            "gemini_handicap_main_pick": gemini_handicap_main_pick,
        }.items()
        if not str(value or "").strip()
    ]
    if required_missing:
        st.error(f"保存失败：必填字段为空 -> {', '.join(required_missing)}")
        st.stop()

    if gemini_match_secondary_pick == gemini_match_main_pick:
        gemini_match_secondary_pick = "无"
    if gemini_handicap_secondary_pick == gemini_handicap_main_pick:
        gemini_handicap_secondary_pick = "无"

    key_data = {
        "issue_date": issue_date,
        "match_no": match_no.strip(),
        "home_team": home_team.strip(),
        "away_team": away_team.strip(),
        "raw_id": raw_id.strip(),
    }
    exists_flags = {
        "match": load_existing_match(key_data, ROOT),
        "prediction": load_existing_prediction(key_data, ROOT),
        "result": load_existing_result(key_data, ROOT),
    }
    if any(exists_flags.values()):
        st.warning("该场次已存在，将执行覆盖更新")

    match_data = {
        **key_data,
        "league": league.strip(),
        "kickoff_time": kickoff_time.strip(),
        "handicap": handicap.strip(),
        "spf_win": spf_win.strip(),
        "spf_draw": spf_draw.strip(),
        "spf_lose": spf_lose.strip(),
        "rqspf_win": rqspf_win.strip(),
        "rqspf_draw": rqspf_draw.strip(),
        "rqspf_lose": rqspf_lose.strip(),
    }

    prediction_data = {
        **key_data,
        "league": league.strip(),
        "kickoff_time": kickoff_time.strip(),
        "handicap": handicap.strip(),
        "gemini_prompt": gemini_prompt.strip() or None,
        "gemini_raw_text": gemini_raw_text.strip(),
        "raw_text": gemini_raw_text.strip(),
        "gemini_match_main_pick": gemini_match_main_pick,
        "gemini_match_secondary_pick": gemini_match_secondary_pick or "无",
        "gemini_handicap_main_pick": gemini_handicap_main_pick,
        "gemini_handicap_secondary_pick": gemini_handicap_secondary_pick or "无",
        "gemini_score_1": gemini_score_1.strip() or None,
        "gemini_score_2": gemini_score_2.strip() or None,
        "gemini_summary": gemini_summary.strip(),
        "gemini_model": "manual_input",
        "gemini_thinking_level": None,
        "gemini_generated_at": datetime.utcnow().isoformat(),
        "prediction_status": "manual_filled",
        "prediction_remark": "history_entry",
    }

    has_result = bool(full_time_score.strip() or result_match.strip() or result_handicap.strip())
    result_data = {
        **key_data,
        "full_time_score": full_time_score.strip(),
        "result_match": result_match.strip() or "未开奖",
        "result_handicap": result_handicap.strip() or "未开奖",
    }

    outcome = save_history_entry(
        match_data=match_data,
        prediction_data=prediction_data,
        result_data=result_data,
        save_result=has_result,
        base_dir=ROOT,
    )
    if outcome.ok:
        st.success(outcome.message)
    else:
        st.error(outcome.message)
