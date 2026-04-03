from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

APP_DIR = Path(__file__).resolve().parents[1]
ROOT = APP_DIR.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from components.data_controls import render_date_file_selector, render_fetch_section
from components.filters import render_sidebar_filters
from components.match_table import render_match_selector, render_match_table
from components.detail_cards import render_match_detail
from services.loader import get_data_context, load_matches_by_date
from services.prediction_store import load_predictions
from services.transforms import apply_filters, normalize_dataframe, sort_matches



def _build_prediction_tag(df, pred_df, issue_date: str):
    out = df.copy()
    out["prediction_tag"] = "无"
    if pred_df.empty:
        return out

    day_pred = pred_df[pred_df["issue_date"].astype(str) == issue_date].copy()
    if day_pred.empty:
        return out

    for i, row in out.iterrows():
        raw_id = str(row.get("raw_id", "") or "").strip()
        if raw_id:
            matched = day_pred[day_pred["raw_id"].astype(str) == raw_id]
        else:
            matched = day_pred[
                (day_pred["match_no"].astype(str) == str(row.get("match_no", "")))
                & (day_pred["home_team"].astype(str) == str(row.get("home_team", "")))
                & (day_pred["away_team"].astype(str) == str(row.get("away_team", "")))
            ]

        if matched.empty:
            continue

        last = matched.iloc[-1]
        status = str(last.get("prediction_status", ""))
        source = str(last.get("prediction_source", ""))

        if status == "manual_filled":
            out.at[i, "prediction_tag"] = "手动"
        elif status == "success" and source == "auto_gemini":
            out.at[i, "prediction_tag"] = "自动"
        elif status == "failed":
            out.at[i, "prediction_tag"] = "失败"
        else:
            out.at[i, "prediction_tag"] = "已预测"

    return out


st.set_page_config(page_title="比赛列表", page_icon="📋", layout="wide")
st.title("📋 比赛列表")

ctx = get_data_context(ROOT)
render_fetch_section(ROOT)
selected_date = render_date_file_selector(ctx)
if not selected_date:
    st.warning("未找到 CSV 数据文件，请先抓取数据")
    st.stop()

try:
    df = load_matches_by_date(selected_date, ctx)
except Exception as exc:
    st.error(f"读取文件失败：{exc}")
    st.stop()

df = normalize_dataframe(df)
pred_df = load_predictions(ROOT)
df = _build_prediction_tag(df, pred_df, selected_date)

st.sidebar.markdown("---")
filters = render_sidebar_filters(df)
filtered = apply_filters(
    df,
    leagues=filters["leagues"],
    keyword=filters["keyword"],
    only_handicap_non_null=filters["only_handicap"],
    only_selling=filters["only_selling"],
)
filtered = sort_matches(filtered, filters["sort_by"], filters["ascending"])

st.caption(f"共 {len(filtered)} 场（原始 {len(df)} 场）")
if filtered.empty:
    st.info("当前筛选条件下无比赛数据")
    st.stop()

render_match_table(filtered)

st.markdown("---")
st.subheader("单场详情")
selected = render_match_selector(filtered)
if selected is not None:
    render_match_detail(selected)
