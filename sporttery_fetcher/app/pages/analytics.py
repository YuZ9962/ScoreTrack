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
from services.loader import get_data_context, load_all_matches, load_chatgpt_predictions, load_results
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
    out["比赛实际比分"] = out.get("final_score")
    out["胜平负预测结果"] = out.get("match_hit_result")
    out["让胜平负预测结果"] = out.get("handicap_hit_result")

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
        ]
    ]


def _status_icon(value: object) -> str:
    text = str(value or "").strip()
    if text == "命中":
        return "✅"
    if text == "未命中":
        return "❌"
    return "⏳"


st.set_page_config(page_title="统计分析", page_icon="📈", layout="wide")
st.title("📈 统计分析")

ctx = get_data_context(ROOT)
render_fetch_section(ROOT)

if st.button("更新比赛结果"):
    with st.spinner("正在抓取官方赛果并更新..."):
        try:
            result = fetch_and_save_results(ROOT)
            if result.get("ok"):
                st.success(f"赛果更新完成，共更新 {result.get('parsed_rows')} 场")
            else:
                st.warning("未抓取到赛果，请检查开奖页解析逻辑")
        except Exception:
            st.error("更新比赛结果失败，请稍后重试")

match_df = load_all_matches(ctx)
match_df = normalize_dataframe(match_df)
match_df = ensure_issue_date_columns(match_df, source_col="issue_date")

pred_df = load_predictions(ROOT)
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
filtered_preds = filter_by_time_and_league(pred_df, time_mode, time_value, selected_league)

st.markdown("---")
st.markdown("### 基础分析")
metric_col1, metric_col2 = st.columns(2)

label_map = {"按日": "每日比赛数", "按月": "每月比赛总数", "按年": "每年比赛总数"}
metric_col1.metric(label_map[time_mode], len(filtered_matches))

league_label = "全部联赛比赛数" if selected_league == "全部联赛" else f"{selected_league} 比赛数"
metric_col2.metric(league_label, len(filtered_matches))

st.markdown("---")
st.markdown("### Gemini 推荐分析")

if filtered_preds.empty:
    st.info("当前筛选条件下暂无 Gemini 推荐数据。")
    st.stop()

results_df = load_results(ROOT)
eval_df = evaluate_predictions(filtered_preds, results_df)
summary = build_hit_summary(eval_df)

m1, m2, m3, m4 = st.columns(4)
m1.metric("推荐总场次", summary["total"])
m2.metric("已结束场次", summary["ended"])
m3.metric("胜平负预测命中率", summary["match_rate"])
m4.metric("让胜平负预测命中率", summary["handicap_rate"])

show_cols = [
    "match_no",
    "league",
    "home_team",
    "away_team",
    "kickoff_time",
    "handicap",
    "gemini_match_main_pick",
    "gemini_match_secondary_pick",
    "gemini_handicap_main_pick",
    "gemini_handicap_secondary_pick",
    "gemini_score_1",
    "gemini_score_2",
    "final_score",
    "match_hit_result",
    "handicap_hit_result",
]

for col in show_cols:
    if col not in eval_df.columns:
        eval_df[col] = None

sorted_df = sort_by_match_no(eval_df[show_cols].copy())
display_df = _build_cn_table(sorted_df)
display_df["胜平负预测结果"] = display_df["胜平负预测结果"].map(_status_icon)
display_df["让胜平负预测结果"] = display_df["让胜平负预测结果"].map(_status_icon)
st.dataframe(display_df, use_container_width=True, hide_index=True)

st.markdown("---")
st.markdown("### ChatGPT 概率预测分析")
chatgpt_df = load_chatgpt_predictions(ROOT)
chatgpt_df = ensure_issue_date_columns(chatgpt_df, source_col="issue_date")
filtered_chatgpt = filter_by_time_and_league(chatgpt_df, time_mode, time_value, selected_league)

chatgpt_eval_df = evaluate_chatgpt_predictions(filtered_chatgpt, results_df)
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
        "kickoff_time",
        "match_no",
        "league",
        "home_team",
        "away_team",
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
        + "/"
        + cdf["chatgpt_score_2"].fillna("").astype(str)
        + "/"
        + cdf["chatgpt_score_3"].fillna("").astype(str)
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
        cdf[
            [
                "日期时间",
                "比赛序号",
                "联赛",
                "主客队",
                "让球",
                "胜平负",
                "让胜平负",
                "推荐比分",
                "概率",
                "比赛实际比分",
                "胜平负预测结果",
                "让胜平负预测结果",
            ]
        ],
        use_container_width=True,
        hide_index=True,
    )

    st.markdown("#### 单场比赛概率分布")
    single_options = []
    for idx, r in cdf.iterrows():
        single_options.append(
            (
                idx,
                f"{r.get('match_no', '-') } | {r.get('league', '-') } | {r.get('home_team', '-') } vs {r.get('away_team', '-')}",
            )
        )
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
