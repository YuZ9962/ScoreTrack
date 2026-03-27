from __future__ import annotations

import csv
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


def fetch_zqsgkj_matches(issue_date: str) -> list[dict[str, str]]:
    from playwright.sync_api import sync_playwright

    start_date = issue_date
    end_date = (datetime.strptime(issue_date, "%Y-%m-%d").date() + timedelta(days=1)).isoformat()
    target_prefix = _target_weekday_prefix(issue_date)

    logger.info("查询日期范围 start_date=%s end_date=%s", start_date, end_date)
    logger.info("target_weekday_prefix=%s", target_prefix)

    rows: list[dict[str, str]] = []

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

        _scroll_to_bottom(page)

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
            if not match_no.startswith(target_prefix):
                continue

            rows.append(_row_to_record(issue_date, cols))

        browser.close()

    logger.info("抓到的总比赛行数=%s", len(rows))
    filtered = [r for r in rows if str(r.get("match_no", "")).startswith(target_prefix)]
    logger.info("weekday 前缀过滤后的比赛数=%s", len(filtered))
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
