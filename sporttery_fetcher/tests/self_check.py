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
from tools.interface_detector import InterfaceDetector
from src.utils.http import HTTPClient


def check_main_page() -> bool:
    client = HTTPClient()
    resp = client.request("GET", settings.primary_page_url)
    ok = resp.status_code == 200 and "sporttery" in str(resp.url)
    print(f"[A] 主页面可访问: {ok} | status={resp.status_code} | url={resp.url}")
    return ok


def check_fetch(issue_date: str) -> tuple[bool, int, int, int, int]:
    api = APIFetcher()
    html = HTMLFetcher()

    records, endpoint = api.fetch(issue_date)
    strategy = "API"
    if not records:
        records, endpoint = html.fetch(issue_date)
        strategy = "HTML/Playwright"

    count = len(records)
    handicap_non_empty = sum(1 for r in records if r.get("handicap") not in (None, ""))
    spf_win_non_empty = sum(1 for r in records if r.get("spf_win") not in (None, ""))
    rqspf_win_non_empty = sum(1 for r in records if r.get("rqspf_win") not in (None, ""))

    ok = count >= 1 and handicap_non_empty >= 1 and spf_win_non_empty >= 1 and rqspf_win_non_empty >= 1

    print(
        f"[B] 抓取检查: strategy={strategy} | count={count} | handicap_non_empty={handicap_non_empty} | "
        f"spf_win_non_empty={spf_win_non_empty} | rqspf_win_non_empty={rqspf_win_non_empty} | ok={ok} | source={endpoint}"
    )
    if records:
        print(f"    样例: {json.dumps(records[0], ensure_ascii=False)[:350]}")
    return ok, count, handicap_non_empty, spf_win_non_empty, rqspf_win_non_empty


def check_detector() -> bool:
    detector = InterfaceDetector()
    try:
        detector.detect(settings.primary_page_url)
    except Exception as exc:
        print(f"[C] detector 失败（可能未安装 Playwright）: {exc}")
        print("    提示：先执行 playwright install chromium")
        return False

    output: Path = detector.output_path
    ok = output.exists() and output.stat().st_size > 0
    print(f"[C] detector 输出文件: {output} | ok={ok}")
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(description="sporttery_fetcher 快速自检")
    parser.add_argument("--date", default="2026-03-19", help="测试抓取日期，默认 2026-03-19")
    args = parser.parse_args()

    print("开始自检...\n")
    a_ok = check_main_page()
    b_ok, count, handicap_count, spf_win_count, rqspf_win_count = check_fetch(args.date)
    c_ok = check_detector()

    print("\n自检汇总:")
    print(f"- A 主页面可访问: {a_ok}")
    print(f"- B 至少抓到1场: {count >= 1}")
    print(f"- C handicap至少1场非空: {handicap_count >= 1}")
    print(f"- D spf_win至少1场非空: {spf_win_count >= 1}")
    print(f"- E rqspf_win至少1场非空: {rqspf_win_count >= 1}")
    print(f"- F detector 输出文件存在: {c_ok}")
    print(f"- Overall: {a_ok and b_ok and c_ok}")


if __name__ == "__main__":
    main()
