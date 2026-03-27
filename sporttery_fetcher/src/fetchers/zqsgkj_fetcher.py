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


def _target_weekday_prefix(issue_date: str) -> str:
    d = datetime.strptime(issue_date, "%Y-%m-%d").date()
    return WEEKDAY_PREFIX[d.weekday()]


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


def _table_signature(page: Any) -> str:
    try:
        table_text = page.locator("table").first.inner_text(timeout=5000)
    except Exception:
        table_text = ""
    if not table_text:
        try:
            table_text = page.locator("tbody").first.inner_text(timeout=5000)
        except Exception:
            table_text = ""
    return hashlib.md5(table_text.encode("utf-8", errors="ignore")).hexdigest()


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


def _parse_current_page_rows(page: Any, issue_date: str) -> list[dict[str, str]]:
    page_rows: list[dict[str, str]] = []
    tr_nodes = page.locator("tr")
    total = tr_nodes.count()
    for i in range(total):
        tr = tr_nodes.nth(i)
        td_nodes = tr.locator("td")
        td_count = td_nodes.count()
        if td_count < 9:
            continue
        cols = [td_nodes.nth(j).inner_text().strip() for j in range(td_count)]
        match_no = cols[1] if len(cols) > 1 else ""
        if not MATCH_NO_RE.match(match_no):
            continue
        try:
            page_rows.append(_row_to_record(issue_date, cols))
        except Exception:
            logger.exception("解析单行失败，已跳过 row_index=%s", i)
    return page_rows


def _find_next_button(page: Any) -> Any | None:
    next_selectors = [
        "a:has-text('下一页')",
        "button:has-text('下一页')",
        "a:has-text('下页')",
        "button:has-text('下页')",
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
                text = (loc.inner_text(timeout=500) or "").strip()
                if text in {"", "下一页", "下页", ">", "›", "»"} or "下一页" in text or "下页" in text:
                    return loc
        except Exception:
            continue
    return None


def _click_next_page(page: Any, previous_signature: str) -> bool:
    next_btn = _find_next_button(page)
    if next_btn is None:
        return False

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
            return False

    # 等待页面变化（签名变化）
    changed = False
    for _ in range(12):
        page.wait_for_timeout(600)
        new_signature = _table_signature(page)
        if new_signature and new_signature != previous_signature:
            changed = True
            break

    if not changed:
        logger.warning("点击下一页后页面内容未变化，停止翻页，避免死循环")
        return False

    return True


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
        page.wait_for_timeout(1800)
        page.wait_for_load_state("networkidle", timeout=max(10000, settings.request_timeout * 1000))

        total_pages_hint = _extract_total_pages_hint(page)
        logger.info("识别到总分页数(提示)=%s", total_pages_hint if total_pages_hint is not None else "未知")

        visited_signatures: set[str] = set()

        for page_index in range(1, MAX_PAGINATION_PAGES + 1):
            try:
                current_page_no = _extract_current_page_no(page)
                logger.info("抓取第%s页(页码标识=%s)", page_index, current_page_no)

                _scroll_to_bottom(page)
                page_rows = _parse_current_page_rows(page, issue_date)
                logger.info("抓取第%s页，原始比赛行数=%s", page_index, len(page_rows))
                all_rows.extend(page_rows)

                signature = _table_signature(page)
                if signature in visited_signatures:
                    logger.warning("当前页内容签名重复，停止翻页，避免死循环")
                    break
                visited_signatures.add(signature)

                if page_index >= MAX_PAGINATION_PAGES:
                    logger.warning("达到最大翻页保护上限=%s，停止翻页", MAX_PAGINATION_PAGES)
                    break

                moved = _click_next_page(page, signature)
                if not moved:
                    logger.info("未检测到可用下一页或翻页无变化，翻页结束")
                    break

                page.wait_for_load_state("networkidle", timeout=max(8000, settings.request_timeout * 1000))
            except Exception:
                logger.exception("解析分页时发生异常，已停止后续翻页")
                break

        browser.close()

    logger.info("全部分页合并后比赛行数=%s", len(all_rows))

    filtered = [r for r in all_rows if str(r.get("match_no", "")).startswith(target_prefix)]
    logger.info("weekday 前缀过滤后的比赛数=%s", len(filtered))

    deduped = _dedup_records(filtered)
    logger.info("去重后最终比赛数=%s", len(deduped))
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
