from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

APP_DIR = Path(__file__).resolve().parents[1]
ROOT = APP_DIR.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from components.data_controls import render_date_file_selector, render_fetch_section
from services.chatgpt_parser import parse_chatgpt_output
from services.chatgpt_runner import run_chatgpt_prediction
from services.chatgpt_store import delete_chatgpt_predictions, load_chatgpt_predictions, save_chatgpt_prediction
from services.gemini_parser import parse_gemini_output, parse_manual_raw_text
from services.gemini_runner import run_gemini_prediction
from services.loader import get_data_context, load_matches_by_date
from services.prediction_store import delete_predictions, load_predictions, save_prediction
from services.transforms import normalize_dataframe, sort_by_match_no
from utils.chatgpt_prompt_builder import build_chatgpt_probability_prompt
from utils.prompt_builder import build_simple_prediction_prompt

STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_MANUAL = "manual_filled"
STATUS_PENDING = "pending"

SOURCE_AUTO = "auto_gemini"
SOURCE_MANUAL_GEMINI = "manual_gemini"
SOURCE_MANUAL_USER = "manual_user"



def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()



def _match_label(row: pd.Series) -> str:
    return f"{row.get('match_no', '')} | {row.get('league', '')} | {row.get('home_team', '')} vs {row.get('away_team', '')}"



def _get_prediction_row(pred_df: pd.DataFrame, issue_date: str, match_row: pd.Series) -> pd.Series | None:
    if pred_df.empty:
        return None

    raw_id = str(match_row.get("raw_id", "") or "").strip()
    match_no = str(match_row.get("match_no", "") or "").strip()
    home_team = str(match_row.get("home_team", "") or "").strip()
    away_team = str(match_row.get("away_team", "") or "").strip()
    kickoff_date = str(match_row.get("kickoff_time", "") or "").strip()[:10]

    if raw_id and "raw_id" in pred_df.columns:
        m = pred_df[pred_df["raw_id"].astype(str) == raw_id]
        if not m.empty:
            return m.iloc[-1]

    if match_no:
        m = pred_df[pred_df["match_no"].astype(str) == match_no]
        if not m.empty:
            return m.iloc[-1]

    if match_no and home_team and away_team:
        m = pred_df[
            (pred_df["match_no"].astype(str) == match_no)
            & (pred_df["home_team"].astype(str) == home_team)
            & (pred_df["away_team"].astype(str) == away_team)
        ]
        if not m.empty:
            return m.iloc[-1]

    if home_team and away_team:
        m = pred_df[
            (pred_df["home_team"].astype(str) == home_team)
            & (pred_df["away_team"].astype(str) == away_team)
        ]
        if kickoff_date and "kickoff_time" in m.columns:
            m2 = m[m["kickoff_time"].astype(str).str[:10] == kickoff_date]
            if not m2.empty:
                return m2.iloc[-1]
        if not m.empty:
            return m.iloc[-1]

    return None



def _status_text(pred_row: pd.Series | None) -> str:
    if pred_row is None:
        return "未预测"
    status = str(pred_row.get("prediction_status", "") or "")
    source = str(pred_row.get("prediction_source", "") or "")
    if status == STATUS_MANUAL:
        return "手动补录"
    if status == STATUS_FAILED:
        return "预测失败"
    if status == STATUS_SUCCESS and source == SOURCE_AUTO:
        return "已自动预测"
    if status == STATUS_PENDING:
        return "未预测"
    return "已预测"



def _is_pending_or_failed(pred_row: pd.Series | None) -> bool:
    if pred_row is None:
        return True
    return str(pred_row.get("prediction_status", "")) in {"", STATUS_FAILED, STATUS_PENDING}


