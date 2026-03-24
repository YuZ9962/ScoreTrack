from __future__ import annotations

from datetime import date
from pathlib import Path

import streamlit as st

from services.fetch_runner import parse_date_input, run_fetch_for_date
from services.loader import DataContext, available_date_options, get_latest_date


def render_fetch_section(project_root: Path) -> None:
    st.sidebar.markdown("---")
    st.sidebar.subheader("抓取数据")

    default_date = date.today()
    selected = st.sidebar.date_input("抓取日期", value=default_date, key="fetch_date_input")
    dev_mode = st.sidebar.toggle("开发者模式（显示调试信息）", value=False, key="dev_mode")

    if st.sidebar.button("🚀 抓取并加载", type="primary", use_container_width=True):
        date_str = parse_date_input(selected)
        with st.spinner(f"正在抓取 {date_str} 的比赛数据..."):
            result = run_fetch_for_date(date_str, project_root)

        st.session_state["last_fetch_result"] = result
        if result["ok"]:
            st.session_state["selected_data_date"] = date_str
            st.rerun()

    result = st.session_state.get("last_fetch_result")
    if result:
        if result.get("ok"):
            st.sidebar.success(result.get("message", "抓取成功"))
        else:
            st.sidebar.error(result.get("message", "抓取失败"))

        if dev_mode:
            with st.sidebar.expander("调试信息"):
                st.code(result.get("stdout") or "(无 stdout)")
                st.code(result.get("stderr") or "(无 stderr)")


def render_date_file_selector(ctx: DataContext) -> str | None:
    options = available_date_options(ctx)
    if not options:
        return None

    preferred = st.session_state.get("selected_data_date")
    if preferred in options:
        idx = options.index(preferred)
    else:
        latest = get_latest_date(ctx)
        idx = options.index(latest) if latest in options else len(options) - 1

    selected_date = st.sidebar.selectbox("选择日期文件", options=options, index=idx, key="date_file_selector")
    st.session_state["selected_data_date"] = selected_date
    return selected_date
