from __future__ import annotations

import pandas as pd
import streamlit as st

SEMANTIC_COLORS = {
    "home": "#3B82F6",  # 蓝色
    "draw": "#9CA3AF",  # 灰色
    "away": "#EF4444",  # 红色
}


def render_league_count_chart(df: pd.DataFrame) -> None:
    if "league" not in df.columns or df.empty:
        st.info("暂无联赛数据可绘图")
        return
    data = df["league"].fillna("未知").value_counts().sort_values(ascending=False)
    st.bar_chart(data)


def render_daily_trend_chart(df: pd.DataFrame) -> None:
    if "issue_date" not in df.columns or df.empty:
        st.info("暂无日期数据可绘图")
        return
    data = df["issue_date"].astype(str).value_counts().sort_index()
    st.line_chart(data)


def render_handicap_distribution(df: pd.DataFrame) -> None:
    if "handicap" not in df.columns or df.empty:
        st.info("暂无让球数据可绘图")
        return
    data = df["handicap"].astype("string").fillna("空").value_counts().sort_index()
    st.bar_chart(data)


def render_odds_distribution(df: pd.DataFrame, cols: list[str], title: str) -> None:
    st.caption(title)
    available = [c for c in cols if c in df.columns]
    if not available:
        st.info("暂无赔率字段")
        return
    numeric = df[available].apply(pd.to_numeric, errors="coerce")
    summary = numeric.describe().T[["count", "mean", "min", "max"]]
    st.dataframe(summary, use_container_width=True)


def render_semantic_probability_pie(
    *,
    title: str,
    labels: list[str],
    values: list[float],
    semantic_keys: list[str],
) -> None:
    if not labels or not values or len(labels) != len(values) or len(labels) != len(semantic_keys):
        st.info("暂无可绘制概率数据")
        return

    data = pd.DataFrame({"label": labels, "value": values, "semantic": semantic_keys})
    data["value"] = pd.to_numeric(data["value"], errors="coerce").fillna(0.0)

    total = float(data["value"].sum())
    if total <= 0:
        st.info("暂无可绘制概率数据")
        return

    data["pct"] = (data["value"] / total * 100).round(1)
    max_idx = int(data["value"].idxmax())
    data["is_max"] = data.index == max_idx
    data["display_pct"] = data["pct"].map(lambda x: f"{x:.1f}%")

    color_domain = ["home", "draw", "away"]
    color_range = [SEMANTIC_COLORS["home"], SEMANTIC_COLORS["draw"], SEMANTIC_COLORS["away"]]

    spec = {
        "layer": [
            {
                "mark": {
                    "type": "arc",
                    "innerRadius": 36,
                    "stroke": "#FFFFFF",
                    "strokeWidth": {"expr": "datum.is_max ? 3 : 1"},
                },
                "encoding": {
                    "theta": {"field": "value", "type": "quantitative"},
                    "radiusOffset": {
                        "condition": {"test": "datum.is_max", "value": 12},
                        "value": 0,
                    },
                    "color": {
                        "field": "semantic",
                        "type": "nominal",
                        "scale": {"domain": color_domain, "range": color_range},
                        "legend": None,
                    },
                    "tooltip": [
                        {"field": "label", "title": "方向"},
                        {"field": "display_pct", "title": "概率"},
                    ],
                },
            },
            {
                "mark": {
                    "type": "text",
                    "radius": 95,
                    "fontSize": 12,
                    "fontWeight": "bold",
                    "fill": "#111827",
                },
                "encoding": {
                    "theta": {"field": "value", "type": "quantitative", "stack": True},
                    "text": {"field": "display_pct", "type": "nominal"},
                },
            },
        ]
    }

    st.markdown(f"#### {title}")
    st.vega_lite_chart(data, spec, use_container_width=True)

    legend_df = pd.DataFrame({"图例": data["label"], "概率": data["display_pct"]})
    st.dataframe(legend_df, use_container_width=True, hide_index=True)