def _predict_single_chatgpt(match: pd.Series, issue_date: str) -> dict[str, object]:
    prompt = build_chatgpt_probability_prompt(
        league=str(match.get("league", "")),
        home_team=str(match.get("home_team", "")),
        away_team=str(match.get("away_team", "")),
        kickoff_time=str(match.get("kickoff_time", "")),
        handicap=str(match.get("handicap", "")),
        spf_win=str(match.get("spf_win", "--")),
        spf_draw=str(match.get("spf_draw", "--")),
        spf_lose=str(match.get("spf_lose", "--")),
        rqspf_win=str(match.get("rqspf_win", "--")),
        rqspf_draw=str(match.get("rqspf_draw", "--")),
        rqspf_lose=str(match.get("rqspf_lose", "--")),
    )
    result = run_chatgpt_prediction(prompt)
    base = {
        "issue_date": issue_date,
        "match_no": match.get("match_no", ""),
        "league": match.get("league", ""),
        "home_team": match.get("home_team", ""),
        "away_team": match.get("away_team", ""),
        "kickoff_time": match.get("kickoff_time", ""),
        "handicap": match.get("handicap", ""),
        "raw_id": match.get("raw_id", ""),
    }
    if not result.get("ok"):
        save_chatgpt_prediction(
            {
                **base,
                "chatgpt_prompt": prompt,
                "chatgpt_raw_text": "",
                "chatgpt_model": result.get("model"),
                "chatgpt_generated_at": result.get("generated_at"),
            },
            ROOT,
        )
        return result

    parsed = parse_chatgpt_output(str(result.get("text", "")))
    save_chatgpt_prediction(
        {
            **base,
            "chatgpt_prompt": prompt,
            "chatgpt_raw_text": result.get("text", ""),
            **parsed,
            "chatgpt_model": result.get("model"),
            "chatgpt_generated_at": result.get("generated_at"),
        },
        ROOT,
    )
    result["structured"] = parsed
    return result


def _render_chatgpt_result(result: dict[str, object]) -> None:
    if not result:
        return
    if not result.get("ok"):
        st.error(str(result.get("error", "ChatGPT 调用失败")))
        return
    s = result.get("structured", {}) or {}
    st.markdown("**比赛结果概率**")
    c1, c2, c3 = st.columns(3)
    c1.metric("主胜概率", f"{s.get('chatgpt_home_win_prob')}%" if s.get("chatgpt_home_win_prob") is not None else "-")
    c2.metric("平局概率", f"{s.get('chatgpt_draw_prob')}%" if s.get("chatgpt_draw_prob") is not None else "-")
    c3.metric("客胜概率", f"{s.get('chatgpt_away_win_prob')}%" if s.get("chatgpt_away_win_prob") is not None else "-")
    st.markdown("**让球结果概率**")
    h1, h2, h3 = st.columns(3)
    h1.metric("让胜概率", f"{s.get('chatgpt_handicap_win_prob')}%" if s.get("chatgpt_handicap_win_prob") is not None else "-")
    h2.metric("让平概率", f"{s.get('chatgpt_handicap_draw_prob')}%" if s.get("chatgpt_handicap_draw_prob") is not None else "-")
    h3.metric("让负概率", f"{s.get('chatgpt_handicap_lose_prob')}%" if s.get("chatgpt_handicap_lose_prob") is not None else "-")
    st.write(
        f"**最可能比分**：{s.get('chatgpt_score_1') or '-'} / {s.get('chatgpt_score_2') or '-'} / {s.get('chatgpt_score_3') or '-'}"
    )
    st.write(f"**最大概率方向**：{s.get('chatgpt_top_direction') or '-'}")
    st.write(f"**爆冷概率**：{s.get('chatgpt_upset_probability_text') or '-'}")
    st.write(f"**简短摘要**：{s.get('chatgpt_summary') or '-'}")
    with st.expander("查看 ChatGPT Prompt", expanded=False):
        st.code(str(result.get("prompt", "")), language="text")
    with st.expander("查看 ChatGPT 原始回复", expanded=False):
        st.write(str(result.get("text", "")))



def _predict_single_match(match: pd.Series, issue_date: str) -> dict[str, object]:
    prompt = build_simple_prediction_prompt(
        league=str(match.get("league", "")),
        home_team=str(match.get("home_team", "")),
        away_team=str(match.get("away_team", "")),
        handicap=match.get("handicap", None),
    )

    result = run_gemini_prediction(prompt)
    base_row = {
        "issue_date": issue_date,
        "match_no": match.get("match_no", ""),
        "league": match.get("league", ""),
        "home_team": match.get("home_team", ""),
        "away_team": match.get("away_team", ""),
        "kickoff_time": match.get("kickoff_time", ""),
        "handicap": match.get("handicap", ""),
        "raw_id": match.get("raw_id", ""),
        "prediction_source": SOURCE_AUTO,
        "is_manual": False,
    }

    if not result.get("ok"):
        save_prediction(
            {
                **base_row,
                "gemini_prompt": result.get("prompt", prompt),
                "gemini_raw_text": result.get("text", ""),
                "raw_text": result.get("text", ""),
                "gemini_generated_at": result.get("generated_at", _now_iso()),
                "prediction_status": STATUS_FAILED,
                "prediction_remark": result.get("error", "Gemini 请求失败"),
            },
            ROOT,
        )
        return result

    raw_text = result.get("text", "")
    parsed = parse_gemini_output(raw_text)
    structured = {
        "gemini_prompt": result.get("prompt", prompt),
        "gemini_raw_text": raw_text,
        "raw_text": raw_text,
        **parsed,
        "gemini_model": result.get("model"),
        "gemini_thinking_level": result.get("thinking_level"),
        "gemini_generated_at": result.get("generated_at"),
        "prediction_source": SOURCE_AUTO,
        "prediction_status": STATUS_SUCCESS,
        "is_manual": False,
        "prediction_remark": None,
    }

    save_prediction({**base_row, **structured}, ROOT)
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


