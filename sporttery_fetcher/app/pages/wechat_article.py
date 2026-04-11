from __future__ import annotations

import os
from datetime import datetime, timezone

import bootstrap  # noqa: F401
import pandas as pd
import streamlit as st
from bootstrap import ROOT

from services.article_store import article_csv_file, load_articles, save_article, update_wechat_upload_status
from services.chatgpt_store import load_chatgpt_predictions
from services.loader import get_data_context, load_gemini_predictions_by_date, load_matches_by_date
from services.md2wechat_runner import DEFAULT_STYLE, STYLE_LABELS, convert_and_upload, is_available
from services.transforms import normalize_dataframe
from services.wechat_api import create_draft, has_wechat_config, list_drafts
from services.wechat_template import build_draft_from_template
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
chatgpt_df = load_chatgpt_predictions(ROOT)
if not chatgpt_df.empty and "issue_date" in chatgpt_df.columns:
    chatgpt_df = chatgpt_df[chatgpt_df["issue_date"].astype(str) == str(selected_date)].copy()

if matches_df.empty:
    st.info("当日无比赛")
    st.stop()

matches_df = matches_df.copy()
matches_df["_match_label"] = matches_df.apply(
    lambda r: (
        f"{r.get('match_no', '-')} | {r.get('league', '-')} | "
        f"{r.get('home_team', '-')} vs {r.get('away_team', '-')} | {r.get('kickoff_time', '-')}"
    ),
    axis=1,
)
_NONE = "（不选）"
label_options = [_NONE] + matches_df["_match_label"].tolist()


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _safe(v) -> str:
    s = str(v or "").strip()
    return "" if s in ("nan", "None", "none") else s


def _find_gemini(row_dict: dict) -> dict | None:
    if gemini_df.empty:
        return None
    key = _safe(row_dict.get("raw_id"))
    if key and "raw_id" in gemini_df.columns:
        g = gemini_df[gemini_df["raw_id"].astype(str) == key].tail(1)
    else:
        g = gemini_df[
            (gemini_df["match_no"].astype(str) == str(row_dict.get("match_no", "")))
            & (gemini_df["home_team"].astype(str) == str(row_dict.get("home_team", "")))
            & (gemini_df["away_team"].astype(str) == str(row_dict.get("away_team", "")))
        ].tail(1)
    return g.iloc[-1].to_dict() if not g.empty else None


def _find_chatgpt(row_dict: dict) -> dict | None:
    if chatgpt_df.empty:
        return None
    key = _safe(row_dict.get("raw_id"))
    if key and "raw_id" in chatgpt_df.columns:
        c = chatgpt_df[chatgpt_df["raw_id"].astype(str) == key].tail(1)
    else:
        c = chatgpt_df[
            (chatgpt_df["match_no"].astype(str) == str(row_dict.get("match_no", "")))
            & (chatgpt_df["home_team"].astype(str) == str(row_dict.get("home_team", "")))
            & (chatgpt_df["away_team"].astype(str) == str(row_dict.get("away_team", "")))
        ].tail(1)
    return c.iloc[-1].to_dict() if not c.empty else None


def _show_predictions(match_row: dict) -> None:
    g = _find_gemini(match_row)
    c = _find_chatgpt(match_row)
    col_g, col_c = st.columns(2)
    with col_g:
        st.markdown("**Gemini**")
        if g:
            picks = " / ".join(filter(None, [_safe(g.get("gemini_match_main_pick")), _safe(g.get("gemini_match_secondary_pick"))]))
            hdp = " / ".join(filter(None, [_safe(g.get("gemini_handicap_main_pick")), _safe(g.get("gemini_handicap_secondary_pick"))]))
            scores = " / ".join(filter(None, [_safe(g.get("gemini_score_1")), _safe(g.get("gemini_score_2"))]))
            if picks:
                st.caption(f"胜平负：{picks}")
            if hdp:
                st.caption(f"让球：{hdp}")
            if scores:
                st.caption(f"比分：{scores}")
            summary = _safe(g.get("gemini_summary"))
            if summary:
                st.caption(summary[:200])
        else:
            st.caption("暂无 Gemini 数据")
    with col_c:
        st.markdown("**ChatGPT**")
        if c:
            home = match_row.get("home_team", "主队")
            away = match_row.get("away_team", "客队")
            wp = _safe(c.get("chatgpt_home_win_prob"))
            dp = _safe(c.get("chatgpt_draw_prob"))
            lp = _safe(c.get("chatgpt_away_win_prob"))
            if any([wp, dp, lp]):
                st.caption(f"概率：{home}胜 {wp} | 平 {dp} | {away}胜 {lp}")
            hw = _safe(c.get("chatgpt_handicap_win_prob"))
            hd = _safe(c.get("chatgpt_handicap_draw_prob"))
            hl = _safe(c.get("chatgpt_handicap_lose_prob"))
            if any([hw, hd, hl]):
                st.caption(f"让球概率：赢 {hw} | 走 {hd} | 负 {hl}")
            picks = " / ".join(filter(None, [_safe(c.get("chatgpt_match_main_pick")), _safe(c.get("chatgpt_match_secondary_pick"))]))
            if picks:
                st.caption(f"推荐：{picks}")
            top = _safe(c.get("chatgpt_top_direction"))
            if top:
                st.caption(f"方向：{top}")
            summary = _safe(c.get("chatgpt_summary"))
            if summary:
                st.caption(summary[:200])
        else:
            st.caption("暂无 ChatGPT 数据")


