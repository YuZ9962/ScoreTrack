from __future__ import annotations

import argparse
from datetime import date
from typing import Any

from dateutil.parser import parse as parse_date

from config.settings import settings
from src.fetchers.api_fetcher import APIFetcher
from src.fetchers.html_fetcher import HTMLFetcher
from src.fetchers.mobile_fetcher import MobileFetcher
from src.fetchers.lottery_schedule_fetcher import fetch_lottery_schedule
from src.fetchers.zqsgkj_fetcher import fetch_zqsgkj_matches, save_zqsgkj_results
from src.parsers.normalize import normalize_matches
from src.utils.logger import get_logger
from src.utils.save import save_csv, save_json


def _try_rebuild_facts(base_dir: Any = None) -> None:
    """抓取完成后触发事实表重建（失败不影响主流程）。"""
    try:
        from src.services.match_fact_builder import rebuild_match_facts
        from pathlib import Path
        rebuild_match_facts(Path(base_dir) if base_dir else None)
    except Exception:
        logger.debug("facts rebuild skipped after fetch")

logger = get_logger(__name__)


def _triple_non_empty_count(records: list[dict[str, Any]], keys: tuple[str, str, str]) -> int:
    a, b, c = keys
    return sum(1 for r in records if r.get(a) not in (None, "") and r.get(b) not in (None, "") and r.get(c) not in (None, ""))


def run(issue_date: str) -> dict[str, Any]:
    logger.info("开始抓取竞彩足球数据，日期=%s", issue_date)

    # 1. 未开始赛程：lottery.gov.cn/jc/zqszsc（侧边栏主流程）
    try:
        lottery_rows = fetch_lottery_schedule(issue_date)
    except Exception as exc:
        logger.warning("lottery 赛程抓取失败，回退后续流程 err=%s", type(exc).__name__)
        lottery_rows = []

    if lottery_rows:
        normalized = normalize_matches(lottery_rows, issue_date=issue_date, source_url=settings.lottery_schedule_url)
        handicap_non_empty = sum(1 for r in normalized if r.get("handicap") not in (None, ""))
        spf_full_non_empty = _triple_non_empty_count(normalized, ("spf_win", "spf_draw", "spf_lose"))
        rqspf_full_non_empty = _triple_non_empty_count(normalized, ("rqspf_win", "rqspf_draw", "rqspf_lose"))
        json_path = save_json(normalized, issue_date)
        csv_path = save_csv(normalized, issue_date)
        logger.info("lottery 赛程抓取成功 count=%s json=%s csv=%s", len(normalized), json_path, csv_path)
        _try_rebuild_facts(settings.base_dir)
        return {
            "count": len(normalized),
            "strategy": "lottery_schedule",
            "handicap_non_empty": handicap_non_empty,
            "spf_full_non_empty": spf_full_non_empty,
            "rqspf_full_non_empty": rqspf_full_non_empty,
            "json_path": str(json_path),
            "csv_path": str(csv_path),
            "source_url": settings.lottery_schedule_url,
        }

    # 2. 历史赛果：sporttery.cn/jc/zqsgkj（日期已过、无赛程时降级）
    try:
        zqsgkj_records = fetch_zqsgkj_matches(issue_date)
    except Exception as exc:
        logger.warning("zqsgkj 历史赛果抓取失败，回退比赛抓取流程 err=%s", type(exc).__name__)
        zqsgkj_records = []

    if zqsgkj_records:
        json_path, csv_path = save_zqsgkj_results(issue_date, zqsgkj_records, settings.base_dir)
        logger.info("zqsgkj 历史赛果抓取成功 count=%s json=%s csv=%s", len(zqsgkj_records), json_path, csv_path)
        _try_rebuild_facts(settings.base_dir)
        return {
            "count": len(zqsgkj_records),
            "strategy": "zqsgkj_playwright",
            "handicap_non_empty": sum(1 for r in zqsgkj_records if str(r.get("handicap", "")).strip()),
            "spf_full_non_empty": _triple_non_empty_count(zqsgkj_records, ("spf_win", "spf_draw", "spf_lose")),
            "rqspf_full_non_empty": 0,
            "json_path": str(json_path),
            "csv_path": str(csv_path),
            "source_url": "https://www.sporttery.cn/jc/zqsgkj/",
        }

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
    _try_rebuild_facts(settings.base_dir)

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