@st.dialog("手动补录预测")
def render_manual_dialog(match_row: pd.Series, issue_date: str):
    st.caption(_match_label(match_row))

    st.markdown("**胜平负推荐**")
    c1, c2 = st.columns(2)
    with c1:
        main_pick = st.selectbox("胜平负主推", ["主胜", "平", "客胜"], key=f"manual_main_{match_row.name}")
    with c2:
        secondary_pick = st.selectbox("胜平负次推（选填）", ["无", "主胜", "平", "客胜"], index=0, key=f"manual_secondary_{match_row.name}")

    st.markdown("**让胜平负推荐**")
    c3, c4 = st.columns(2)
    with c3:
        handicap_pick = st.selectbox("让胜平负主推", ["让胜", "让平", "让负"], key=f"manual_hcap_{match_row.name}")
    with c4:
        handicap_secondary_pick = st.selectbox("让胜平负次推（选填）", ["无", "让胜", "让平", "让负"], index=0, key=f"manual_hcap_secondary_{match_row.name}")

    st.markdown("**推荐比分**")
    s1, s2 = st.columns(2)
    with s1:
        score_1_input = st.text_input("比分1", value="", placeholder="如：2-1", key=f"manual_score1_{match_row.name}")
    with s2:
        score_2_input = st.text_input("比分2", value="", placeholder="如：1-0", key=f"manual_score2_{match_row.name}")

    analysis = st.text_area("分析内容", value="", height=100, key=f"manual_analysis_{match_row.name}")
    source = st.selectbox("预测来源", [SOURCE_MANUAL_GEMINI, SOURCE_MANUAL_USER], index=0, key=f"manual_source_{match_row.name}")
    remark = st.text_input("备注（可选）", value="", key=f"manual_remark_{match_row.name}")

    raw_text = st.text_area("raw_gemini_text", value="", height=180, key=f"manual_raw_{match_row.name}")

    col1, col2, col3 = st.columns(3)
    if col1.button("解析原文", key=f"parse_raw_{match_row.name}"):
        parsed = parse_manual_raw_text(raw_text)
        if parsed.get("result_prediction"):
            st.session_state[f"manual_main_{match_row.name}"] = parsed["result_prediction"]
        if parsed.get("handicap_prediction"):
            st.session_state[f"manual_hcap_{match_row.name}"] = parsed["handicap_prediction"]
        if parsed.get("score_prediction"):
            scores = [s.strip() for s in str(parsed["score_prediction"]).split("/") if s.strip()]
            if scores:
                st.session_state[f"manual_score1_{match_row.name}"] = scores[0]
            if len(scores) > 1:
                st.session_state[f"manual_score2_{match_row.name}"] = scores[1]
        if parsed.get("analysis"):
            st.session_state[f"manual_analysis_{match_row.name}"] = parsed["analysis"]

        if parsed.get("parse_warning"):
            st.warning(parsed["parse_warning"])
        else:
            st.success("解析成功，已自动回填字段")

    if col2.button("保存", type="primary", key=f"save_manual_{match_row.name}"):
        if secondary_pick == main_pick:
            st.warning("胜平负主推和次推相同，已自动将次推设为无")
            secondary_pick = "无"
        if handicap_secondary_pick == handicap_pick:
            st.warning("让胜平负主推和次推相同，已自动将次推设为无")
            handicap_secondary_pick = "无"

        row = {
            "issue_date": issue_date,
            "match_no": match_row.get("match_no", ""),
            "league": match_row.get("league", ""),
            "home_team": match_row.get("home_team", ""),
            "away_team": match_row.get("away_team", ""),
            "kickoff_time": match_row.get("kickoff_time", ""),
            "handicap": match_row.get("handicap", ""),
            "raw_id": match_row.get("raw_id", ""),
            "gemini_prompt": None,
            "gemini_raw_text": raw_text,
            "raw_text": raw_text,
            "gemini_match_main_pick": main_pick,
            "gemini_match_secondary_pick": secondary_pick,
            "gemini_handicap_main_pick": handicap_pick,
            "gemini_handicap_secondary_pick": handicap_secondary_pick,
            "gemini_score_1": score_1_input or None,
            "gemini_score_2": score_2_input or None,
            "gemini_summary": analysis,
            "gemini_model": "manual_input",
            "gemini_thinking_level": None,
            "gemini_generated_at": _now_iso(),
            "prediction_source": source,
            "prediction_status": STATUS_MANUAL,
            "is_manual": True,
            "prediction_remark": remark,
        }
        try:
            save_prediction(row, ROOT)
            st.success("保存成功")
            st.rerun()
        except Exception:
            st.error("保存失败，请稍后重试")

    if col3.button("取消", key=f"cancel_manual_{match_row.name}"):
        st.rerun()


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