def _gemini_dict_from_row(g: dict | None) -> dict:
    keys = [
        "gemini_raw_text", "gemini_summary",
        "gemini_match_main_pick", "gemini_match_secondary_pick",
        "gemini_handicap_main_pick", "gemini_handicap_secondary_pick",
        "gemini_score_1", "gemini_score_2",
    ]
    if g:
        return {k: g.get(k) for k in keys}
    return {k: "" for k in keys}


# ── 三个独立下拉菜单 ──────────────────────────────────────────────────────────
st.markdown("### 选择比赛（最多 3 场）")
dc1, dc2, dc3 = st.columns(3)
with dc1:
    sel1 = st.selectbox("比赛 1", options=label_options, key="sel_match_1")
with dc2:
    sel2 = st.selectbox("比赛 2", options=label_options, key="sel_match_2")
with dc3:
    sel3 = st.selectbox("比赛 3", options=label_options, key="sel_match_3")

# 去重、保序
_seen: set[str] = set()
selected_labels: list[str] = []
for _lbl in [sel1, sel2, sel3]:
    if _lbl != _NONE and _lbl not in _seen:
        selected_labels.append(_lbl)
        _seen.add(_lbl)

# ── 预测信息展示 ───────────────────────────────────────────────────────────────
if selected_labels:
    st.markdown("#### 预测信息")
    pred_cols = st.columns(len(selected_labels))
    for _idx, _lbl in enumerate(selected_labels):
        _mrow = matches_df[matches_df["_match_label"] == _lbl].iloc[0].to_dict()
        with pred_cols[_idx]:
            st.markdown(f"**{_mrow.get('match_no')} {_mrow.get('home_team')} vs {_mrow.get('away_team')}**")
            _show_predictions(_mrow)

# ── 自动从 CSV 加载已有文章（选择变化时触发）──────────────────────────────────
_sel_key = f"{selected_date}|{'|'.join(selected_labels)}"
if st.session_state.get("_wechat_sel_key") != _sel_key:
    st.session_state["_wechat_sel_key"] = _sel_key
    _csv_arts = load_articles(ROOT)
    _preloaded: list[dict] = []
    for _lbl in selected_labels:
        _mrow = matches_df[matches_df["_match_label"] == _lbl].iloc[0].to_dict()
        _existing: pd.DataFrame = pd.DataFrame()
        if not _csv_arts.empty:
            _dm = _csv_arts["issue_date"].astype(str) == str(selected_date)
            _mm = (
                (_csv_arts["home_team"].astype(str) == str(_mrow.get("home_team", "")))
                & (_csv_arts["away_team"].astype(str) == str(_mrow.get("away_team", "")))
            )
            _existing = _csv_arts[_dm & _mm]
        if not _existing.empty:
            _art = _existing.iloc[-1].to_dict()
            _preloaded.append({
                **_art,
                "source_match": _mrow,
                "source_gemini": _gemini_dict_from_row(_find_gemini(_mrow)),
                "csv_path": str(article_csv_file(ROOT)),
                "md_path": str(
                    ROOT / "data" / "articles" /
                    f"{selected_date}_{str(_mrow.get('home_team','')).replace('/','-')}_vs_{str(_mrow.get('away_team','')).replace('/','-')}.md"
                ),
            })
    st.session_state["wechat_articles"] = _preloaded

# ── 手动补录 Gemini 素材（无 Gemini 数据的场次）────────────────────────────────
if selected_labels:
    st.markdown("#### Gemini 素材检查")
