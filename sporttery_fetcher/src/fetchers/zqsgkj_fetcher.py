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
from src.domain.match_time import infer_issue_date_from_kickoff

logger = get_logger("zqsgkj_fetcher")

ZQSGKJ_URL = "https://www.sporttery.cn/jc/zqsgkj/"

# 多 URL 候选：lottery.gov.cn 优先，sporttery.cn 兜底
_RESULT_CANDIDATE_URLS: list[str] = []  # 延迟初始化，避免循环导入
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

    match_date = cols[0]
    inferred_issue_date = infer_issue_date_from_kickoff(f"{match_date} 12:00") if match_date else None

    return {
        "issue_date": issue_date,
        "issue_date_inferred": inferred_issue_date,
        "issue_date_source": "query_param",
        "match_date": match_date,
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
        "li.u-pg3 span",
        "li.u-pg3",
    ]
    for selector in selectors:
        try:
            node = page.locator(selector).first
            if node.count() > 0:
                text = node.inner_text(timeout=1000).strip()
                if text and text.isdigit():
                    return text
        except Exception:
            continue
    return "?"


def _extract_total_pages_hint(page: Any) -> int | None:
    selectors = [
        "li.u-pg2 a",
        "li.u-pg4 a",
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


def _wait_for_form_ready(page: Any, timeout_ms: int = 15000) -> bool:
    """等待SPA动态注入的表单就绪（#sgkj_991 内出现 input 元素）。"""
    # 先等待 #sgkj_991 容器本身
    try:
        page.wait_for_selector("#sgkj_991", timeout=timeout_ms)
    except Exception:
        logger.warning("等待 #sgkj_991 超时，可能是SPA加载失败")
        # 诊断：记录页面实际 URL 和关键容器，帮助排查结构差异
        try:
            actual_url = page.url
            body_excerpt = page.evaluate(
                "() => document.body ? document.body.innerHTML.slice(0, 800) : '(no body)'"
            )
            containers = page.evaluate(
                "() => ['#sgkj_991','#matchList','.m-tab','.m-form'].map(s => "
                "({sel:s, found:!!document.querySelector(s)}))"
            )
            logger.warning(
                "SPA诊断 actual_url=%s containers=%s body_excerpt=%s",
                actual_url, containers, body_excerpt,
            )
        except Exception as diag_exc:
            logger.warning("SPA诊断失败 err=%s", diag_exc)

    # 再等待容器内的 input 元素
    for selector in ["#sgkj_991 input", "#sgkj_991 form", "input[id*='date']", "input[type='text']"]:
        try:
            page.wait_for_selector(selector, timeout=6000)
            logger.info("表单就绪：检测到 selector=%s", selector)
            return True
        except Exception:
            continue

    logger.warning("表单等待超时：未找到任何 input 元素，后续可能无法填写日期")
    return False


def _diagnose_date_inputs(page: Any) -> list[dict[str, Any]]:
    """扫描页面上所有可能的日期输入控件，用于调试 js_set_ok=False 场景。"""
    try:
        return page.evaluate(
            r"""
            () => {
                const inputs = Array.from(document.querySelectorAll("input"));
                return inputs.map(el => ({
                    id: el.id || "",
                    name: el.name || "",
                    type: el.type || "",
                    placeholder: el.placeholder || "",
                    value: el.value || "",
                    className: el.className || "",
                })).filter(i =>
                    i.type === "text" || i.type === "date" ||
                    /date|start|end|begin/i.test(i.id + i.name + i.placeholder)
                ).slice(0, 10);
            }
            """
        )
    except Exception:
        return []


def _fill_date_input(page: Any, selectors: list[str], value: str) -> bool:
    """尝试多种方式填写日期输入框，返回是否成功。

    优先使用 jQuery UI Datepicker API（网站实际使用的控件），
    再回退到 Playwright fill() 和 JS 直接赋值。
    """
    for sel in selectors:
        # 1) jQuery UI Datepicker API — 网站使用 jquery-ui-timepicker-addon.js
        try:
            ok = page.evaluate(
                """
                ([sel, val]) => {
                    if (typeof $ === "undefined" || typeof $.fn.datepicker === "undefined") return false;
                    const el = $(sel);
                    if (!el.length) return false;
                    try {
                        el.datepicker("setDate", val);
                        el.trigger("input").trigger("change").trigger("blur");
                        return el.val() !== "";
                    } catch(e) {
                        el.val(val).trigger("input").trigger("change").trigger("blur");
                        return el.val() !== "";
                    }
                }
                """,
                [sel, value],
            )
            if ok:
                logger.info("jQuery datepicker setDate 成功 sel=%s val=%s", sel, value)
                return True
        except Exception:
            pass

        # 2) Playwright fill()
        try:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible():
                loc.triple_click(timeout=2000)
                loc.fill(value, timeout=2000)
                loc.dispatch_event("input")
                loc.dispatch_event("change")
                actual = loc.input_value(timeout=1000)
                if value in actual or actual in value:
                    return True
        except Exception:
            pass

        # 3) JS 直接赋值 + 事件（兜底）
        try:
            ok = page.evaluate(
                """
                ([sel, val]) => {
                    const el = document.querySelector(sel);
                    if (!el) return false;
                    const nativeInputSetter = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, "value"
                    )?.set;
                    if (nativeInputSetter) nativeInputSetter.call(el, val);
                    else el.value = val;
                    el.dispatchEvent(new Event("input",  { bubbles: true }));
                    el.dispatchEvent(new Event("change", { bubbles: true }));
                    el.dispatchEvent(new Event("blur",   { bubbles: true }));
                    return el.value !== "";
                }
                """,
                [sel, value],
            )
            if ok:
                return True
        except Exception:
            pass

    return False


def _submit_query_with_js_priority(page: Any, start_date: str, end_date: str) -> tuple[bool, bool, str]:
    js_set_ok = False
    click_submit_ok = False
    submit_mode = "none"

    # 先诊断页面上有哪些日期输入框（SPA内容加载后）
    date_inputs = _diagnose_date_inputs(page)
    logger.info("页面日期输入框诊断结果=%s", date_inputs)

    # 构建候选选择器：先放从诊断结果中动态发现的 ID，再放静态备选
    start_selectors: list[str] = []
    end_selectors: list[str] = []

    # 根据诊断结果推断：诊断列表第1个为 start，第2个为 end（常见布局）
    for i, info in enumerate(date_inputs[:4]):
        el_id = info.get("id", "")
        el_name = info.get("name", "")
        if el_id:
            sel = f"#{el_id}"
            if i == 0:
                start_selectors.insert(0, sel)
            elif i == 1:
                end_selectors.insert(0, sel)
            else:
                start_selectors.append(sel)
                end_selectors.append(sel)
        if el_name:
            sel = f"[name='{el_name}']"
            if i == 0:
                start_selectors.append(sel)
            elif i == 1:
                end_selectors.append(sel)

    # 静态备选选择器
    start_selectors += [
        "#start_date", "#startDate", "#queryStartDate", "#beginDate",
        "#sgkj_991 input[id*='start']", "#sgkj_991 input[name*='start']",
        "input[id*='start']", "input[name*='start']", "input[name*='begin']",
        "input[placeholder*='开始']", "input[placeholder*='起始']",
    ]
    end_selectors += [
        "#end_date", "#endDate", "#queryEndDate",
        "#sgkj_991 input[id*='end']", "#sgkj_991 input[name*='end']",
        "input[id*='end']", "input[name*='end']",
        "input[placeholder*='结束']", "input[placeholder*='截止']",
    ]

    start_ok = _fill_date_input(page, start_selectors, start_date)
    end_ok = _fill_date_input(page, end_selectors, end_date)
    js_set_ok = start_ok and end_ok
    if not start_ok:
        logger.warning("开始日期填写失败，将使用 URL 参数兜底")
    if not end_ok:
        logger.warning("结束日期填写失败，将使用 URL 参数兜底")

    page.wait_for_timeout(300)

    # 尝试方法1: 调用页面全局 click_submit() / query() / search()
    for fn_name in ("click_submit", "query", "search", "doQuery", "doSearch"):
        try:
            click_ret = page.evaluate(
                f"""
                () => {{
                    if (typeof {fn_name} === "function") {{
                        {fn_name}();
                        return "{fn_name}";
                    }}
                    return "";
                }}
                """
            )
            if click_ret:
                click_submit_ok = True
                submit_mode = f"js_{fn_name}"
                logger.info("通过全局函数提交查询 fn=%s", fn_name)
                break
        except Exception:
            pass

    # 方法2: 点击查询按钮
    if not click_submit_ok:
        submit_btn_selectors = [
            "#sgkj_991 input[type='button']",
            "#sgkj_991 button",
            "input[type='button'][value*='查询']",
            "button:has-text('查询')",
            "input[value*='查询']",
            "a:has-text('查询')",
            "input[type='submit']",
        ]
        for btn_sel in submit_btn_selectors:
            try:
                btn = page.locator(btn_sel).first
                if btn.count() > 0 and btn.is_visible():
                    btn.click(timeout=5000)
                    click_submit_ok = True
                    submit_mode = f"btn:{btn_sel}"
                    logger.info("通过按钮提交查询 selector=%s", btn_sel)
                    break
            except Exception:
                continue

    if not click_submit_ok:
        submit_mode = "submit_failed"
        logger.warning("所有提交方式均失败")

    return js_set_ok, click_submit_ok, submit_mode


def _find_next_button(page: Any) -> Any | None:
    """查找下一页按钮。

    支持：
    - 实际页面 li.u-pg2 a（当前页+1 的数字链接）
    - pagerN "下N页"/"下一页" 文字按钮
    - 其他常见分页库
    """
    # ── 实际页面结构：li.u-pg2 a（非当前页的数字链接） ──
    # 先确定当前页码，再找当前页+1 的链接
    cur_page = 1
    try:
        cur_el = page.locator("li.u-pg3 span, li.u-pg3").first
        if cur_el.count() > 0:
            txt = cur_el.inner_text(timeout=1000).strip()
            if txt.isdigit():
                cur_page = int(txt)
    except Exception:
        pass

    next_page = cur_page + 1
    try:
        candidates = page.locator("li.u-pg2 a")
        n = candidates.count()
        for i in range(n):
            loc = candidates.nth(i)
            txt = loc.inner_text(timeout=500).strip()
            if txt.isdigit() and int(txt) == next_page and loc.is_visible():
                logger.info("找到 li.u-pg2 下一页链接 page=%s", next_page)
                return loc
    except Exception:
        pass

    # ── 固定文字选择器 ──
    fixed_selectors = [
        "a:has-text('下一页')",
        "button:has-text('下一页')",
        "a:has-text('下页')",
        "button:has-text('下页')",
        "a[aria-label*='下一页']",
        "a[title*='下一页']",
        ".pagination a:has-text('>')",
        "li.next a",
        "a[rel='next']",
    ]
    for selector in fixed_selectors:
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


def _click_pagern_next_via_js(page: Any) -> tuple[bool, int]:
    """JS 兜底翻页：适配实际页面的 jcSgkj.getDataClickPage() 和 li.u-pg3/u-pg2 结构。

    当 _find_next_button() 返回 None 时调用（应对 DOM 不可见但 JS 可调用的情况）。
    返回 (success, next_page_no)。
    """
    try:
        result = page.evaluate(
            r"""
            () => {
                // 当前页：li.u-pg3 > span（实际页面结构）
                const curEl = document.querySelector('li.u-pg3 span') ||
                              document.querySelector('li.u-pg3');
                if (!curEl) return {ok: false, cur: 0, next: 0, reason: "no u-pg3"};
                const curNum = parseInt(curEl.textContent.trim(), 10);
                if (isNaN(curNum)) return {ok: false, cur: 0, next: 0, reason: "u-pg3 not numeric"};
                const nextNum = curNum + 1;

                // 方法1：调用页面 JS API jcSgkj.getDataClickPage(N)
                if (typeof jcSgkj !== "undefined" &&
                    typeof jcSgkj.getDataClickPage === "function") {
                    jcSgkj.getDataClickPage(nextNum);
                    return {ok: true, cur: curNum, next: nextNum, method: "jcSgkj"};
                }

                // 方法2：点击 li.u-pg2 a 中数字为 nextNum 的链接
                for (const a of document.querySelectorAll('li.u-pg2 a')) {
                    if (parseInt(a.textContent.trim(), 10) === nextNum) {
                        a.click();
                        return {ok: true, cur: curNum, next: nextNum, method: "click"};
                    }
                }

                return {ok: false, cur: curNum, next: nextNum, reason: "no link or jcSgkj"};
            }
            """
        )
        logger.info("JS兜底翻页结果=%s", result)
        return bool(result.get("ok")), int(result.get("next", 0))
    except Exception:
        logger.exception("JS兜底翻页异常")
        return False, 0


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


def _try_url_param_navigation(page: Any, start_date: str, end_date: str, base_url: str = ZQSGKJ_URL) -> bool:
    """尝试通过 URL 查询参数直接导航到目标日期范围，作为表单填写失败时的兜底方案。"""
    param_variants = [
        f"{base_url}?startDate={start_date}&endDate={end_date}",
        f"{base_url}?start_date={start_date}&end_date={end_date}",
        f"{base_url}?beginDate={start_date}&endDate={end_date}",
        f"{base_url}?queryStartDate={start_date}&queryEndDate={end_date}",
    ]
    for url in param_variants:
        try:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(2000)
            state = _extract_matchlist_state(page)
            first_date = state.get("first_date", "")
            if first_date and first_date == start_date:
                logger.info("URL参数导航成功 url=%s first_date=%s", url, first_date)
                return True
            logger.info("URL参数导航后首条日期=%s（期望=%s），继续尝试下一个", first_date, start_date)
        except Exception:
            logger.exception("URL参数导航失败 url=%s", url)
    return False


def _get_result_candidate_urls() -> list[str]:
    """延迟获取候选 URL 列表（避免模块加载时循环导入）。"""
    if not _RESULT_CANDIDATE_URLS:
        lottery_url = settings.lottery_result_url
        # sporttery.cn 首选（lottery.gov.cn 在某些网络环境下 SPA 无法加载）
        urls = [ZQSGKJ_URL, lottery_url]
        # 去重保序
        seen: set[str] = set()
        result = []
        for u in urls:
            if u and u not in seen:
                seen.add(u)
                result.append(u)
        return result
    return _RESULT_CANDIDATE_URLS


def fetch_zqsgkj_matches(issue_date: str) -> list[dict[str, str]]:
    """从多个候选 URL（lottery.gov.cn 优先，sporttery.cn 兜底）抓取历史赛果。"""
    candidate_urls = _get_result_candidate_urls()
    for url in candidate_urls:
        try:
            logger.info("尝试抓取赛果 url=%s issue_date=%s", url, issue_date)
            rows = _fetch_zqsgkj_from_url(issue_date, url)
            if rows:
                logger.info("赛果抓取成功 url=%s count=%s", url, len(rows))
                return rows
            logger.info("赛果抓取返回0条 url=%s，尝试下一个候选", url)
        except Exception as exc:
            logger.warning("赛果抓取异常 url=%s err=%s，尝试下一个候选", url, type(exc).__name__)
    logger.warning("所有候选 URL 均未返回赛果 issue_date=%s", issue_date)
    return []


def _fetch_zqsgkj_from_url(issue_date: str, base_url: str) -> list[dict[str, str]]:
    from playwright.sync_api import sync_playwright

    start_date = issue_date
    end_date = (datetime.strptime(issue_date, "%Y-%m-%d").date() + timedelta(days=1)).isoformat()

    logger.info("开始抓取历史赛果 issue_date=%s base_url=%s", issue_date, base_url)
    logger.info("查询日期范围 start_date=%s end_date=%s", start_date, end_date)

    all_rows: list[dict[str, str]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=settings.playwright_headless)
        context = browser.new_context(user_agent=settings.user_agent)
        page = context.new_page()

        page.goto(base_url, wait_until="domcontentloaded", timeout=settings.request_timeout * 1000)

        # 等待SPA通过 commonV1Fun.loadHtml() 将表单注入 #sgkj_991
        form_ready = _wait_for_form_ready(page, timeout_ms=18000)
        logger.info("SPA表单就绪状态=%s", form_ready)

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

        # 仅在表单填写本身失败时才触发URL兜底；
        # 若 loaded_first_date 在查询窗口 [start_date, end_date] 内，说明查询已生效，无需兜底。
        loaded_first_date = new_state.get("first_date", "")
        in_window = bool(loaded_first_date) and start_date <= loaded_first_date <= end_date
        if in_window:
            logger.info(
                "查询成功：loaded_first_date=%s 在查询窗口 [%s, %s] 内，跳过URL兜底",
                loaded_first_date, start_date, end_date,
            )
        elif not js_set_ok:
            logger.warning(
                "表单日期填写失败（js_set_ok=False），尝试URL参数兜底导航",
            )
            url_ok = _try_url_param_navigation(page, start_date, end_date, base_url=base_url)
            if url_ok:
                changed = True
                new_state = _extract_matchlist_state(page)
                logger.info("URL参数兜底成功 new_first_date=%s", new_state.get("first_date"))
            else:
                logger.warning("URL参数兜底也未能定位到目标日期，继续使用当前页面数据（将依赖 match_date 字段过滤）")
        else:
            logger.warning(
                "表单提交后首条日期 loaded=%s 不在查询窗口内（期望范围 [%s, %s]），可能无当日赛事",
                loaded_first_date, start_date, end_date,
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

    deduped = _dedup_records(all_rows)
    logger.info("去重后比赛数=%s", len(deduped))

    # 赛果页已通过 issue_date 查询，这里不再按自然日(match_date)二次硬过滤，避免跨日误丢。
    # 特别是次日凌晨/上午场次依然属于前一销售日窗口，必须保留。
    logger.info("按 issue_date 查询后直接保留去重结果 issue_date=%s rows=%s", issue_date, len(deduped))
    if not deduped:
        logger.info("日期 %s 无可用赛果（可能当日无竞彩足球赛事）", issue_date)

    return deduped


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
