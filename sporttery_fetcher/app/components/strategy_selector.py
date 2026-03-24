from __future__ import annotations

import streamlit as st

from strategies.registry import StrategyMeta


_STATUS_TEXT = {
    "active": "启用",
    "beta": "开发中",
    "disabled": "已停用",
}


def render_strategy_selector(strategies: list[StrategyMeta], selected_id: str) -> str:
    labels = [f"{s.name_en}｜{s.name_cn}" for s in strategies]
    idx_map = {label: s.id for label, s in zip(labels, strategies)}

    selected_label = next((label for label, sid in idx_map.items() if sid == selected_id), labels[0])
    chosen = st.radio("选择推荐方案", labels, index=labels.index(selected_label), horizontal=False)

    for s in strategies:
        mark = "⭐ 默认" if s.is_default else ""
        badge = _STATUS_TEXT.get(s.status, s.status)
        st.caption(f"{s.name_cn} ({s.name_en}) · 状态: {badge} {mark} · {s.short_description}")

    return idx_map[chosen]