for _lbl in selected_labels:
    _mrow = matches_df[matches_df["_match_label"] == _lbl].iloc[0].to_dict()
    if _find_gemini(_mrow) is None:
        st.warning(
            f"{_mrow.get('match_no')} {_mrow.get('home_team')} vs {_mrow.get('away_team')}："
            "未找到 Gemini 分析，可手动补录摘要"
        )
        st.text_area(
            f"手动补录：{_mrow.get('match_no')} {_mrow.get('home_team')} vs {_mrow.get('away_team')}",
            value="",
            height=90,
            key=f"manual_{_mrow.get('match_no')}_{_mrow.get('home_team')}_{_mrow.get('away_team')}",
        )

# ── 构建 match_inputs（用于生成按钮）────────────────────────────────────────
match_inputs: list[tuple[dict, dict]] = []
_already_generated = {
    (str(a.get("home_team", "")), str(a.get("away_team", "")))
    for a in st.session_state.get("wechat_articles", [])
}
for _lbl in selected_labels:
    _mrow = matches_df[matches_df["_match_label"] == _lbl].iloc[0].to_dict()
    _g = _find_gemini(_mrow)
    _manual_key = f"manual_{_mrow.get('match_no')}_{_mrow.get('home_team')}_{_mrow.get('away_team')}"
    _manual_txt = st.session_state.get(_manual_key, "")
    if _g is None and _manual_txt:
        _g = {
            "gemini_raw_text": _manual_txt, "gemini_summary": _manual_txt,
            "gemini_match_main_pick": "", "gemini_match_secondary_pick": "",
            "gemini_handicap_main_pick": "", "gemini_handicap_secondary_pick": "",
            "gemini_score_1": "", "gemini_score_2": "",
        }
    match_inputs.append((_mrow, _gemini_dict_from_row(_g)))

# ── 生成按钮 ──────────────────────────────────────────────────────────────────
_need_generate = [
    (md, gd) for md, gd in match_inputs
    if (str(md.get("home_team", "")), str(md.get("away_team", ""))) not in _already_generated
]
_btn_label = "一键生成公众号文案"
if _need_generate and _already_generated:
    _btn_label = f"生成剩余 {len(_need_generate)} 篇文章"

