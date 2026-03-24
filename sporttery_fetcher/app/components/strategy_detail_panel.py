from __future__ import annotations

import streamlit as st

from strategies.registry import StrategyMeta


_STATUS_TEXT = {
    "active": "启用",
    "beta": "开发中 (Coming Soon)",
    "disabled": "已停用 (Coming Soon)",
}


def render_strategy_detail_panel(strategy: StrategyMeta) -> None:
    st.markdown("### 当前方案说明")
    st.markdown(
        f"**{strategy.name_cn}** / {strategy.name_en}  \\n版本：`{strategy.version}` · 状态：`{_STATUS_TEXT.get(strategy.status, strategy.status)}`"
    )
    st.write(strategy.long_description)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**适用比赛类型**")
        for item in strategy.applicable_scenarios:
            st.markdown(f"- {item}")
    with col2:
        st.markdown("**不适用比赛类型**")
        for item in strategy.not_applicable_scenarios:
            st.markdown(f"- {item}")

    st.markdown("**推荐输出逻辑**")
    for item in strategy.output_logic:
        st.markdown(f"- {item}")
