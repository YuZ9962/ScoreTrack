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

TABLE_HINT_KEYWORDS = ["赛事编号", "主队", "客队", "全场比分", "胜", "平", "负"]


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


def _collect_table_debug(page: Any) -> list[dict[str, Any]]:
    table_infos: list[dict[str, Any]] = []
    tables = page.locator("table")
    try:
        table_count = tables.count()
    except Exception:
        table_count = 0

    for idx in range(table_count):
        table = tables.nth(idx)
        try:
            header = table.locator("thead").first.inner_text(timeout=800).strip()
        except Exception:
            header = ""
        if not header:
            try:
                first_row = table.locator("tr").first.inner_text(timeout=800).strip()
                header = first_row
            except Exception:
                header = ""

        samples: list[str] = []
        try:
            body_rows = table.locator("tbody tr")
            body_count = body_rows.count()
            for i in range(min(3, body_count)):
                samples.append(body_rows.nth(i).inner_text(timeout=800).strip())
        except Exception:
            try:
                rows = table.locator("tr")
                row_count = rows.count()
                for i in range(min(3, max(0, row_count - 1))):
                    samples.append(rows.nth(i + 1).inner_text(timeout=800).strip())
            except Exception:
                pass

        joined = f"{header} {' '.join(samples)}"
        score = sum(1 for kw in TABLE_HINT_KEYWORDS if kw in joined)
        table_infos.append({"index": idx, "header": header, "samples": samples, "score": score})

    logger.info("查询后命中的 table 数量=%s", table_count)
    for info in table_infos:
        logger.info(
            "table[%s] score=%s header=%s sample_rows=%s",
            info["index"],
            info["score"],
            info["header"],
            info["samples"],
        )
    return table_infos


def _select_results_table(page: Any) -> tuple[Any | None, int | None]:
    infos = _collect_table_debug(page)
    if not infos:
        return None, None

    best = sorted(infos, key=lambda x: (x["score"], len(x["samples"])), reverse=True)[0]
    if best["score"] <= 0:
        return None, None

    idx = int(best["index"])
    table = page.locator("table").nth(idx)
    logger.info("当前实际选中的 table 索引=%s score=%s", idx, best["score"])
    return table, idx


def _parse_rows_from_table(table: Any, issue_date: str) -> list[dict[str, str]]:
    rows_out: list[dict[str, str]] = []

    # 优先 tbody tr；若没有则退化到 tr
    row_locator = table.locator("tbody tr")
    try:
        row_count = row_locator.count()
    except Exception:
        row_count = 0

    if row_count == 0:
        row_locator = table.locator("tr")
        try:
            row_count = row_locator.count()
        except Exception:
            row_count = 0

    for i in range(row_count):
        tr = row_locator.nth(i)
        td_nodes = tr.locator("td")
        td_count = td_nodes.count()
        if td_count < 9:
            continue
        cols = [td_nodes.nth(j).inner_text().strip() for j in range(td_count)]
        match_no = cols[1] if len(cols) > 1 else ""
        if not MATCH_NO_RE.match(match_no):
            continue
        try:
            rows_out.append(_row_to_record(issue_date, cols))
        except Exception:
            logger.exception("解析单行失败，已跳过 row_index=%s", i)

    return rows_out


def _parse_current_page_rows(page: Any, issue_date: str) -> tuple[list[dict[str, str]], str]:
    table, table_idx = _select_results_table(page)
    if table is None:
        return [], "no_result_table"
    rows = _parse_rows_from_table(table, issue_date)
    return rows, f"table_index={table_idx}"


def _first_match_no(rows: list[dict[str, str]]) -> str:
    if not rows:
        return ""
    return str(rows[0].get("match_no", "") or "").strip()


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

    # 尝试解析点击后的首条 match_no，用于日志
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
        page.locator("#start_date").fill(start_date)
        page.locator("#end_date").fill(end_date)
        page.get_by_text("开始查询").first.click()
        page.wait_for_timeout(2200)
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

                # 首次解析为 0 时，做一次增强等待+重新识别+快照，不立即判定无数据
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

                # 第1页都没有有效行时，仍尝试一次下一页判断；若无变化则自然结束
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
