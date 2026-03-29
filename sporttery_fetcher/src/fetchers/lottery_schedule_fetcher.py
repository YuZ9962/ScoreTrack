"""
lottery_schedule_fetcher.py
从 lottery.gov.cn/jc/zqszsc 抓取每日未开始的比赛赛程。

lottery.gov.cn 与 sporttery.cn 共享同一套前端框架（SPA + jQuery UI Datepicker），
因此复用 zqsgkj_fetcher 的 SPA 交互辅助函数。
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from config.settings import settings
from src.utils.logger import get_logger

# 复用 zqsgkj_fetcher 的 SPA 辅助函数
from src.fetchers.zqsgkj_fetcher import (
    _wait_for_form_ready,
    _diagnose_date_inputs,
    _fill_date_input,
    _submit_query_with_js_priority,
    _wait_matchlist_updated,
    _extract_matchlist_state,
    _table_signature,
    _click_next_page,
    _click_pagern_next_via_js,
    _scroll_to_bottom,
    _save_page_snapshot,
    MATCH_NO_RE,
    TEAM_RE,
    MAX_PAGINATION_PAGES,
)

logger = get_logger("lottery_schedule_fetcher")

SCHEDULE_STATUS_PENDING = {"待开奖", "未开始", "待售", "未售"}  # 还未开始的状态关键字

# 赛程 CSV 输出字段（对应 data/processed/YYYY-MM-DD_matches.csv schema）
SCHEDULE_OUTPUT_COLUMNS = [
    "issue_date",
    "match_no",
    "league",
    "home_team",
    "away_team",
    "kickoff_time",
    "handicap",
    "sell_status",
    "spf_win",
    "spf_draw",
    "spf_lose",
    "rqspf_win",
    "rqspf_draw",
    "rqspf_lose",
    "source_url",
    "scrape_time",
]


def _parse_team_handicap(text: str) -> tuple[str, str, str]:
    """从 '主队(让球)VS客队' 格式提取 home_team, handicap, away_team。"""
    t = str(text or "").strip().replace(" ", "")
    m = TEAM_RE.match(t)
    if not m:
        return t, "", ""
    return (m.group(1) or "").strip(), (m.group(3) or "").strip(), (m.group(4) or "").strip()


def _is_status_pending(status: str) -> bool:
    """判断比赛是否未开始（待开奖/未开始等）。"""
    s = str(status or "").strip()
    if not s:
        return True  # 无状态字段时默认保留
    return s in SCHEDULE_STATUS_PENDING or "已完成" not in s


def _detect_column_indices(header_cells: list[str]) -> dict[str, int]:
    """从表头文字自动映射列名 → 索引。"""
    mapping: dict[str, int] = {}
    for i, h in enumerate(header_cells):
        h_clean = re.sub(r"\s+", "", str(h or ""))
        if "日期" in h_clean or "赛事日期" in h_clean:
            mapping.setdefault("match_date", i)
        elif "编号" in h_clean or "赛事编号" in h_clean:
            mapping.setdefault("match_no", i)
        elif "联赛" in h_clean:
            mapping.setdefault("league", i)
        elif "vs" in h_clean.lower() or "主队" in h_clean:
            mapping.setdefault("teams", i)
        elif "开赛" in h_clean or "时间" in h_clean:
            mapping.setdefault("kickoff_time", i)
        elif "让球胜" in h_clean or "让胜" in h_clean or ("让" in h_clean and "胜" in h_clean):
            mapping.setdefault("rqspf_win", i)
        elif "让球平" in h_clean or "让平" in h_clean:
            mapping.setdefault("rqspf_draw", i)
        elif "让球负" in h_clean or "让负" in h_clean:
            mapping.setdefault("rqspf_lose", i)
        elif h_clean == "胜":
            mapping.setdefault("spf_win", i)
        elif h_clean == "平":
            mapping.setdefault("spf_draw", i)
        elif h_clean == "负":
            mapping.setdefault("spf_lose", i)
        elif "状态" in h_clean or "销售" in h_clean:
            mapping.setdefault("sell_status", i)
    return mapping


def _parse_schedule_row(
    issue_date: str,
    cells: list[str],
    col_map: dict[str, int],
    source_url: str,
) -> dict[str, str] | None:
    """将一行 TD 数据转换为赛程记录。"""
    def _get(key: str, default: str = "") -> str:
        idx = col_map.get(key)
        if idx is None or idx >= len(cells):
            return default
        return str(cells[idx] or "").strip()

    match_no = _get("match_no")
    if not match_no or not MATCH_NO_RE.match(match_no):
        return None

    team_text = _get("teams")
    home_team, handicap, away_team = _parse_team_handicap(team_text)
    if not home_team:
        return None

    sell_status = _get("sell_status")
    if not _is_status_pending(sell_status):
        return None  # 跳过已完成比赛

    return {
        "issue_date": issue_date,
        "match_no": match_no,
        "league": _get("league"),
        "home_team": home_team,
        "away_team": away_team,
        "kickoff_time": _get("kickoff_time"),
        "handicap": handicap,
        "sell_status": sell_status,
        "spf_win": _get("spf_win"),
        "spf_draw": _get("spf_draw"),
        "spf_lose": _get("spf_lose"),
        "rqspf_win": _get("rqspf_win"),
        "rqspf_draw": _get("rqspf_draw"),
        "rqspf_lose": _get("rqspf_lose"),
        "source_url": source_url,
        "scrape_time": datetime.utcnow().isoformat(),
    }


def _extract_header_row(table: Any) -> list[str]:
    """提取表格第一行表头文字。"""
    for row_sel in ["thead tr", "tr"]:
        try:
            rows = table.locator(row_sel)
            if rows.count() > 0:
                first = rows.nth(0)
                cells = first.locator("th, td")
                n = cells.count()
                if n > 0:
                    return [cells.nth(i).inner_text(timeout=600).strip() for i in range(n)]
        except Exception:
            continue
    return []


def _parse_data_rows(
    table: Any,
    issue_date: str,
    col_map: dict[str, int],
    source_url: str,
) -> list[dict[str, str]]:
    """解析数据表所有行。"""
    rows_out: list[dict[str, str]] = []
    for row_sel in ["tbody tr", "tr"]:
        try:
            body_rows = table.locator(row_sel)
            n = body_rows.count()
        except Exception:
            n = 0
        if n == 0:
            continue
        for i in range(n):
            try:
                tr = body_rows.nth(i)
                tds = tr.locator("td")
                td_n = tds.count()
                if td_n < 4:
                    continue
                cells = [tds.nth(j).inner_text(timeout=500).strip() for j in range(td_n)]
                rec = _parse_schedule_row(issue_date, cells, col_map, source_url)
                if rec:
                    rows_out.append(rec)
            except Exception:
                continue
        break  # 找到合适的 row_sel 后停止
    return rows_out


def _parse_page_schedule(page: Any, issue_date: str, source_url: str) -> list[dict[str, str]]:
    """从当前页面提取赛程行（自动检测表头 → 映射列索引）。"""
    col_map: dict[str, int] = {}
    all_rows: list[dict[str, str]] = []

    try:
        tables = page.locator("table")
        n_tables = tables.count()
    except Exception:
        return []

    header_found = False
    for i in range(n_tables):
        table = tables.nth(i)
        header_cells = _extract_header_row(table)
        if not header_cells:
            continue
        detected = _detect_column_indices(header_cells)
        if "match_no" in detected or "teams" in detected:
            col_map = detected
            header_found = True
            logger.info("赛程表头检测 table_idx=%s header=%s col_map=%s", i, header_cells, col_map)
            # 如果同一个 table 里也有数据行，直接解析
            rows = _parse_data_rows(table, issue_date, col_map, source_url)
            all_rows.extend(rows)
            # 再尝试下一个 table 作为纯数据表
            if i + 1 < n_tables:
                data_table = tables.nth(i + 1)
                data_rows = _parse_data_rows(data_table, issue_date, col_map, source_url)
                all_rows.extend(data_rows)
            break

    if not header_found:
        # 兜底：直接遍历所有 table
        for i in range(n_tables):
            table = tables.nth(i)
            rows = _parse_data_rows(table, issue_date, {}, source_url)
            all_rows.extend(rows)

    logger.info("当前页赛程解析完成 rows=%s", len(all_rows))
    return all_rows


def fetch_lottery_schedule(issue_date: str) -> list[dict[str, str]]:
    """从 lottery.gov.cn/jc/zqszsc 抓取指定日期的赛程（未开始的比赛）。

    返回字段兼容 data/processed/YYYY-MM-DD_matches.csv schema。
    """
    from playwright.sync_api import sync_playwright

    source_url = settings.lottery_schedule_url
    start_date = issue_date
    end_date = issue_date  # 赛程只查当日

    logger.info("开始抓取lottery赛程 issue_date=%s url=%s", issue_date, source_url)

    all_rows: list[dict[str, str]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=settings.playwright_headless)
        context = browser.new_context(user_agent=settings.user_agent)
        page = context.new_page()

        try:
            page.goto(source_url, wait_until="domcontentloaded", timeout=settings.request_timeout * 1000)
        except Exception as exc:
            logger.warning("导航到赛程页失败 url=%s err=%s", source_url, exc)
            browser.close()
            return []

        # 等待SPA表单注入
        form_ready = _wait_for_form_ready(page, timeout_ms=18000)
        logger.info("赛程页表单就绪=%s", form_ready)

        old_state = _extract_matchlist_state(page)

        # 设置日期并提交查询
        js_set_ok, click_submit_ok, submit_mode = _submit_query_with_js_priority(page, start_date, end_date)
        page.wait_for_timeout(1200)
        changed, new_state = _wait_matchlist_updated(page, old_state, timeout_ms=15000)

        if not changed:
            # 二次提交重试
            try:
                page.evaluate("() => { if (typeof click_submit === 'function') click_submit(); }")
            except Exception:
                pass
            page.wait_for_timeout(1000)
            changed, new_state = _wait_matchlist_updated(page, old_state, timeout_ms=10000)

        logger.info(
            "赛程查询状态 js_set_ok=%s submit_mode=%s changed=%s first_date=%s match_count=%s",
            js_set_ok, submit_mode, changed,
            new_state.get("first_date"), new_state.get("match_count"),
        )

        if not changed and not new_state.get("match_count"):
            logger.warning("赛程页未返回数据，放弃")
            browser.close()
            return []

        page.wait_for_load_state("networkidle", timeout=max(12000, settings.request_timeout * 1000))
        _save_page_snapshot(page, issue_date, page_no=1)

        visited_signatures: set[str] = set()

        for page_index in range(1, MAX_PAGINATION_PAGES + 1):
            try:
                _scroll_to_bottom(page)
                page_rows = _parse_page_schedule(page, issue_date, source_url)
                logger.info("赛程第%s页 解析行数=%s", page_index, len(page_rows))
                all_rows.extend(page_rows)

                signature = _table_signature(page)
                if signature in visited_signatures:
                    logger.warning("赛程分页签名重复，停止翻页")
                    break
                visited_signatures.add(signature)

                if page_index >= MAX_PAGINATION_PAGES:
                    break

                moved, _, _ = _click_next_page(page, signature, "")
                if not moved:
                    logger.info("赛程翻页结束")
                    break

                page.wait_for_load_state("networkidle", timeout=max(9000, settings.request_timeout * 1000))

            except Exception:
                logger.exception("赛程分页解析异常，已停止")
                break

        browser.close()

    # 去重
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, str]] = []
    for r in all_rows:
        key = (str(r.get("issue_date", "")), str(r.get("match_no", "")))
        if key not in seen:
            seen.add(key)
            deduped.append(r)

    logger.info("lottery赛程抓取完成 total=%s deduped=%s", len(all_rows), len(deduped))
    return deduped