single_pred = _get_prediction_row(pred_df, selected_date, selected_match)
st.info(f"当前场次状态：{_status_text(single_pred)}")

st.markdown("---")
col_a, col_b, col_c, col_d = st.columns(4)

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
                target_df.apply(lambda r: _get_prediction_row(pred_df, selected_date, r) is None, axis=1)
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
                    save_prediction(
                        {
                            "issue_date": selected_date,
                            "match_no": row.get("match_no", ""),
                            "league": row.get("league", ""),
                            "home_team": row.get("home_team", ""),
                            "away_team": row.get("away_team", ""),
                            "kickoff_time": row.get("kickoff_time", ""),
                            "handicap": row.get("handicap", ""),
                            "raw_id": row.get("raw_id", ""),
                            "prediction_source": SOURCE_AUTO,
                            "prediction_status": STATUS_FAILED,
                            "is_manual": False,
                            "prediction_remark": "批量预测异常",
                            "gemini_generated_at": _now_iso(),
                        },
                        ROOT,
                    )
                    failed_matches.append(str(row.get("match_no", "")))

                progress.progress(i / total)

            status.success(f"已完成 {total} / {total} 场")
            st.success(f"批量预测完成：成功 {success_count} 场，失败 {len(failed_matches)} 场")
            if failed_matches:
                st.warning(f"失败场次：{', '.join(failed_matches)}")

with col_c:
    if st.button("生成 ChatGPT 预测"):
        with st.spinner("正在生成 ChatGPT 预测..."):
            try:
                chatgpt_result = _predict_single_chatgpt(selected_match, selected_date)
            except Exception:
                chatgpt_result = {"ok": False, "error": "ChatGPT 预测失败，请稍后重试"}
        st.session_state["prediction_chatgpt_single_result"] = chatgpt_result

with col_d:
    if st.button("一键生成当日全部 ChatGPT 预测"):
        target_df = filtered_df.copy()
        total = len(target_df)
        if total == 0:
            st.info("当前筛选下没有需要预测的比赛。")
        else:
            progress = st.progress(0)
            status = st.empty()
            success_count = 0
            failed = 0
            for i, (_, row) in enumerate(target_df.iterrows(), start=1):
                status.info(f"ChatGPT 预测第 {i}/{total} 场：{row.get('match_no', '')}")
                try:
                    r = _predict_single_chatgpt(row, selected_date)
                    if r.get("ok"):
                        success_count += 1
                    else:
                        failed += 1
                except Exception:
                    failed += 1
                progress.progress(i / total)
            status.success("ChatGPT 批量预测完成")
            st.success(f"ChatGPT 批量预测完成：成功 {success_count} 场，失败 {failed} 场")

single_result = st.session_state.get("prediction_single_result")
if single_result:
    st.markdown("### 当前场次预测结果")
    _render_single_result(single_result)

chatgpt_single_result = st.session_state.get("prediction_chatgpt_single_result")
if chatgpt_single_result:
    st.markdown("### 当前场次 ChatGPT 预测结果")
    _render_chatgpt_result(chatgpt_single_result)

st.markdown("---")
st.markdown("### 待补录场次")

latest_pred_df = load_predictions(ROOT)
pending_rows: list[pd.Series] = []
for _, r in filtered_df.iterrows():
    pred = _get_prediction_row(latest_pred_df, selected_date, r)
    if _is_pending_or_failed(pred):
        pending_rows.append(r)

if not pending_rows:
    st.success("当前筛选下无待补录场次")