if st.button(_btn_label, type="primary", disabled=not selected_labels):
    if not selected_labels:
        st.warning("请先选择至少 1 场比赛")
    else:
        _to_generate = _need_generate if _need_generate else match_inputs
        for match_dict, gemini_dict in _to_generate:
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
                "article_fields": result.get("article_fields") or {},
                "generated_at": result.get("generated_at"),
                "source_model": result.get("source_model"),
                "source_analysis_type": "gemini",
                "wechat_upload_status": "未上传",
                "wechat_draft_id": None,
                "wechat_uploaded_at": None,
                "wechat_error_message": None,
            }
            csv_path, md_path = save_article(record, ROOT)
            new_entry = {
                **record,
                "prompt": result.get("prompt", ""),
                "source_gemini": gemini_dict,
                "source_match": match_dict,
                "csv_path": str(csv_path),
                "md_path": str(md_path),
            }
            # 替换 session 中同场次旧记录（如有）
            arts = st.session_state.get("wechat_articles", [])
            arts = [
                a for a in arts
                if not (
                    str(a.get("home_team")) == str(match_dict.get("home_team"))
                    and str(a.get("away_team")) == str(match_dict.get("away_team"))
                )
            ]
            arts.append(new_entry)
            st.session_state["wechat_articles"] = arts

        # 刷新选择键，避免触发 CSV 重载覆盖刚生成的内容
        st.session_state["_wechat_sel_key"] = _sel_key
        st.rerun()

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
        csv_articles = load_articles(ROOT)
        pending_from_csv = []
        if not csv_articles.empty:
            day_mask = csv_articles["issue_date"].astype(str) == str(selected_date)
            unuploaded_mask = csv_articles["wechat_upload_status"].astype(str).isin(["未上传", "上传失败", "nan", ""])
            pending_rows = csv_articles[day_mask & unuploaded_mask]
            pending_from_csv = pending_rows.to_dict("records")

        session_articles = st.session_state.get("wechat_articles", [])
        seen = {(a.get("match_no"), a.get("home_team"), a.get("away_team")) for a in session_articles}
        for row in pending_from_csv:
            key = (row.get("match_no"), row.get("home_team"), row.get("away_team"))
            if key not in seen:
                session_articles.append(row)
                seen.add(key)

        if not session_articles:
            st.warning("当天暂无待上传文章，请先生成文案")
        else:
            success_count, fail_count = 0, 0
            updated = []
            for article in session_articles:
                if str(article.get("wechat_upload_status", "")) == "已上传草稿":
                    updated.append(article)
                    continue
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
                    success_count += 1
                else:
                    article["wechat_upload_status"] = "上传失败"
                    article["wechat_error_message"] = r.get("error", "")
                    fail_count += 1

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
            if fail_count == 0:
                st.success(f"批量上传完成：{success_count} 篇成功")
            else:
                st.warning(f"批量上传完成：{success_count} 篇成功，{fail_count} 篇失败，请查看错误信息")

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

        _md2w_style_key = f"md2w_style_{i}"
        if _md2w_style_key not in st.session_state:
            st.session_state[_md2w_style_key] = DEFAULT_STYLE
        selected_style = st.selectbox(
            "md2wechat 风格",
            options=list(STYLE_LABELS.keys()),
            format_func=lambda k: STYLE_LABELS[k],
            key=_md2w_style_key,
        )

        col1, col2, col3, col4, col5, col6 = st.columns(6)
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

        with col4:
            if st.button("使用模板上传草稿", key=f"upload_tmpl_{i}", disabled=not has_wechat_config()):
                fields = article.get("article_fields") or {}
                if not fields or not fields.get("前言"):
                    st.warning("字段未解析，请重新生成文章后再使用模板上传")
                else:
                    enable_upload = (os.getenv("WECHAT_ENABLE_DRAFT_UPLOAD") or "true").strip().lower() == "true"
                    if not enable_upload:
                        st.warning("WECHAT_ENABLE_DRAFT_UPLOAD=false，已禁用上传")
                    else:
                        author = (os.getenv("WECHAT_AUTHOR") or "金条玩足球").strip() or "金条玩足球"
                        with st.spinner("拉取模板并替换字段..."):
                            build_r = build_draft_from_template(
                                article_title=edited_title,
                                fields=fields,
                                base_dir=ROOT,
                            )
                        if not build_r.get("ok"):
                            st.error(f"模板渲染失败：{build_r.get('error')}")
                        else:
                            content_html = build_r["content_html"]
                            content_bytes = len(content_html.encode("utf-8"))
                            r = create_draft(
                                title=edited_title,
                                content=content_html,
                                author=author,
                                digest="",
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
                                st.success(f"模板草稿上传成功，草稿ID：{r.get('draft_id')}")
                            else:
                                st.error(f"上传失败：{r.get('error')}（content {content_bytes} bytes）")

        with col5:
            _md2w_disabled = not (has_wechat_config() and is_available())
            _md2w_tooltip = "" if not _md2w_disabled else "需配置 WECHAT_APP_ID/SECRET 并安装 md2wechat"
            if st.button("md2wechat 上传", key=f"upload_md2w_{i}", disabled=_md2w_disabled, help=_md2w_tooltip):
                enable_upload = (os.getenv("WECHAT_ENABLE_DRAFT_UPLOAD") or "true").strip().lower() == "true"
                if not enable_upload:
                    st.warning("WECHAT_ENABLE_DRAFT_UPLOAD=false，已禁用上传")
                else:
                    author = (os.getenv("WECHAT_AUTHOR") or "金条玩足球").strip() or "金条玩足球"
                    style = st.session_state.get(_md2w_style_key, DEFAULT_STYLE)
                    with st.spinner(f"md2wechat 转换并上传（风格：{STYLE_LABELS.get(style, style)}）..."):
                        r = convert_and_upload(
                            edited_body,
                            title=edited_title,
                            author=author,
                            style=style,
                            base_dir=ROOT,
                        )
                    if r.get("ok"):
                        raw = r.get("raw") or {}
                        draft_id = str(raw.get("media_id") or raw.get("draft_id") or "")
                        article["wechat_upload_status"] = "已上传草稿"
                        article["wechat_draft_id"] = draft_id
                        article["wechat_uploaded_at"] = datetime.now(timezone.utc).isoformat()
                        article["wechat_error_message"] = ""
                        update_wechat_upload_status(
                            issue_date=str(article.get("issue_date", "")),
                            match_no=str(article.get("match_no", "")),
                            home_team=str(article.get("home_team", "")),
                            away_team=str(article.get("away_team", "")),
                            status="已上传草稿",
                            draft_id=draft_id,
                            uploaded_at=article["wechat_uploaded_at"],
                            error_message="",
                            base_dir=ROOT,
                        )
                        st.success(f"md2wechat 上传成功（{STYLE_LABELS.get(style, style)}）草稿ID：{draft_id}")
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
                        st.error(f"md2wechat 上传失败：{r.get('error')}")

        with col6:
            if st.button("重新生成", key=f"regen_{i}"):
                match_d = article.get("source_match") or {}
                gemini_d = article.get("source_gemini") or {}
                with st.spinner("重新生成中..."):
                    new_result = generate_wechat_article(match_d, gemini_d)
                if new_result.get("ok"):
                    arts = st.session_state["wechat_articles"]
                    arts[i - 1]["article_title"] = new_result.get("article_title", "")
                    arts[i - 1]["article_body"] = new_result.get("article_body", "")
                    arts[i - 1]["article_fields"] = new_result.get("article_fields") or {}
                    arts[i - 1]["source_model"] = new_result.get("source_model", "")
                    arts[i - 1]["wechat_upload_status"] = "未上传"
                    arts[i - 1]["wechat_draft_id"] = None
                    save_article(arts[i - 1], ROOT)
                    # 更新选择键以防止 CSV 重载覆盖刚生成的内容
                    st.session_state["_wechat_sel_key"] = _sel_key
                    st.success("重新生成成功")
                    st.rerun()
                else:
                    st.error(f"重新生成失败：{new_result.get('error', '')}")

        st.caption(f"保存位置：CSV {article.get('csv_path')} | MD {article.get('md_path')}")
        with st.expander("字段拆解（11个字段）", expanded=False):
            fields = article.get("article_fields") or {}
            if not fields:
                st.caption("暂无字段数据（旧记录，请重新生成）")
            else:
                col_a, col_b = st.columns(2)
                with col_a:
                    st.text_area("前言", value=fields.get("前言", ""), height=100, key=f"f_preface_{i}", disabled=True)
                    st.text_input("主队名称", value=fields.get("主队名称", ""), key=f"f_home_name_{i}", disabled=True)
                    st.text_area("主队分析", value=fields.get("主队分析", ""), height=120, key=f"f_home_analysis_{i}", disabled=True)
                    st.text_input("客队名称", value=fields.get("客队名称", ""), key=f"f_away_name_{i}", disabled=True)
                    st.text_area("客队分析", value=fields.get("客队分析", ""), height=120, key=f"f_away_analysis_{i}", disabled=True)
                with col_b:
                    st.text_area("主基调", value=fields.get("主基调", ""), height=150, key=f"f_tone_{i}", disabled=True)
                    st.text_input("结果（推荐）", value=fields.get("结果", ""), key=f"f_result_{i}", disabled=True)
                    st.text_input("score1", value=fields.get("score1", ""), key=f"f_score1_{i}", disabled=True)
                    st.text_input("score2", value=fields.get("score2", ""), key=f"f_score2_{i}", disabled=True)
                    st.text_area("总结", value=fields.get("总结", ""), height=100, key=f"f_summary_{i}", disabled=True)

        with st.expander("查看原始 Gemini 分析素材", expanded=False):
            st.json(article.get("source_gemini", {}))

st.markdown("---")
st.markdown("### 微信草稿模板分析（日常公众号模板）")
st.caption("此区块用于获取并分析微信草稿箱中的模板内容，暂不做集成改变。")
if not has_wechat_config():
    st.warning("未配置 WECHAT_APP_ID / WECHAT_APP_SECRET，无法获取草稿列表。")
else:
    if st.button("获取草稿列表（分析模板）"):
        with st.spinner("请求微信草稿列表…"):
            result = list_drafts(offset=0, count=20)
        if not result.get("ok"):
            st.error(f"获取失败：{result.get('error')}")
        else:
            items = result.get("items", [])
            total = result.get("total", 0)
            st.success(f"共 {total} 篇草稿，返回 {len(items)} 篇")
            template_item = None
            for item in items:
                content_list = item.get("content", {}).get("news_item", [])
                for article_item in content_list:
                    if "日常公众号模板" in (article_item.get("title") or ""):
                        template_item = article_item
                        break
                if template_item:
                    break

            if template_item:
                st.success("找到模板：日常公众号模板")
                st.markdown(f"**标题**: {template_item.get('title')}")
                st.markdown(f"**作者**: {template_item.get('author')}")
                st.markdown(f"**摘要**: {template_item.get('digest')}")
                with st.expander("模板 HTML 内容（原始）", expanded=True):
                    content_html = template_item.get("content", "")
                    st.code(content_html[:5000] if content_html else "（空）", language="html")
                    if len(content_html) > 5000:
                        st.caption(f"内容已截断，总长度 {len(content_html)} 字符")
            else:
                st.warning('未在草稿中找到标题含"日常公众号模板"的草稿')
                st.markdown("**全部草稿标题：**")
                for item in items:
                    for a in item.get("content", {}).get("news_item", []):
                        st.markdown(f"- {a.get('title', '（无标题）')}")
