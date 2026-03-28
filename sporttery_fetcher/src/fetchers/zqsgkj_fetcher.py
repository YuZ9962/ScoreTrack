from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from config.settings import settings
from src.utils.logger import get_logger

logger = get_logger("zqsgkj_fetcher")

ZQSGKJ_URL = "https://www.sporttery.cn/jc/zqsgkj/"
MATCH_NO_RE = re.compile(r"^周[一二三四五六日]\d{3}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TEAM_RE = re.compile(r"^(.+?)(\(([+-]?\d+)\))?VS(.+)$")
MAX_PAGINATION_PAGES = 20

WEEKDAY_PREFIX = {
    0: "周一",
    1: "周二",
    2: "周三",
    3: "周四",
    4: "周五",
    5: "周六",
    6: "周日",
}

OUTPUT_COLUMNS = [
    "issue_date",
    "match_date",
    "match_no",
    "league",
    "home_team",
    "away_team",
    "handicap",
    "half_score",
    "full_score",
    "half_time_score",
    "full_time_score",
    "spf_win",
    "spf_draw",
    "spf_lose",
    "source_url",
    "scrape_time",
]

HEADER_KEYWORDS = ["赛事日期", "赛事编号", "联赛", "主队", "客队", "半场比分", "全场比分", "胜", "平", "负"]


def _target_weekday_prefix(issue_date: str) -> str:
    d = datetime.strptime(issue_date, "%Y-%m-%d").date()
    return WEEKDAY_PREFIX[d.weekday()]


def _debug_snapshot_path(issue_date: str, page_no: int) -> Path:
    debug_dir = settings.base_dir / "data" / "raw" / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    return debug_dir / f"result_query_{issue_date}_page{page_no}.html"


def _save_page_snapshot(page: Any, issue_date: str, page_no: int) -> Path | None:
    try:
        content = page.content()
        path = _debug_snapshot_path(issue_date, page_no)
        path.write_text(content, encoding="utf-8")
        logger.info("已保存查询快照 path=%s html_len=%s", path, len(content))
        return path
    except Exception:
        logger.exception("保存查询快照失败")
        return None


def _scroll_to_bottom(page: Any) -> int:
    stable_count = 0
    rounds = 0
    last_height = -1

    while stable_count < 2 and rounds < 40:
        rounds += 1
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1200)
        new_height = page.evaluate("document.body.scrollHeight")
        if new_height == last_height:
            stable_count += 1
        else:
            stable_count = 0
            last_height = new_height

    logger.info("页面滚动轮数=%s", rounds)
    return rounds


def _parse_team_text(team_text: str) -> tuple[str, str, str]:
    text = str(team_text or "").strip().replace(" ", "")
    m = TEAM_RE.match(text)
    if not m:
        return text, "", ""
    home_team = (m.group(1) or "").strip()
    handicap = (m.group(3) or "").strip()
    away_team = (m.group(4) or "").strip()
    return home_team, handicap, away_team


def _row_to_record(issue_date: str, cols: list[str]) -> dict[str, str]:
    team_text = cols[3]
    home_team, handicap, away_team = _parse_team_text(team_text)
    scrape_time = datetime.utcnow().isoformat()

    return {
        "issue_date": issue_date,
        "match_date": cols[0],
        "match_no": cols[1],
        "league": cols[2],
        "home_team": home_team,
        "away_team": away_team,
        "handicap": handicap,
        "half_score": cols[4],
        "full_score": cols[5],
        "half_time_score": cols[4],
        "full_time_score": cols[5],
        "spf_win": cols[6],
        "spf_draw": cols[7],
        "spf_lose": cols[8],
        "source_url": ZQSGKJ_URL,
        "scrape_time": scrape_time,
    }


def _table_signature(page: Any, table_locator: Any | None = None) -> str:
    text = ""
    try:
        if table_locator is not None:
            text = table_locator.inner_text(timeout=5000)
        else:
            text = page.locator("table").first.inner_text(timeout=5000)
    except Exception:
        text = ""
    if not text:
        try:
            text = page.locator("tbody").first.inner_text(timeout=5000)
        except Exception:
            text = ""
    return hashlib.md5(text.encode("utf-8", errors="ignore")).hexdigest()