else:
    st.caption(f"待补录 {len(pending_rows)} 场")
    for r in pending_rows:
        pred = _get_prediction_row(latest_pred_df, selected_date, r)
        with st.container(border=True):
            st.write(f"**{_match_label(r)}**")
            st.write(f"状态：{_status_text(pred)}")
            if st.button("手动补录预测", key=f"manual_btn_{r.get('match_no')}_{r.get('raw_id', '')}"):
                render_manual_dialog(r, selected_date)

st.markdown("---")
st.markdown("### 手动删除比赛场次")
delete_labels = [_match_label(row) for _, row in filtered_df.iterrows()]
delete_indices = st.multiselect(
    "选择要删除的比赛（可多选）",
    options=list(range(len(filtered_df))),
    format_func=lambda i: delete_labels[i],
)
confirm_delete = st.checkbox("我已确认删除以上比赛及其 Gemini/ChatGPT 预测记录", value=False)
if st.button("删除所选比赛", type="secondary"):
    if not delete_indices:
        st.warning("请先选择要删除的比赛")
    elif not confirm_delete:
        st.warning("请先勾选删除确认")
    else:
        to_delete = filtered_df.iloc[delete_indices].copy()
        keys = [
            {
                "raw_id": str(r.get("raw_id", "") or "").strip(),
                "match_no": str(r.get("match_no", "") or "").strip(),
                "home_team": str(r.get("home_team", "") or "").strip(),
                "away_team": str(r.get("away_team", "") or "").strip(),
            }
            for _, r in to_delete.iterrows()
        ]

        target_file = ctx.data_dir / f"{selected_date}_matches.csv"
        deleted_matches = 0
        if target_file.exists():
            src_df = pd.read_csv(target_file)
            keep_mask = pd.Series([True] * len(src_df))
            for k in keys:
                raw_id = k["raw_id"]
                if raw_id and "raw_id" in src_df.columns:
                    keep_mask &= src_df["raw_id"].astype(str) != raw_id
                else:
                    keep_mask &= ~(
                        (src_df["match_no"].astype(str) == k["match_no"])
                        & (src_df["home_team"].astype(str) == k["home_team"])
                        & (src_df["away_team"].astype(str) == k["away_team"])
                    )
            new_df = src_df[keep_mask].copy()
            deleted_matches = len(src_df) - len(new_df)
            new_df.to_csv(target_file, index=False, encoding="utf-8-sig")

        deleted_gemini = delete_predictions(keys, ROOT)
        deleted_chatgpt = delete_chatgpt_predictions(keys, ROOT)
        st.success(
            f"删除完成：比赛 {deleted_matches} 场，Gemini 预测 {deleted_gemini} 条，ChatGPT 预测 {deleted_chatgpt} 条"
        )
        st.rerun()

st.markdown("---")
st.markdown("### 当日已生成 Gemini 推荐")

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
    "prediction_source",
    "prediction_status",
    "gemini_generated_at",
]

for col in show_cols:
    if col not in show_df.columns:
        show_df[col] = None

show_df = sort_by_match_no(show_df[show_cols])
st.dataframe(show_df, use_container_width=True, hide_index=True)

st.markdown("---")
st.markdown("### 当日已生成 ChatGPT 概率预测")
chatgpt_df = load_chatgpt_predictions(ROOT)
if not chatgpt_df.empty:
    cshow = chatgpt_df[chatgpt_df["issue_date"].astype(str) == selected_date].copy()
    if selected_league != "全部联赛":
        cshow = cshow[cshow["league"].fillna("").astype(str) == selected_league]
    if not cshow.empty:
        cols = [
            "issue_date",
            "match_no",
            "league",
            "home_team",
            "away_team",
            "kickoff_time",
            "handicap",
            "chatgpt_home_win_prob",
            "chatgpt_draw_prob",
            "chatgpt_away_win_prob",
            "chatgpt_handicap_win_prob",
            "chatgpt_handicap_draw_prob",
            "chatgpt_handicap_lose_prob",
            "chatgpt_score_1",
            "chatgpt_score_2",
            "chatgpt_score_3",
            "chatgpt_top_direction",
            "chatgpt_upset_probability_text",
            "chatgpt_generated_at",
        ]
        for col in cols:
            if col not in cshow.columns:
                cshow[col] = None
        cshow = sort_by_match_no(cshow[cols])
        st.dataframe(cshow, use_container_width=True, hide_index=True)
    else:
        st.info("当前日期/联赛暂无 ChatGPT 预测")
else:
    st.info("暂无 ChatGPT 预测记录")
