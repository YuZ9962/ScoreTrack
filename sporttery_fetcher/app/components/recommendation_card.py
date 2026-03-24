from __future__ import annotations

import streamlit as st


def _risk_badge(risk_level: str) -> str:
    mapping = {
        "low": "🟢 低风险",
        "medium": "🟠 中风险",
        "high": "🔴 高风险",
    }
    return mapping.get(str(risk_level), str(risk_level))


def render_recommendation_card(rec: dict) -> None:
    title = f"{rec.get('match_no', '-')}. {rec.get('home_team', '-') } vs {rec.get('away_team', '-')}"
    with st.expander(title, expanded=False):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("置信度", f"{rec.get('confidence_score', 0)}")
        c2.metric("适配度", f"{rec.get('fit_score', 0)}")
        c3.metric("风险", _risk_badge(str(rec.get('risk_level', ''))))
        c4.metric("建议", "跳过" if rec.get("should_skip") else "可入选")

        st.markdown(
            f"**联赛**：{rec.get('league', '-')} · **开赛**：{rec.get('kickoff_time', '-')} · "
            f"**推荐类型**：{rec.get('recommendation_type', '-') }"
        )
        st.markdown(
            f"**推荐方向**：`{rec.get('recommendation_label', '-')}`  \\n"
            f"**主推**：`{rec.get('primary_pick', '-')}`  \\n"
            f"**次选**：`{rec.get('secondary_pick') or '-'}`"
        )
        st.info(str(rec.get("rationale_summary", "")))

        points = rec.get("rationale_points", []) or []
        if points:
            st.markdown("**关键理由**")
            for p in points:
                st.markdown(f"- {p}")

        tags = rec.get("warning_tags", []) or []
        if tags:
            st.markdown("**风险标签**")
            st.caption(" | ".join([f"`{t}`" for t in tags]))

        d = rec.get("detailed_analysis", {}) or {}
        st.markdown("**详细分析**")
        st.markdown(f"- 基础面判断：{d.get('basic_view', '-')}")
        st.markdown(f"- 比赛结构判断：{d.get('structure_view', '-')}")
        st.markdown(f"- 赔率/盘口辅助理解：{d.get('market_view', '-')}")
        st.markdown(f"- 风险提示：{d.get('risk_notes', '-')}")
        st.markdown(f"- 最终建议：{d.get('final_verdict', '-')}")