def _extract_current_page_no(page: Any) -> str:
    selectors = [
        ".pagination .active",
        ".page .active",
        ".pager .active",
        "a.cur",
        "span.cur",
        "li.active",
    ]
    for selector in selectors:
        try:
            node = page.locator(selector).first
            if node.count() > 0:
                text = node.inner_text(timeout=1000).strip()
                if text:
                    return text
        except Exception:
            continue
    return "?"


def _extract_total_pages_hint(page: Any) -> int | None:
    selectors = [
        ".pagination a",
        ".page a",
        ".pager a",
        "a[href*='page']",
    ]
    values: list[int] = []
    for selector in selectors:
        try:
            nodes = page.locator(selector)
            n = nodes.count()
        except Exception:
            n = 0
        for i in range(n):
            try:
                txt = nodes.nth(i).inner_text(timeout=500).strip()
            except Exception:
                continue
            if txt.isdigit():
                values.append(int(txt))
    if not values:
        return None
    return max(values)


def _row_cells_text(tr: Any, selectors: list[str]) -> list[str]:
    for selector in selectors:
        try:
            nodes = tr.locator(selector)
            cnt = nodes.count()
        except Exception:
            cnt = 0
        if cnt > 0:
            return [nodes.nth(i).inner_text(timeout=800).strip() for i in range(cnt)]
    return []


def _get_first_row_cells(table: Any) -> list[str]:
    candidates = ["thead tr", "tbody tr", "tr"]
    for row_selector in candidates:
        try:
            rows = table.locator(row_selector)
            count = rows.count()
        except Exception:
            count = 0
        if count <= 0:
            continue
        first = rows.nth(0)
        cells = _row_cells_text(first, ["th", "td"])
        if cells:
            return cells
    return []


def _is_header_table(first_row_cells: list[str]) -> bool:
    if not first_row_cells:
        return False
    text = " ".join(first_row_cells)
    hit = sum(1 for kw in HEADER_KEYWORDS if kw in text)
    return hit >= 5


def _is_data_table(first_row_cells: list[str]) -> bool:
    if len(first_row_cells) < 2:
        return False
    first_col = str(first_row_cells[0]).strip()
    second_col = str(first_row_cells[1]).strip()
    return bool(DATE_RE.match(first_col) and MATCH_NO_RE.match(second_col))


def _collect_table_debug(page: Any) -> list[dict[str, Any]]:
    table_infos: list[dict[str, Any]] = []
    tables = page.locator("table")
    try:
        table_count = tables.count()
    except Exception:
        table_count = 0

    for idx in range(table_count):
        table = tables.nth(idx)
        first_cells = _get_first_row_cells(table)
        first_text = " | ".join(first_cells)
        samples: list[str] = []
        try:
            rows = table.locator("tbody tr")
            rc = rows.count()
            for i in range(min(3, rc)):
                row_cells = _row_cells_text(rows.nth(i), ["td", "th"])
                samples.append(" | ".join(row_cells[:2]))
        except Exception:
            pass

        info = {
            "index": idx,
            "first_cells": first_cells,
            "first_text": first_text,
            "samples": samples,
            "is_header": _is_header_table(first_cells),
            "is_data": _is_data_table(first_cells),
        }
        table_infos.append(info)

    logger.info("查询后命中的 table 数量=%s", table_count)
    for info in table_infos:
        logger.info(
            "table[%s] is_header=%s is_data=%s first_row=%s sample_rows=%s",
            info["index"],
            info["is_header"],
            info["is_data"],
            info["first_text"],
            info["samples"],
        )
    return table_infos


def _select_header_and_data_table(page: Any) -> tuple[Any | None, Any | None, int | None, int | None]:
    infos = _collect_table_debug(page)
    if not infos:
        return None, None, None, None

    header_idx: int | None = None
    data_idx: int | None = None

    for info in infos:
        if info["is_header"] and header_idx is None:
            header_idx = int(info["index"])

    # 优先选择“在 header 表后面的 data 表”
    for info in infos:
        if info["is_data"]:
            idx = int(info["index"])
            if header_idx is not None and idx > header_idx:
                data_idx = idx
                break
            if data_idx is None:
                data_idx = idx

    header_table = page.locator("table").nth(header_idx) if header_idx is not None else None
    data_table = page.locator("table").nth(data_idx) if data_idx is not None else None

    logger.info("识别到的表头表 index=%s", header_idx)
    logger.info("识别到的数据表 index=%s", data_idx)
    return header_table, data_table, header_idx, data_idx


