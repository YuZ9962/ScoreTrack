from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import streamlit as st

APP_DIR = Path(__file__).resolve().parents[1]
ROOT = APP_DIR.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from services.manual_entry_store import (
    load_existing_match,
    load_existing_prediction,
    load_existing_result,
    save_history_entry,
)

st.set_page_config(page_title="历史补录", page_icon="🗂️", layout="wide")
st.title("🗂️ 历史补录")
st.caption("手动补录历史比赛、Gemini 预测与赛果。补录后可直接参与 Analytics 统计。")


def _today() -> str:
    return datetime.now().date().isoformat()


with st.form("history_entry_form", clear_on_submit=False):
    st.subheader("1) 比赛基础信息")
    c1, c2, c3 = st.columns(3)
    with c1:
        issue_date = st.date_input("issue_date *", value=datetime.now().date()).isoformat()
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

    st.markdown("---")
    st.subheader("2) Gemini 预测信息")
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

    st.markdown("---")
    st.subheader("3) 比赛真实结果（可后补）")
    r1, r2, r3 = st.columns(3)
    with r1:
        full_time_score = st.text_input("full_time_score", value="", placeholder="如 2:1")
    with r2:
        result_match = st.selectbox("result_match", ["", "主胜", "平", "客胜", "未开奖"])
    with r3:
        result_handicap = st.selectbox("result_handicap", ["", "让胜", "让平", "让负", "未开奖"])

    save_clicked = st.form_submit_button("保存历史场次", type="primary")

if st.button("清空表单"):
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
