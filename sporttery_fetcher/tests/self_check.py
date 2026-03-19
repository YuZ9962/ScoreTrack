from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import settings
from src.fetchers.api_fetcher import APIFetcher
from src.fetchers.html_fetcher import HTMLFetcher
from src.fetchers.interface_detector import InterfaceDetector
from src.utils.http import HTTPClient


def check_main_page() -> bool:
    client = HTTPClient()
    resp = client.request("GET", settings.schedule_urls[0])
    ok = resp.status_code == 200 and "sporttery" in str(resp.url)
    print(f"[A] 主页面可访问: {ok} | status={resp.status_code} | url={resp.url}")
    return ok


def check_api_fetch(issue_date: str) -> bool:
    fetcher = APIFetcher()
    records, endpoint = fetcher.fetch(issue_date)
    ok = len(records) >= 1
    print(f"[B] API 抓取结果: {len(records)} 条 | ok={ok} | endpoint={endpoint}")
    if records:
        print(f"    样例: {json.dumps(records[0], ensure_ascii=False)[:300]}")
    return ok


def check_html_fetch(issue_date: str) -> bool:
    fetcher = HTMLFetcher()
    records, source = fetcher.fetch(issue_date)
    ok = len(records) >= 1
    print(f"[C] HTML 抓取结果: {len(records)} 条 | ok={ok} | source={source}")
    if records:
        print(f"    样例: {json.dumps(records[0], ensure_ascii=False)[:300]}")
    return ok


def check_detector() -> bool:
    detector = InterfaceDetector()
    try:
        detector.detect(settings.schedule_urls[0])
    except Exception as exc:
        print(f"[D] detector 失败（可能未安装 Playwright）: {exc}")
        print("    提示：先执行 playwright install chromium")
        return False

    output: Path = detector.output_path
    ok = output.exists() and output.stat().st_size > 0
    print(f"[D] detector 输出文件: {output} | ok={ok}")
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(description="sporttery_fetcher 快速自检")
    parser.add_argument("--date", default="2026-03-19", help="测试抓取日期，默认 2026-03-19")
    args = parser.parse_args()

    print("开始自检...\n")
    a_ok = check_main_page()
    b_ok = check_api_fetch(args.date)
    c_ok = check_html_fetch(args.date)
    d_ok = check_detector()

    print("\n自检汇总:")
    print(f"- A 主页面可访问: {a_ok}")
    print(f"- B API 至少 1 场: {b_ok}")
    print(f"- C HTML 至少 1 场: {c_ok}")
    print(f"- D detector 输出文件: {d_ok}")


if __name__ == "__main__":
    main()