def _parse_rows_from_data_table(data_table: Any, issue_date: str) -> list[dict[str, str]]:
    rows_out: list[dict[str, str]] = []
    body_rows = data_table.locator("tbody tr")
    try:
        row_count = body_rows.count()
    except Exception:
        row_count = 0

    if row_count == 0:
        body_rows = data_table.locator("tr")
        try:
            row_count = body_rows.count()
        except Exception:
            row_count = 0

    # 输出前3行的首列/第二列用于日志
    first_three: list[tuple[str, str]] = []

    for i in range(row_count):
        tr = body_rows.nth(i)
        td_nodes = tr.locator("td")
        td_count = td_nodes.count()
        if td_count < 9:
            continue
        cols = [td_nodes.nth(j).inner_text().strip() for j in range(td_count)]
        first_col = cols[0] if len(cols) > 0 else ""
        second_col = cols[1] if len(cols) > 1 else ""
        if len(first_three) < 3:
            first_three.append((first_col, second_col))

        match_no = second_col
        if not MATCH_NO_RE.match(match_no):
            continue

        try:
            rows_out.append(_row_to_record(issue_date, cols))
        except Exception:
            logger.exception("解析单行失败，已跳过 row_index=%s", i)

    logger.info("数据表前3行首列/第二列=%s", first_three)
    return rows_out


def _parse_current_page_rows(page: Any, issue_date: str) -> tuple[list[dict[str, str]], str]:
    header_table, data_table, header_idx, data_idx = _select_header_and_data_table(page)

    # 两段式：header + data
    if header_table is not None and data_table is not None:
        rows = _parse_rows_from_data_table(data_table, issue_date)
        logger.info("两段式解析完成 header_idx=%s data_idx=%s 解析比赛行数=%s", header_idx, data_idx, len(rows))
        return rows, f"two_stage(header={header_idx},data={data_idx})"

    # 回退：单table混合结构
    if data_table is not None:
        rows = _parse_rows_from_data_table(data_table, issue_date)
        logger.info("回退单表解析完成 data_idx=%s 解析比赛行数=%s", data_idx, len(rows))
        return rows, f"single_table(data={data_idx})"

    return [], "no_result_table"


def _first_match_no(rows: list[dict[str, str]]) -> str:
    if not rows:
        return ""
    return str(rows[0].get("match_no", "") or "").strip()


def _extract_matchlist_state(page: Any) -> dict[str, Any]:
    state: dict[str, Any] = {
        "first_date": "",
        "first_match_no": "",
        "match_count": 0,
        "html_digest": "",
        "html_excerpt": "",
        "update_time": "",
    }
    try:
        state = page.evaluate(
            r"""
            () => {
                const out = {
                    first_date: "",
                    first_match_no: "",
                    match_count: 0,
                    html_digest: "",
                    html_excerpt: "",
                    update_time: "",
                };
                const wrap = document.querySelector("#matchList");
                if (!wrap) return out;

                const html = wrap.innerHTML || "";
                out.match_count = wrap.querySelectorAll("tr").length;
                out.html_excerpt = html.replace(/\s+/g, " ").slice(0, 160);
                let hash = 0;
                for (let i = 0; i < html.length; i++) {
                    hash = ((hash << 5) - hash) + html.charCodeAt(i);
                    hash |= 0;
                }
                out.html_digest = String(hash);

                const rows = wrap.querySelectorAll("tr");
                for (const tr of rows) {
                    const cells = tr.querySelectorAll("td,th");
                    if (cells.length >= 2) {
                        const c1 = (cells[0].textContent || "").trim();
                        const c2 = (cells[1].textContent || "").trim();
                        if (/^\d{4}-\d{2}-\d{2}$/.test(c1) && /^周[一二三四五六日]\d{3}$/.test(c2)) {
                            out.first_date = c1;
                            out.first_match_no = c2;
                            break;
                        }
                    }
                }

                const wholeText = document.body?.innerText || "";
                const m = wholeText.match(/更新时间[:：]?\s*([0-9:\-\s]{5,})/);
                if (m && m[0]) out.update_time = m[0].trim();
                return out;
            }
            """
        )
    except Exception:
        logger.exception("提取#matchList状态失败")
    return state


