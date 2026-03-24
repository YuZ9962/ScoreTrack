from __future__ import annotations

import streamlit as st

from strategies.registry import StrategyMeta


_STATUS_TEXT = {
    "active": "启用",
    "beta": "开发中 · Coming Soon",
    "disabled": "已停用 · Coming Soon",
}


def render_strategy_selector(strategies: list[StrategyMeta], selected_id: str) -> str:
    label_map: dict[str, str] = {}
    options: list[str] = []

    for s in strategies:
        status = _STATUS_TEXT.get(s.status, s.status)
        label = f"{s.name_cn}｜{s.name_en}（{status}）"
        options.append(label)
        label_map[label] = s.id

    default_label = next((label for label, sid in label_map.items() if sid == selected_id), options[0])
    selected_label = st.selectbox(
        "选择推荐策略（可搜索）",
        options=options,
        index=options.index(default_label),
        help="可直接输入关键字搜索策略名称",
    )
    return label_map[selected_label]
