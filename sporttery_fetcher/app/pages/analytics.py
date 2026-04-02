from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

APP_DIR = Path(__file__).resolve().parents[1]
ROOT = APP_DIR.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from components.charts import render_semantic_probability_pie
from components.data_controls import render_fetch_section
from services.loader import (
    get_data_context,
    get_or_rebuild_match_facts,
    load_all_matches,
    load_chatgpt_predictions,
    load_results,
)
from services.prediction_store import load_predictions
from services.result_evaluator import build_hit_summary, evaluate_chatgpt_predictions, evaluate_predictions
from services.transforms import (
    ensure_issue_date_columns,
    filter_by_time_and_league,
    normalize_dataframe,
    sort_by_match_no,
)
from src.fetchers.result_fetcher import fetch_and_save_results
from utils.formatting import semantic_match_labels

TIME_MODES = ["按日", "按月", "按年"]


def _run_daily_result_update(base_dir: Path, issue_date: str | None = None) -> tuple[bool, str]:
    """Analytics 日常更新链路：只做当前结果更新，不做历史补录流程。"""
    try:
        st.info("开始更新比赛结果（analytics 日常更新器）")
        result = fetch_and_save_results(base_dir, issue_date=issue_date)
    except Exception as exc:
        return False, f"更新比赛结果失败：{type(exc).__name__}"

    if not result.get("ok"):
        return False, (
            "未抓取到可写入赛果："
            f"issue_date={result.get('issue_date')} mode={result.get('mode')} parsed={result.get('parsed_rows')}"
        )

    msg = (
        "更新完成："
        f"issue_date={result.get('issue_date')} | "
        f"mode={result.get('mode')} | "
        f"parsed={result.get('parsed_rows')} | "
        f"clean={result.get('written_rows')} | "
        f"bad={result.get('bad_rows', 0)} | "
        f"matched_predictions={result.get('matched_predictions', 0)}"
    )
    return True, msg


def _time_options(df: pd.DataFrame, mode: str) -> list[str]:
    col_map = {"按日": "_date", "按月": "_month", "按年": "_year"}
    col = col_map[mode]
    if col not in df.columns:
        return []
    return sorted([str(v) for v in df[col].dropna().unique().tolist() if str(v).strip()])


def _collect_leagues(match_df: pd.DataFrame, pred_df: pd.DataFrame) -> list[str]:
    series_list = []
    if "league" in match_df.columns:
        series_list.append(match_df["league"].fillna("").astype(str))
    if "league" in pred_df.columns:
        series_list.append(pred_df["league"].fillna("").astype(str))
    if not series_list:
        return ["全部联赛"]
    merged = pd.concat(series_list, ignore_index=True)
    leagues = sorted([x for x in merged.unique().tolist() if x.strip()])
    return ["全部联赛", *leagues]


def _normalize_pick_text(value: object) -> str:
    text = str(value or "").strip()
    if not text or text.lower() in {"nan", "null", "none"}:
        return ""
    return text


def _join_main_secondary(main_pick: object, secondary_pick: object) -> str:
    main = _normalize_pick_text(main_pick)
    secondary = _normalize_pick_text(secondary_pick)
    if not main:
        return ""
    if not secondary or secondary == "无":
        return main
    return f"{main}/{secondary}"


def _join_scores(score_1: object, score_2: object) -> str:
    s1 = str(score_1 or "").strip()
    s2 = str(score_2 or "").strip()
    if s1 and s2:
        return f"{s1}/{s2}"
    return s1 or s2