def _wait_matchlist_updated(page: Any, old_state: dict[str, Any], timeout_ms: int = 14000) -> tuple[bool, dict[str, Any]]:
    waited = 0
    interval = 500
    while waited < timeout_ms:
        page.wait_for_timeout(interval)
        waited += interval
        new_state = _extract_matchlist_state(page)
        changed = (
            new_state.get("html_digest") != old_state.get("html_digest")
            or new_state.get("first_date") != old_state.get("first_date")
            or new_state.get("first_match_no") != old_state.get("first_match_no")
            or int(new_state.get("match_count", 0) or 0) != int(old_state.get("match_count", 0) or 0)
        )
        if changed:
            return True, new_state
    return False, _extract_matchlist_state(page)


def _submit_query_with_js_priority(page: Any, start_date: str, end_date: str) -> tuple[bool, bool, str]:
    js_set_ok = False
    click_submit_ok = False
    submit_mode = "none"

    try:
        set_ret = page.evaluate(
            """
            ([startDate, endDate]) => {
                const s = document.querySelector("#start_date");
                const e = document.querySelector("#end_date");
                if (!s || !e) return false;
                s.value = startDate;
                e.value = endDate;
                s.dispatchEvent(new Event("input", { bubbles: true }));
                s.dispatchEvent(new Event("change", { bubbles: true }));
                e.dispatchEvent(new Event("input", { bubbles: true }));
                e.dispatchEvent(new Event("change", { bubbles: true }));
                return true;
            }
            """,
            [start_date, end_date],
        )
        js_set_ok = bool(set_ret)
    except Exception:
        logger.exception("JS设定查询日期失败")

    try:
        click_ret = page.evaluate(
            """
            () => {
                if (typeof click_submit === "function") {
                    click_submit();
                    return "click_submit";
                }
                return "no_click_submit";
            }
            """
        )
        if click_ret == "click_submit":
            click_submit_ok = True
            submit_mode = "click_submit"
    except Exception:
        logger.exception("调用click_submit()失败")

    if not click_submit_ok:
        try:
            page.get_by_text("开始查询").first.click(timeout=5000)
            submit_mode = "button_click"
        except Exception:
            try:
                page.locator("input[type='button'][value*='查询'],button:has-text('查询')").first.click(timeout=5000)
                submit_mode = "button_click"
            except Exception:
                submit_mode = "submit_failed"

    return js_set_ok, click_submit_ok, submit_mode


def _find_next_button(page: Any) -> Any | None:
    next_selectors = [
        "a:has-text('下一页')",
        "button:has-text('下一页')",
        "a:has-text('下页')",
        "button:has-text('下页')",
        "a[aria-label*='下一页']",
        "button[aria-label*='下一页']",
        "a[title*='下一页']",
        "button[title*='下一页']",
        ".pagination a:has-text('>')",
        ".page a:has-text('>')",
        "li.next a",
        "a[rel='next']",
    ]
    for selector in next_selectors:
        try:
            loc = page.locator(selector).first
            if loc.count() > 0 and loc.is_visible():
                class_name = (loc.get_attribute("class") or "").lower()
                aria_disabled = (loc.get_attribute("aria-disabled") or "").lower()
                if "disabled" in class_name or aria_disabled in {"true", "1"}:
                    continue
                return loc
        except Exception:
            continue
    return None


