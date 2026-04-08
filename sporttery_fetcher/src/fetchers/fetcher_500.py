"""
从 https://trade.500.com/jczq/ 抓取竞彩足球赛事数据。

页面使用 GBK 编码的 SSR HTML，赛事行选择器为 tr.bet-tb-tr，
无需 JS 执行，直接 requests + BeautifulSoup 解析即可。
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import requests
from bs4 import BeautifulSoup

from src.domain.match_time import infer_issue_date_from_kickoff
from src.utils.logger import get_logger

logger = get_logger(__name__)

SOURCE_URL = "https://trade.500.com/jczq/"

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


def _parse_handicap(rang_text: str) -> str | None:
    """从 td-rang 文本提取让球值。

    示例输入：'单关0-1', '0-1', '0+1', '让球0+2', '0-0.5'
    对应输出：'-1', '-1', '+1', '+2', '-0.5'
    """
    m = re.search(r"0([+-]\d+(?:\.\d+)?)", rang_text)
    if m:
        return m.group(1)
    return None


def _build_kickoff_time(time_text: str, issue_date: str) -> str | None:
    """把页面的 'MM-DD HH:MM' 拼成 'YYYY-MM-DD HH:MM'。

    年份从 issue_date 取，若拼出来的月份比 issue_date 早超过 6 个月，
    则认为是跨年，年份 +1。
    """
    time_text = time_text.strip()
    try:
        year = int(issue_date[:4])
        dt = datetime.strptime(f"{year}-{time_text}", "%Y-%m-%d %H:%M")
        # 跨年处理：kickoff 比 issue_date 早 6 个月以上 → 加一年
        issue_dt = datetime.strptime(issue_date, "%Y-%m-%d")
        if (issue_dt - dt).days > 180:
            dt = dt.replace(year=year + 1)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return None


def fetch_500_matches(issue_date: str, timeout: int = 15) -> list[dict[str, Any]]:
    """抓取 500.com 竞彩足球赛事，返回符合 STANDARD_FIELDS 格式的记录列表。

    只返回 issue_date 当日的赛事（根据 kickoff_time 推断）。
    """
    try:
        resp = requests.get(SOURCE_URL, headers=_HEADERS, timeout=timeout)
        resp.encoding = "gbk"
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("500.com 请求失败 err=%s", exc)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    rows = soup.select("tr.bet-tb-tr")
    logger.info("500.com 页面解析到 %s 条原始赛事行", len(rows))

    out: list[dict[str, Any]] = []
    for row in rows:
        tds = row.find_all("td")
        if len(tds) < 6:
            continue

        match_no = tds[0].get_text(strip=True)
        league = tds[1].get_text(strip=True)
        time_text = tds[2].get_text(strip=True)       # "MM-DD HH:MM"
        team_td = tds[3]
        rang_text = tds[4].get_text(strip=True)
        odds_td = tds[5]

        # 主客队
        home_team = team_td.select_one(".team-l")
        away_team = team_td.select_one(".team-r")
        home_team = home_team.get_text(strip=True) if home_team else None
        away_team = away_team.get_text(strip=True) if away_team else None
        if not home_team or not away_team:
            # 兜底：从整体文本 "主队VS客队" 拆分
            team_text = team_td.get_text(strip=True)
            parts = re.split(r"VS", team_text, maxsplit=1)
            if len(parts) == 2:
                home_team = parts[0].strip() or home_team
                away_team = parts[1].strip() or away_team

        # 赔率：6 个 span（胜平负 × SPF + RQSPF）
        spans = odds_td.find_all("span")
        odds = [s.get_text(strip=True) for s in spans if s.get_text(strip=True)]
        spf_win = odds[0] if len(odds) > 0 else None
        spf_draw = odds[1] if len(odds) > 1 else None
        spf_lose = odds[2] if len(odds) > 2 else None
        rqspf_win = odds[3] if len(odds) > 3 else None
        rqspf_draw = odds[4] if len(odds) > 4 else None
        rqspf_lose = odds[5] if len(odds) > 5 else None

        handicap = _parse_handicap(rang_text)
        kickoff_time = _build_kickoff_time(time_text, issue_date)
        inferred = infer_issue_date_from_kickoff(kickoff_time)

        # 仅保留属于 issue_date 的赛事
        if inferred and inferred != issue_date:
            continue

        out.append(
            {
                "issue_date": inferred or issue_date,
                "issue_date_source": "inferred",
                "match_no": match_no,
                "league": league,
                "home_team": home_team,
                "away_team": away_team,
                "kickoff_time": kickoff_time,
                "handicap": handicap,
                "sell_status": "开售",
                "spf_win": spf_win,
                "spf_draw": spf_draw,
                "spf_lose": spf_lose,
                "rqspf_win": rqspf_win,
                "rqspf_draw": rqspf_draw,
                "rqspf_lose": rqspf_lose,
                "source_url": SOURCE_URL,
                "scrape_time": datetime.now().isoformat(timespec="seconds"),
            }
        )

    logger.info("500.com 过滤后 issue_date=%s 赛事数=%s", issue_date, len(out))
    return out