def _build_cn_table(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["日期时间"] = pd.to_datetime(out.get("kickoff_time"), errors="coerce").dt.strftime("%Y-%m-%d %H:%M")
    out["比赛序号"] = out.get("match_no")
    out["联赛"] = out.get("league")
    out["主客队"] = out.get("home_team", "").astype(str) + " vs " + out.get("away_team", "").astype(str)
    out["让球"] = out.get("handicap")
    out["胜平负"] = out.apply(
        lambda r: _join_main_secondary(r.get("gemini_match_main_pick"), r.get("gemini_match_secondary_pick")), axis=1
    )
    out["让胜平负"] = out.apply(
        lambda r: _join_main_secondary(r.get("gemini_handicap_main_pick"), r.get("gemini_handicap_secondary_pick")), axis=1
    )
    out["推荐比分"] = out.apply(lambda r: _join_scores(r.get("gemini_score_1"), r.get("gemini_score_2")), axis=1)
    out["比赛实际比分"] = out.get("full_time_score")
    out["胜平负预测结果"] = out.get("gemini_match_hit") if "gemini_match_hit" in out.columns else out.get("match_hit_result")
    out["让胜平负预测结果"] = out.get("gemini_handicap_hit") if "gemini_handicap_hit" in out.columns else out.get("handicap_hit_result")
    out["数据来源"] = out.get("data_source", pd.Series(["auto"] * len(out))).fillna("auto")

    return out[
        [
            "日期时间",
            "比赛序号",
            "联赛",
            "主客队",
            "让球",
            "胜平负",
            "让胜平负",
            "推荐比分",
            "比赛实际比分",
            "胜平负预测结果",
            "让胜平负预测结果",
            "数据来源",
        ]
    ]


def _status_icon(value: object) -> str:
    text = str(value or "").strip()
    if text == "命中":
        return "✅"
    if text == "未命中":
        return "❌"
    return "⏳"


def _hit_summary_from_facts(df: pd.DataFrame, match_col: str, handicap_col: str) -> dict:
    """从事实表字段直接计算命中统计，复用 build_hit_summary 格式。"""
    total = len(df)
    match_ended = int((df[match_col] != "未开奖").sum()) if match_col in df.columns else 0
    handicap_ended = int((df[handicap_col] != "未开奖").sum()) if handicap_col in df.columns else 0
    match_hit = int((df.get(match_col, pd.Series([], dtype="string")) == "命中").sum())
    handicap_hit = int((df.get(handicap_col, pd.Series([], dtype="string")) == "命中").sum())

    match_rate = (
        f"{match_hit} / {match_ended}（{(match_hit / match_ended) * 100:.1f}%）"
        if match_ended > 0 else "0 / 0（0.0%）"
    )
    handicap_rate = (
        f"{handicap_hit} / {handicap_ended}（{(handicap_hit / handicap_ended) * 100:.1f}%）"
        if handicap_ended > 0 else "0 / 0（0.0%）"
    )
    return {"total": total, "ended": match_ended, "match_rate": match_rate, "handicap_rate": handicap_rate}


# ─────────────────────────────────────────────────────────────────────────────
# 页面入口
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(page_title="统计分析", page_icon="📈", layout="wide")
st.title("📈 统计分析")

ctx = get_data_context(ROOT)
render_fetch_section(ROOT)

# ── 优先加载事实表 ──────────────────────────────────────────────────────────
facts_df = get_or_rebuild_match_facts(ROOT)
use_facts = not facts_df.empty

if use_facts:
    facts_df = ensure_issue_date_columns(facts_df, source_col="issue_date")
    st.caption("✅ 正在使用统一事实表（match_facts.csv）")
else:
    st.caption("⚠️ 事实表为空，回退旧数据路径")

# ── 回退路径（事实表不可用时）──────────────────────────────────────────────
match_df = load_all_matches(ctx) if not use_facts else facts_df
match_df = normalize_dataframe(match_df)
match_df = ensure_issue_date_columns(match_df, source_col="issue_date")

pred_df = (
    facts_df[facts_df["gemini_prediction_status"].notna() & (facts_df["gemini_prediction_status"] != "")]
    if use_facts
    else load_predictions(ROOT)
)
pred_df = ensure_issue_date_columns(pred_df, source_col="issue_date")

if match_df.empty and pred_df.empty:
    st.info("暂无可分析数据。请先抓取比赛数据并生成 Gemini 推荐。")
    st.stop()

st.markdown("### 分析筛选区")
col1, col2, col3 = st.columns(3)

with col1:
    time_mode = st.selectbox("时间维度", options=TIME_MODES, index=0)

base_time_df = match_df if not match_df.empty else pred_df
options = _time_options(base_time_df, time_mode)
if not options:
    st.info("当前没有可用时间选项。")
    st.stop()

with col2:
    time_value = st.selectbox("时间选择", options=options, index=len(options) - 1)

league_options = _collect_leagues(match_df, pred_df)
with col3:
    selected_league = st.selectbox("联赛筛选", options=league_options, index=0)

filtered_matches = filter_by_time_and_league(match_df, time_mode, time_value, selected_league)

issue_date_for_update = time_value if time_mode == "按日" else None
if st.button("更新比赛结果", type="primary"):
    label = issue_date_for_update or "今日"
    with st.spinner(f"正在更新 {label} 的比赛结果..."):
        ok, message = _run_daily_result_update(ROOT, issue_date=issue_date_for_update)
    if ok:
        st.success(message)
        st.rerun()
    else:
        st.warning(message)

st.markdown("---")
st.markdown("### 基础分析")
metric_col1, metric_col2 = st.columns(2)

label_map = {"按日": "每日比赛数", "按月": "每月比赛总数", "按年": "每年比赛总数"}
metric_col1.metric(label_map[time_mode], len(filtered_matches))
league_label = "全部联赛比赛数" if selected_league == "全部联赛" else f"{selected_league} 比赛数"
metric_col2.metric(league_label, len(filtered_matches))

# ─────────────────────────────────────────────────────────────────────────────
# Gemini 推荐分析
# ─────────────────────────────────────────────────────────────────────────────

st.markdown("---")
st.markdown("### Gemini 推荐分析")
st.caption("包含自动抓取与手动补录（data_source=manual）的 Gemini 预测数据")

if use_facts:
    # 从事实表筛出有 Gemini 预测的行
    filtered_preds = filter_by_time_and_league(
        facts_df[
            facts_df["gemini_prediction_status"].notna()
            & (facts_df["gemini_prediction_status"].astype(str).str.strip() != "")
        ].copy(),
        time_mode, time_value, selected_league,
    )
else:
    filtered_preds = filter_by_time_and_league(pred_df, time_mode, time_value, selected_league)

if filtered_preds.empty:
    st.info("当前筛选条件下暂无 Gemini 推荐数据。")
else:
    if use_facts:
        # 直接用事实表命中字段
        summary = _hit_summary_from_facts(filtered_preds, "gemini_match_hit", "gemini_handicap_hit")
        eval_df = filtered_preds.copy()
        # 将事实表命中列映射到 display 列名
        eval_df["match_hit_result"] = eval_df.get("gemini_match_hit")
        eval_df["handicap_hit_result"] = eval_df.get("gemini_handicap_hit")
        eval_df["final_score"] = eval_df.get("full_time_score")
    else:
        results_df = load_results(ROOT)
        eval_df = evaluate_predictions(filtered_preds, results_df)
        summary = build_hit_summary(eval_df)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("推荐总场次", summary["total"])
    m2.metric("已结束场次", summary["ended"])
    m3.metric("胜平负预测命中率", summary["match_rate"])
    m4.metric("让胜平负预测命中率", summary["handicap_rate"])

    show_cols = [
        "match_no", "league", "home_team", "away_team", "kickoff_time", "handicap",
        "gemini_match_main_pick", "gemini_match_secondary_pick",
        "gemini_handicap_main_pick", "gemini_handicap_secondary_pick",
        "gemini_score_1", "gemini_score_2",
        "final_score", "match_hit_result", "handicap_hit_result", "data_source",
    ]
    for col in show_cols:
        if col not in eval_df.columns:
            eval_df[col] = None

    sorted_df = sort_by_match_no(eval_df[show_cols].copy())
    display_df = _build_cn_table(sorted_df)
    display_df["胜平负预测结果"] = display_df["胜平负预测结果"].map(_status_icon)
    display_df["让胜平负预测结果"] = display_df["让胜平负预测结果"].map(_status_icon)
    st.dataframe(display_df, use_container_width=True, hide_index=True)

# ─────────────────────────────────────────────────────────────────────────────
# ChatGPT 概率预测分析
# ─────────────────────────────────────────────────────────────────────────────

st.markdown("---")
st.markdown("### ChatGPT 概率预测分析")

if use_facts:
    chatgpt_filtered = filter_by_time_and_league(
        facts_df[
            facts_df["chatgpt_prediction_status"].astype(str).str.strip() == "present"
        ].copy(),
        time_mode, time_value, selected_league,
    )
    if not chatgpt_filtered.empty:
        chatgpt_filtered = ensure_issue_date_columns(chatgpt_filtered, source_col="issue_date")
    chatgpt_eval_df = chatgpt_filtered.copy()
    if not chatgpt_eval_df.empty:
        chatgpt_eval_df["match_hit_result"] = chatgpt_eval_df.get("chatgpt_match_hit")
        chatgpt_eval_df["handicap_hit_result"] = chatgpt_eval_df.get("chatgpt_handicap_hit")
        chatgpt_eval_df["final_score"] = chatgpt_eval_df.get("full_time_score")
    chatgpt_summary = _hit_summary_from_facts(chatgpt_eval_df, "chatgpt_match_hit", "chatgpt_handicap_hit")
else:
    chatgpt_df = load_chatgpt_predictions(ROOT)
    chatgpt_df = ensure_issue_date_columns(chatgpt_df, source_col="issue_date")
    chatgpt_filtered = filter_by_time_and_league(chatgpt_df, time_mode, time_value, selected_league)
    results_df = load_results(ROOT)
    chatgpt_eval_df = evaluate_chatgpt_predictions(chatgpt_filtered, results_df)
    chatgpt_summary = build_hit_summary(chatgpt_eval_df)

g1, g2, g3, g4 = st.columns(4)
g1.metric("推荐总场次", chatgpt_summary["total"])
g2.metric("已结束场次", chatgpt_summary["ended"])
g3.metric("胜平负预测命中率", chatgpt_summary["match_rate"])
g4.metric("让胜平负预测命中率", chatgpt_summary["handicap_rate"])

if chatgpt_eval_df.empty:
    st.info("当前筛选条件下暂无 ChatGPT 概率预测数据。")
else:
    for c in [
        "kickoff_time", "match_no", "league", "home_team", "away_team", "handicap",
        "chatgpt_home_win_prob", "chatgpt_draw_prob", "chatgpt_away_win_prob",
        "chatgpt_handicap_win_prob", "chatgpt_handicap_draw_prob", "chatgpt_handicap_lose_prob",
        "chatgpt_score_1", "chatgpt_score_2", "chatgpt_score_3",
        "chatgpt_top_direction", "chatgpt_upset_probability_text",
        "match_hit_result", "handicap_hit_result", "final_score",
    ]:
        if c not in chatgpt_eval_df.columns:
            chatgpt_eval_df[c] = None

    cdf = chatgpt_eval_df.copy()
    cdf["日期时间"] = pd.to_datetime(cdf["kickoff_time"], errors="coerce").dt.strftime("%Y-%m-%d %H:%M")
    cdf["比赛序号"] = cdf["match_no"]
    cdf["联赛"] = cdf["league"]
    cdf["主客队"] = cdf["home_team"].astype(str) + " vs " + cdf["away_team"].astype(str)
    cdf["让球"] = cdf["handicap"]
    cdf["胜平负"] = cdf.apply(
        lambda r: _join_main_secondary(r.get("chatgpt_match_main_pick"), r.get("chatgpt_match_secondary_pick")), axis=1
    )
    cdf["让胜平负"] = cdf.apply(
        lambda r: _join_main_secondary(r.get("chatgpt_handicap_main_pick"), r.get("chatgpt_handicap_secondary_pick")), axis=1
    )
    cdf["推荐比分"] = (
        cdf["chatgpt_score_1"].fillna("").astype(str)
        + "/" + cdf["chatgpt_score_2"].fillna("").astype(str)
        + "/" + cdf["chatgpt_score_3"].fillna("").astype(str)
    ).str.strip("/")
    cdf["概率"] = cdf.apply(
        lambda r: f"主{r.get('chatgpt_home_win_prob')}% | 平{r.get('chatgpt_draw_prob')}% | 客{r.get('chatgpt_away_win_prob')}%",
        axis=1,
    )
    cdf["比赛实际比分"] = cdf["final_score"]
    cdf["胜平负预测结果"] = cdf["match_hit_result"].map(_status_icon)
    cdf["让胜平负预测结果"] = cdf["handicap_hit_result"].map(_status_icon)

    cdf = sort_by_match_no(cdf)
    st.dataframe(
        cdf[[
            "日期时间", "比赛序号", "联赛", "主客队", "让球",
            "胜平负", "让胜平负", "推荐比分", "概率",
            "比赛实际比分", "胜平负预测结果", "让胜平负预测结果",
        ]],
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("#### 单场比赛概率分布")
    single_options = [
        (idx, f"{r.get('match_no', '-')} | {r.get('league', '-')} | {r.get('home_team', '-')} vs {r.get('away_team', '-')}")
        for idx, r in cdf.iterrows()
    ]
    selected_single_idx = st.selectbox(
        "选择比赛（用于下方两个饼图）",
        options=[x[0] for x in single_options],
        format_func=lambda x: dict(single_options).get(x, str(x)),
    )
    selected_row = cdf.loc[selected_single_idx]

    home_name = str(selected_row.get("home_team", "")).strip()
    away_name = str(selected_row.get("away_team", "")).strip()
    match_labels = semantic_match_labels(home_name, away_name, True)
    match_values = [
        pd.to_numeric(selected_row.get("chatgpt_home_win_prob"), errors="coerce"),
        pd.to_numeric(selected_row.get("chatgpt_draw_prob"), errors="coerce"),
        pd.to_numeric(selected_row.get("chatgpt_away_win_prob"), errors="coerce"),
    ]
    handicap_labels = ["让胜", "让平", "让负"]
    handicap_values = [
        pd.to_numeric(selected_row.get("chatgpt_handicap_win_prob"), errors="coerce"),
        pd.to_numeric(selected_row.get("chatgpt_handicap_draw_prob"), errors="coerce"),
        pd.to_numeric(selected_row.get("chatgpt_handicap_lose_prob"), errors="coerce"),
    ]

    pie_col1, pie_col2 = st.columns(2)
    with pie_col1:
        render_semantic_probability_pie(
            title="胜平负概率分布（单场）",
            labels=match_labels,
            values=[0 if pd.isna(v) else float(v) for v in match_values],
            semantic_keys=["home", "draw", "away"],
        )
    with pie_col2:
        render_semantic_probability_pie(
            title="让胜平负概率分布（单场）",
            labels=handicap_labels,
            values=[0 if pd.isna(v) else float(v) for v in handicap_values],
            semantic_keys=["home", "draw", "away"],
        )