def _click_next_page(page: Any, previous_signature: str, before_first_match_no: str) -> tuple[bool, str, str]:
    next_btn = _find_next_button(page)
    if next_btn is None:
        logger.info("分页识别：未找到下一页控件")
        return False, "", ""

    logger.info("分页识别：找到下一页控件，准备点击")
    try:
        next_btn.scroll_into_view_if_needed(timeout=2000)
    except Exception:
        pass

    try:
        next_btn.click(timeout=5000)
    except Exception:
        try:
            next_btn.click(force=True, timeout=5000)
        except Exception:
            logger.warning("点击下一页失败，停止翻页")
            return False, "", ""

    changed = False
    after_signature = ""
    for _ in range(12):
        page.wait_for_timeout(600)
        after_signature = _table_signature(page)
        if after_signature and after_signature != previous_signature:
            changed = True
            break

    page_rows_after, _ = _parse_current_page_rows(page, issue_date="")
    after_first_match_no = _first_match_no(page_rows_after)
    logger.info(
        "翻页前后首条match_no before=%s after=%s 页面内容变化=%s",
        before_first_match_no,
        after_first_match_no,
        changed,
    )

    if not changed and (after_first_match_no == before_first_match_no):
        logger.warning("点击下一页后页面内容未变化，停止翻页，避免死循环")
        return False, after_first_match_no, after_signature

    return True, after_first_match_no, after_signature


def _dedup_records(records: list[dict[str, str]]) -> list[dict[str, str]]:
    buckets: dict[tuple[str, str, str, str], dict[str, str]] = {}
    for r in records:
        key = (
            str(r.get("issue_date", "") or "").strip(),
            str(r.get("match_no", "") or "").strip(),
            str(r.get("home_team", "") or "").strip(),
            str(r.get("away_team", "") or "").strip(),
        )
        buckets[key] = r
    return list(buckets.values())


