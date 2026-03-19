from __future__ import annotations

import argparse
from datetime import date
from typing import Any

from dateutil.parser import parse as parse_date

from config.settings import settings
from src.fetchers.api_fetcher import APIFetcher
from src.fetchers.html_fetcher import HTMLFetcher
from src.fetchers.mobile_fetcher import MobileFetcher
from src.parsers.normalize import normalize_matches
from src.utils.logger import get_logger
from src.utils.save import save_csv, save_json

logger = get_logger(__name__)


def _triple_non_empty_count(records: list[dict[str, Any]], keys: tuple[str, str, str]) -> int:
    a, b, c = keys
    return sum(1 for r in records if r.get(a) not in (None, "") and r.get(b) not in (None, "") and r.get(c) not in (None, ""))


def run(issue_date: str) -> dict[str, Any]:
    logger.info("开始抓取竞彩足球数据，日期=%s", issue_date)
    logger.info("当前主页面: %s", settings.primary_page_url)

    raw_records: list[dict[str, Any]] = []
    source_url: str | None = None
    strategy = ""

    api_fetcher = APIFetcher()
    html_fetcher = HTMLFetcher()
    mobile_fetcher = MobileFetcher()

    raw_records, source_url = api_fetcher.fetch(issue_date)
    strategy = "api"

    if not raw_records:
        logger.info("API 无可用数据，回退到 HTML 抓取")
        raw_records, source_url = html_fetcher.fetch(issue_date)
        strategy = "html/playwright"

    if not raw_records:
        logger.info("HTML 无可用数据，回退移动端抓取")
        raw_records, source_url = mobile_fetcher.fetch(issue_date)
        strategy = "mobile"

    if not raw_records:
        detail = (
            "抓取失败：未获取到有效竞彩足球数据。\n"
            "请优先运行：python -m src.fetchers.interface_detector\n"
            "并确认主页面是否可访问：https://www.sporttery.cn/jc/jsq/zqspf/index.html\n"
            "如需动态解析，请先执行：playwright install chromium"
        )
        raise RuntimeError(detail)

    normalized = normalize_matches(raw_records, issue_date=issue_date, source_url=source_url or "")
    handicap_non_empty = sum(1 for r in normalized if r.get("handicap") not in (None, ""))
    spf_full_non_empty = _triple_non_empty_count(normalized, ("spf_win", "spf_draw", "spf_lose"))
    rqspf_full_non_empty = _triple_non_empty_count(normalized, ("rqspf_win", "rqspf_draw", "rqspf_lose"))

    json_path = save_json(normalized, issue_date)
    csv_path = save_csv(normalized, issue_date)

    logger.info(
        "抓取完成：strategy=%s, 总场次=%s, handicap非空=%s, spf三列非空=%s, rqspf三列非空=%s",
        strategy,
        len(normalized),
        handicap_non_empty,
        spf_full_non_empty,
        rqspf_full_non_empty,
    )
    logger.info("JSON 输出: %s", json_path)
    logger.info("CSV 输出: %s", csv_path)

    return {
        "count": len(normalized),
        "strategy": strategy,
        "handicap_non_empty": handicap_non_empty,
        "spf_full_non_empty": spf_full_non_empty,
        "rqspf_full_non_empty": rqspf_full_non_empty,
        "json_path": str(json_path),
        "csv_path": str(csv_path),
        "source_url": source_url,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="中国体彩竞彩足球比赛信息抓取器（第一阶段）")
    parser.add_argument("--date", help="抓取日期，格式 YYYY-MM-DD，默认当天")
    return parser.parse_args()


def normalize_issue_date(value: str | None) -> str:
    if not value:
        return date.today().isoformat()
    return parse_date(value).date().isoformat()


def main() -> None:
    args = parse_args()
    issue_date = normalize_issue_date(args.date)
    try:
        result = run(issue_date)
        print(
            f"抓取成功: 条数={result['count']} | 策略={result['strategy']} | "
            f"handicap非空={result['handicap_non_empty']} | "
            f"spf三列非空={result['spf_full_non_empty']} | "
            f"rqspf三列非空={result['rqspf_full_non_empty']} | "
            f"JSON={result['json_path']} | CSV={result['csv_path']}"
        )
    except Exception as exc:
        logger.exception("抓取失败")
        print(f"抓取失败: {exc}")


if __name__ == "__main__":
    main()
