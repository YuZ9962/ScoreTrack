from __future__ import annotations

import argparse
from datetime import date, datetime
from typing import Any

from dateutil.parser import parse as parse_date

from src.fetchers.api_fetcher import APIFetcher
from src.fetchers.html_fetcher import HTMLFetcher
from src.fetchers.mobile_fetcher import MobileFetcher
from src.parsers.normalize import normalize_matches
from src.utils.logger import get_logger
from src.utils.save import save_csv, save_json

logger = get_logger(__name__)


def run(issue_date: str) -> dict[str, Any]:
    logger.info("开始抓取竞彩足球赛程，日期=%s", issue_date)

    raw_records: list[dict[str, Any]] = []
    source_url: str | None = None
    strategy = ""

    api_fetcher = APIFetcher()
    html_fetcher = HTMLFetcher()
    mobile_fetcher = MobileFetcher()

    try:
        raw_records, source_url = api_fetcher.fetch(issue_date)
        strategy = "api"
    except Exception as exc:
        logger.warning("API 抓取异常，将回退 HTML: %s", exc)

    if not raw_records:
        logger.info("API 无可用数据，回退到 HTML 抓取")
        raw_records, source_url = html_fetcher.fetch(issue_date)
        strategy = "html"

    if not raw_records:
        logger.info("HTML 无可用数据，回退移动端抓取")
        raw_records, source_url = mobile_fetcher.fetch(issue_date)
        strategy = "mobile"

    if not raw_records:
        raise RuntimeError("抓取失败：API/HTML/移动端均未返回有效比赛数据")

    normalized = normalize_matches(raw_records, issue_date=issue_date, source_url=source_url or "")

    json_path = save_json(normalized, issue_date)
    csv_path = save_csv(normalized, issue_date)

    logger.info("抓取完成，策略=%s，条数=%s", strategy, len(normalized))
    logger.info("JSON 输出: %s", json_path)
    logger.info("CSV 输出: %s", csv_path)

    return {
        "count": len(normalized),
        "strategy": strategy,
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
            f"JSON={result['json_path']} | CSV={result['csv_path']}"
        )
    except Exception as exc:
        logger.exception("抓取失败")
        print(f"抓取失败: {exc}")


if __name__ == "__main__":
    main()
