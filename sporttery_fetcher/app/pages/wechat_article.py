from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

APP_DIR = Path(__file__).resolve().parents[1]
ROOT = APP_DIR.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from services.article_store import save_article
from services.loader import get_data_context, load_gemini_predictions_by_date, load_matches_by_date
from services.transforms import normalize_dataframe
from services.wechat_writer import generate_wechat_article

st.set_page_config(page_title="公众号", page_icon="📝", layout="wide")
st.title("📝 公众号（【金条玩足球】）")

ctx = get_data_context(ROOT)
options = sorted([f.name.split("_matches.csv")[0] for f in ctx.files])
if not options:
    st.warning("暂无可用比赛数据")
    st.stop()

selected_date = st.selectbox("日期", options=options, index=len(options) - 1)
matches_df = normalize_dataframe(load_matches_by_date(selected_date, ctx))
gemini_df = load_gemini_predictions_by_date(selected_date, ROOT)

if matches_df.empty:
    st.info("当日无比赛")
    st.stop()

matches_df = matches_df.copy()
matches_df["_match_label"] = matches_df.apply(
    lambda r: f"{r.get('match_no', '-') } | {r.get('league', '-') } | {r.get('home_team', '-') } vs {r.get('away_team', '-') } | {r.get('kickoff_time', '-')}",
    axis=1,
)

selected_labels = st.multiselect(
    "选择 1~3 场比赛",
    options=matches_df["_match_label"].tolist(),
    default=[],
)

if len(selected_labels) > 3:
    st.error("最多只能选择 3 场比赛，请减少选择。")
    st.stop()

selected_matches = matches_df[matches_df["_match_label"].isin(selected_labels)].copy()
st.markdown("### 选中比赛预览")
if selected_matches.empty:
    st.caption("未选择比赛")
else:
    st.dataframe(
        selected_matches[["match_no", "league", "home_team", "away_team", "kickoff_time", "handicap"]],
        use_container_width=True,
        hide_index=True,
    )

manual_summary: dict[str, str] = {}
match_inputs: list[tuple[dict, dict]] = []

st.markdown("### Gemini 素材检查")
for _, row in selected_matches.iterrows():
    key = str(row.get("raw_id", "") or "").strip()
    if key and (not gemini_df.empty) and "raw_id" in gemini_df.columns:
        g = gemini_df[gemini_df["raw_id"].astype(str) == key].tail(1)
    else:
        g = gemini_df[
            (gemini_df["match_no"].astype(str) == str(row.get("match_no", "")))
            & (gemini_df["home_team"].astype(str) == str(row.get("home_team", "")))
            & (gemini_df["away_team"].astype(str) == str(row.get("away_team", "")))
        ].tail(1)

    match_dict = row.to_dict()
    if g.empty:
        st.warning(f"{row.get('match_no')} {row.get('home_team')} vs {row.get('away_team')}：未找到 Gemini 分析，可手动补录摘要")
        txt = st.text_area(
            f"手动补录摘要：{row.get('match_no')} {row.get('home_team')} vs {row.get('away_team')}",
            value="",
            height=90,
            key=f"manual_{row.get('match_no')}_{row.get('home_team')}_{row.get('away_team')}",
        )
        manual_summary[row.get("_match_label")] = txt
        gemini_dict = {
            "gemini_raw_text": txt,
            "gemini_summary": txt,
            "gemini_match_main_pick": "",
            "gemini_match_secondary_pick": "",
            "gemini_handicap_main_pick": "",
            "gemini_handicap_secondary_pick": "",
            "gemini_score_1": "",
            "gemini_score_2": "",
        }
    else:
        gemini_row = g.iloc[-1].to_dict()
        gemini_dict = {
            "gemini_raw_text": gemini_row.get("gemini_raw_text"),
            "gemini_summary": gemini_row.get("gemini_summary"),
            "gemini_match_main_pick": gemini_row.get("gemini_match_main_pick"),
            "gemini_match_secondary_pick": gemini_row.get("gemini_match_secondary_pick"),
            "gemini_handicap_main_pick": gemini_row.get("gemini_handicap_main_pick"),
            "gemini_handicap_secondary_pick": gemini_row.get("gemini_handicap_secondary_pick"),
            "gemini_score_1": gemini_row.get("gemini_score_1"),
            "gemini_score_2": gemini_row.get("gemini_score_2"),
        }
        st.success(f"{row.get('match_no')} {row.get('home_team')} vs {row.get('away_team')}：已找到 Gemini 分析")

    match_inputs.append((match_dict, gemini_dict))

if "wechat_articles" not in st.session_state:
    st.session_state["wechat_articles"] = []

if st.button("一键生成公众号文案", type="primary"):
    if len(selected_matches) == 0:
        st.warning("请先选择 1~3 场比赛")
    elif len(selected_matches) > 3:
        st.warning("最多 3 场")
    else:
        generated = []
        for match_dict, gemini_dict in match_inputs:
            result = generate_wechat_article(match_dict, gemini_dict)
            if not result.get("ok"):
                st.error(f"生成失败：{match_dict.get('home_team')} vs {match_dict.get('away_team')}")
                continue

            record = {
                "issue_date": selected_date,
                "match_no": match_dict.get("match_no"),
                "league": match_dict.get("league"),
                "home_team": match_dict.get("home_team"),
                "away_team": match_dict.get("away_team"),
                "article_title": result.get("article_title"),
                "article_body": result.get("article_body"),
                "generated_at": result.get("generated_at"),
                "source_model": result.get("source_model"),
                "source_analysis_type": "gemini",
            }
            csv_path, md_path = save_article(record, ROOT)
            generated.append({
                **record,
                "prompt": result.get("prompt", ""),
                "source_gemini": gemini_dict,
                "csv_path": str(csv_path),
                "md_path": str(md_path),
            })

        st.session_state["wechat_articles"] = generated

st.markdown("---")
st.markdown("### 生成结果")
for i, article in enumerate(st.session_state.get("wechat_articles", []), start=1):
    with st.container(border=True):
        st.markdown(f"#### {i}. {article.get('article_title', '')}")
        edited_title = st.text_input("标题", value=article.get("article_title", ""), key=f"title_{i}")
        edited_body = st.text_area("正文（可编辑）", value=article.get("article_body", ""), height=320, key=f"body_{i}")

        col1, col2 = st.columns(2)
        with col1:
            st.download_button(
                "导出 Markdown",
                data=f"# {edited_title}\n\n{edited_body}\n",
                file_name=f"{article.get('issue_date')}_{article.get('home_team')}_vs_{article.get('away_team')}.md",
                mime="text/markdown",
                key=f"dl_md_{i}",
            )
        with col2:
            st.download_button(
                "导出 TXT",
                data=f"{edited_title}\n\n{edited_body}\n",
                file_name=f"{article.get('issue_date')}_{article.get('home_team')}_vs_{article.get('away_team')}.txt",
                mime="text/plain",
                key=f"dl_txt_{i}",
            )

        st.caption(f"保存位置：CSV {article.get('csv_path')} | MD {article.get('md_path')}")
        with st.expander("查看原始 Gemini 分析素材", expanded=False):
            st.json(article.get("source_gemini", {}))