def fetch_zqsgkj_matches(issue_date: str) -> list[dict[str, str]]:
    from playwright.sync_api import sync_playwright

    start_date = issue_date
    end_date = (datetime.strptime(issue_date, "%Y-%m-%d").date() + timedelta(days=1)).isoformat()
    target_prefix = _target_weekday_prefix(issue_date)

    logger.info("开始抓取历史赛果 issue_date=%s", issue_date)
    logger.info("查询日期范围 start_date=%s end_date=%s", start_date, end_date)
    logger.info("target_weekday_prefix=%s", target_prefix)

    all_rows: list[dict[str, str]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=settings.playwright_headless)
        context = browser.new_context(user_agent=settings.user_agent)
        page = context.new_page()

        page.goto(ZQSGKJ_URL, wait_until="domcontentloaded", timeout=settings.request_timeout * 1000)
        old_state = _extract_matchlist_state(page)
        logger.info(
            "查询前状态 first_date=%s first_match_no=%s match_count=%s html_excerpt=%s",
            old_state.get("first_date"),
            old_state.get("first_match_no"),
            old_state.get("match_count"),
            old_state.get("html_excerpt"),
        )

        js_set_ok, click_submit_ok, submit_mode = _submit_query_with_js_priority(page, start_date, end_date)
        page.wait_for_timeout(1200)
        changed, new_state = _wait_matchlist_updated(page, old_state, timeout_ms=15000)

        if not changed:
            logger.warning("首次提交后结果未变化，触发二次click_submit重试")
            try:
                page.evaluate(
                    """
                    () => {
                        if (typeof click_submit === "function") {
                            click_submit();
                            return true;
                        }
                        return false;
                    }
                    """
                )
            except Exception:
                logger.exception("二次调用click_submit失败")
            page.wait_for_timeout(1000)
            changed, new_state = _wait_matchlist_updated(page, old_state, timeout_ms=10000)

        logger.info(
            "查询后状态 js_set_ok=%s click_submit_ok=%s submit_mode=%s changed=%s new_first_date=%s new_first_match_no=%s new_match_count=%s update_time=%s html_excerpt=%s",
            js_set_ok,
            click_submit_ok,
            submit_mode,
            changed,
            new_state.get("first_date"),
            new_state.get("first_match_no"),
            new_state.get("match_count"),
            new_state.get("update_time"),
            new_state.get("html_excerpt"),
        )

        if not changed:
            logger.warning("日期查询未生效：#matchList在两次提交后仍未变化，停止后续过滤链路")
            browser.close()
            return []

        page.wait_for_load_state("networkidle", timeout=max(12000, settings.request_timeout * 1000))

        _save_page_snapshot(page, issue_date, page_no=1)
        total_pages_hint = _extract_total_pages_hint(page)
        logger.info("识别到总分页数(提示)=%s", total_pages_hint if total_pages_hint is not None else "未知")

        visited_signatures: set[str] = set()

        for page_index in range(1, MAX_PAGINATION_PAGES + 1):
            try:
                current_page_no = _extract_current_page_no(page)
                logger.info("抓取第%s页(页码标识=%s)", page_index, current_page_no)

                _scroll_to_bottom(page)
                page_rows, parse_hint = _parse_current_page_rows(page, issue_date)
                logger.info("抓取第%s页，原始比赛行数=%s parse_hint=%s", page_index, len(page_rows), parse_hint)

                if page_index == 1 and len(page_rows) == 0:
                    logger.warning("第1页解析为0行，触发增强重试与候选表重识别")
                    page.wait_for_timeout(2500)
                    _save_page_snapshot(page, issue_date, page_no=1)
                    _scroll_to_bottom(page)
                    page_rows_retry, parse_hint_retry = _parse_current_page_rows(page, issue_date)
                    logger.info(
                        "第1页重试后原始比赛行数=%s parse_hint=%s",
                        len(page_rows_retry),
                        parse_hint_retry,
                    )
                    if len(page_rows_retry) > len(page_rows):
                        page_rows = page_rows_retry

                all_rows.extend(page_rows)

                signature = _table_signature(page)
                if signature in visited_signatures:
                    logger.warning("当前页内容签名重复，停止翻页，避免死循环")
                    break
                visited_signatures.add(signature)

                before_first_no = _first_match_no(page_rows)

                if page_index >= MAX_PAGINATION_PAGES:
                    logger.warning("达到最大翻页保护上限=%s，停止翻页", MAX_PAGINATION_PAGES)
                    break

                moved, after_first_no, after_signature = _click_next_page(page, signature, before_first_no)
                if not moved:
                    logger.info("未检测到可用下一页或翻页无变化，翻页结束")
                    break

                page.wait_for_load_state("networkidle", timeout=max(9000, settings.request_timeout * 1000))
                logger.info(
                    "翻页成功：before_first_match_no=%s after_first_match_no=%s signature_changed=%s",
                    before_first_no,
                    after_first_no,
                    bool(after_signature and after_signature != signature),
                )
            except Exception:
                logger.exception("解析分页时发生异常，已停止后续翻页")
                break

        browser.close()

    logger.info("全部分页合并后比赛行数=%s", len(all_rows))

    prefix_set = sorted(
        {
            str(r.get("match_no", "") or "").strip()[:2]
            for r in all_rows
            if str(r.get("match_no", "") or "").strip()
        }
    )
    has_target_prefix = any(str(r.get("match_no", "") or "").startswith(target_prefix) for r in all_rows)
    if not has_target_prefix:
        logger.warning(
            "前缀不匹配，疑似未切换到目标日期：target_weekday_prefix=%s 当前抓取到的前缀集合=%s",
            target_prefix,
            prefix_set,
        )

    deduped = _dedup_records(all_rows)
    logger.info("去重后比赛数=%s", len(deduped))

    filtered = [r for r in deduped if str(r.get("match_no", "")).startswith(target_prefix)]
    logger.info("weekday 前缀过滤后的比赛数=%s", len(filtered))

    logger.info("去重后最终比赛数=%s", len(filtered))
    return filtered


def save_zqsgkj_results(issue_date: str, records: list[dict[str, str]], base_dir: Path | None = None) -> tuple[Path, Path]:
    root = base_dir or settings.base_dir
    raw_path = root / "data" / "raw" / f"{issue_date}_zqsgkj_results.json"
    csv_path = root / "data" / "processed" / f"{issue_date}_zqsgkj_results.csv"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    with raw_path.open("w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        for r in records:
            writer.writerow({k: r.get(k, "") for k in OUTPUT_COLUMNS})

    logger.info("最终写入条数=%s", len(records))
    return raw_path, csv_path
