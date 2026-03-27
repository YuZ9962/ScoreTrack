from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

APP_DIR = Path(__file__).resolve().parents[1]
ROOT = APP_DIR.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from services.article_store import save_article, update_wechat_upload_status
from services.loader import get_data_context, load_gemini_predictions_by_date, load_matches_by_date
from services.transforms import normalize_dataframe
from services.wechat_api import create_draft, has_wechat_config
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
                "wechat_upload_status": "未上传",
                "wechat_draft_id": None,
                "wechat_uploaded_at": None,
                "wechat_error_message": None,
            }
            csv_path, md_path = save_article(record, ROOT)
            generated.append(
                {
                    **record,
                    "prompt": result.get("prompt", ""),
                    "source_gemini": gemini_dict,
                    "csv_path": str(csv_path),
                    "md_path": str(md_path),
                }
            )

        st.session_state["wechat_articles"] = generated

st.markdown("---")
st.markdown("### 微信公众号上传状态")
if not has_wechat_config():
    st.warning("未配置 WECHAT_APP_ID / WECHAT_APP_SECRET，当前仅可生成文案，不能上传草稿。")

if st.button("批量上传今天生成的全部文章到草稿", disabled=not has_wechat_config()):
    author = (os.getenv("WECHAT_AUTHOR") or "金条玩足球").strip() or "金条玩足球"
    digest = (os.getenv("WECHAT_DEFAULT_DIGEST") or "").strip()
    enable_upload = (os.getenv("WECHAT_ENABLE_DRAFT_UPLOAD") or "true").strip().lower() == "true"
    if not enable_upload:
        st.warning("WECHAT_ENABLE_DRAFT_UPLOAD=false，已禁用上传")
    else:
        updated = []
        for article in st.session_state.get("wechat_articles", []):
            r = create_draft(
                title=article.get("article_title", ""),
                content=article.get("article_body", ""),
                author=author,
                digest=digest,
                thumb_media_id=None,
                base_dir=ROOT,
            )
            if r.get("ok"):
                article["wechat_upload_status"] = "已上传草稿"
                article["wechat_draft_id"] = r.get("draft_id")
                article["wechat_uploaded_at"] = r.get("uploaded_at")
                article["wechat_error_message"] = ""
            else:
                article["wechat_upload_status"] = "上传失败"
                article["wechat_error_message"] = r.get("error", "")

            update_wechat_upload_status(
                issue_date=str(article.get("issue_date", "")),
                match_no=str(article.get("match_no", "")),
                home_team=str(article.get("home_team", "")),
                away_team=str(article.get("away_team", "")),
                status=article.get("wechat_upload_status", "未上传"),
                draft_id=article.get("wechat_draft_id"),
                uploaded_at=article.get("wechat_uploaded_at") or datetime.now(timezone.utc).isoformat(),
                error_message=article.get("wechat_error_message"),
                base_dir=ROOT,
            )
            updated.append(article)
        st.session_state["wechat_articles"] = updated
        st.success("批量上传流程已完成，请查看每篇文章状态")

st.markdown("---")
st.markdown("### 生成结果")
for i, article in enumerate(st.session_state.get("wechat_articles", []), start=1):
    with st.container(border=True):
        st.markdown(f"#### {i}. {article.get('article_title', '')}")
        edited_title = st.text_input("标题", value=article.get("article_title", ""), key=f"title_{i}")
        edited_body = st.text_area("正文（可编辑）", value=article.get("article_body", ""), height=320, key=f"body_{i}")

        status = article.get("wechat_upload_status") or "未上传"
        draft_id = article.get("wechat_draft_id") or "-"
        uploaded_at = article.get("wechat_uploaded_at") or "-"
        st.caption(f"上传状态：{status} | 草稿ID：{draft_id} | 上传时间：{uploaded_at}")
        if article.get("wechat_error_message"):
            st.error(f"上传失败：{article.get('wechat_error_message')}")

        col1, col2, col3 = st.columns(3)
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
        with col3:
            if st.button("上传到公众号草稿", key=f"upload_{i}", disabled=not has_wechat_config()):
                author = (os.getenv("WECHAT_AUTHOR") or "金条玩足球").strip() or "金条玩足球"
                digest = (os.getenv("WECHAT_DEFAULT_DIGEST") or "").strip()
                enable_upload = (os.getenv("WECHAT_ENABLE_DRAFT_UPLOAD") or "true").strip().lower() == "true"
                if not enable_upload:
                    st.warning("WECHAT_ENABLE_DRAFT_UPLOAD=false，已禁用上传")
                else:
                    r = create_draft(
                        title=edited_title,
                        content=edited_body,
                        author=author,
                        digest=digest,
                        thumb_media_id=None,
                        base_dir=ROOT,
                    )
                    if r.get("ok"):
                        article["wechat_upload_status"] = "已上传草稿"
                        article["wechat_draft_id"] = r.get("draft_id")
                        article["wechat_uploaded_at"] = r.get("uploaded_at")
                        article["wechat_error_message"] = ""
                        update_wechat_upload_status(
                            issue_date=str(article.get("issue_date", "")),
                            match_no=str(article.get("match_no", "")),
                            home_team=str(article.get("home_team", "")),
                            away_team=str(article.get("away_team", "")),
                            status="已上传草稿",
                            draft_id=str(r.get("draft_id", "")),
                            uploaded_at=str(r.get("uploaded_at", "")),
                            error_message="",
                            base_dir=ROOT,
                        )
                        st.success(f"上传成功，草稿ID：{r.get('draft_id')}")
                    else:
                        article["wechat_upload_status"] = "上传失败"
                        article["wechat_error_message"] = r.get("error", "")
                        update_wechat_upload_status(
                            issue_date=str(article.get("issue_date", "")),
                            match_no=str(article.get("match_no", "")),
                            home_team=str(article.get("home_team", "")),
                            away_team=str(article.get("away_team", "")),
                            status="上传失败",
                            draft_id=None,
                            uploaded_at=datetime.now(timezone.utc).isoformat(),
                            error_message=str(r.get("error", "")),
                            base_dir=ROOT,
                        )
                        st.error(f"上传失败：{r.get('error')}")

        st.caption(f"保存位置：CSV {article.get('csv_path')} | MD {article.get('md_path')}")
        with st.expander("查看原始 Gemini 分析素材", expanded=False):
            st.json(article.get("source_gemini", {}))
