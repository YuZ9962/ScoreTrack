"""
从 https://zx.500.com/jczq/kaijiang.php?d=YYYY-MM-DD 抓取已结束比赛赛果。

页面 GBK 编码，SSR 渲染，无需 Playwright，直接 requests + BeautifulSoup 解析。
返回字段兼容 upsert_history_fetch_results / append_raw_results 所需格式。
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import requests
from bs4 import BeautifulSoup

from src.utils.logger import get_logger

logger = get_logger(__name__)

SOURCE_URL = "https://zx.500.com/jczq/kaijiang.php"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://www.500.com/",
}

# SPF / RQSPF 结果映射
_SPF_MAP = {"胜": "主胜", "平": "平", "负": "客胜"}
_RQSPF_MAP = {"胜": "让胜", "平": "让平", "负": "让负"}


def _parse_score(score_text: str) -> tuple[str, str]:
    """解析比分字段 '(0:1) 1:2' → half_time_score='0-1', full_time_score='1-2'。"""
    half_time = ""
    full_time = ""
    # 半场比分：括号内
    half_m = re.search(r"\((\d+)\s*[:：]\s*(\d+)\)", score_text)
    if half_m:
        half_time = f"{half_m.group(1)}-{half_m.group(2)}"
    # 全场比分：括号后的数字
    full_m = re.search(r"\)\s*(\d+)\s*[:：]\s*(\d+)", score_text)
    if full_m:
        full_time = f"{full_m.group(1)}-{full_m.group(2)}"
    return half_time, full_time


def _build_kickoff_time(time_text: str, issue_date: str) -> str | None:
    """'MM-DD HH:MM' + issue_date 年份 → 'YYYY-MM-DD HH:MM'。"""
    try:
        year = int(issue_date[:4])
        dt = datetime.strptime(f"{year}-{time_text.strip()}", "%Y-%m-%d %H:%M")
        issue_dt = datetime.strptime(issue_date, "%Y-%m-%d")
        # 跨年保护
        if (issue_dt - dt).days > 180:
            dt = dt.replace(year=year + 1)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return None


def fetch_500_results(issue_date: str, timeout: int = 15) -> list[dict[str, Any]]:
    """抓取指定 issue_date 的已结束赛果。

    返回列表字段：
        issue_date, match_no, league, home_team, away_team, handicap,
        kickoff_time, half_time_score, full_time_score,
        result_match (主胜/平/客胜), result_handicap (让胜/让平/让负),
        source_url, scrape_time
    """
    url = f"{SOURCE_URL}?d={issue_date}"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout)
        resp.encoding = "gbk"
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("500.com 赛果请求失败 url=%s err=%s", url, exc)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    # 过滤出数据行：至少 12 个 td，跳过表头（首列含"胜平负"关键字）
    all_rows = soup.select("tr")
    scrape_time = datetime.now().isoformat(timespec="seconds")
    out: list[dict[str, Any]] = []

    for row in all_rows:
        tds = row.find_all("td")
        if len(tds) < 12:
            continue
        texts = [td.get_text(strip=True) for td in tds]

        # 跳过表头行
        if "胜平负" in texts[0] or "竞彩" not in texts[0] and "周" not in texts[0]:
            continue

        match_no = texts[0]
        league = texts[1]
        time_text = texts[2]
        home_team = texts[3]
        handicap_raw = texts[4]   # "+1" / "-1"
        away_team = texts[5]
        score_text = texts[6]     # "(0:1) 1:2"
        spf_result = texts[8]     # 胜/平/负
        rqspf_result = texts[11]  # 胜/平/负

        # 让球值：直接取原始值（已是 +1/-1 格式）
        handicap = handicap_raw if re.match(r"^[+-]?\d+(\.\d+)?$", handicap_raw) else None

        half_time_score, full_time_score = _parse_score(score_text)
        result_match = _SPF_MAP.get(spf_result, "")
        result_handicap = _RQSPF_MAP.get(rqspf_result, "")
        kickoff_time = _build_kickoff_time(time_text, issue_date)

        out.append(
            {
                "issue_date": issue_date,
                "match_no": match_no,
                "league": league,
                "home_team": home_team,
                "away_team": away_team,
                "handicap": handicap,
                "kickoff_time": kickoff_time,
                "half_time_score": half_time_score,
                "full_time_score": full_time_score,
                "result_match": result_match,
                "result_handicap": result_handicap,
                "source_url": url,
                "scrape_time": scrape_time,
            }
        )

    logger.info("500.com 赛果 issue_date=%s 抓取到 %s 场", issue_date, len(out))
    return out
