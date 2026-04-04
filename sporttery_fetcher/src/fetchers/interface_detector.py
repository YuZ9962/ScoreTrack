from __future__ import annotations

import argparse
import json
from typing import Any

from config.settings import settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


class InterfaceDetector:
    def __init__(self) -> None:
        self.output_path = settings.data_raw_dir / "detected_xhr.json"

    def detect(self, target_url: str) -> list[dict[str, Any]]:
        try:
            from src.fetchers.playwright_utils import managed_playwright
        except Exception as exc:
            raise RuntimeError("请先安装 playwright 并执行 playwright install chromium") from exc

        discovered: list[dict[str, Any]] = []

        with managed_playwright() as p:
            browser = p.chromium.launch(headless=settings.playwright_headless)
            context = browser.new_context(user_agent=settings.user_agent)
            page = context.new_page()

            def on_response(resp):
                req = resp.request
                url = resp.url
                rtype = req.resource_type
                if rtype not in {"xhr", "fetch"} and "json" not in resp.headers.get("content-type", "").lower():
                    return
                if "sporttery" not in url:
                    return

                item = {
                    "url": url,
                    "method": req.method,
                    "resource_type": rtype,
                    "post_data": req.post_data,
                }
                try:
                    body = resp.text()
                    item["response_sample"] = body[:500]
                except Exception:
                    item["response_sample"] = None
                discovered.append(item)

            page.on("response", on_response)
            page.goto(target_url, wait_until="networkidle", timeout=settings.request_timeout * 1000)
            browser.close()

        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        with self.output_path.open("w", encoding="utf-8") as f:
            json.dump(discovered, f, ensure_ascii=False, indent=2)

        logger.info("接口检测完成，共发现 %s 条候选请求，输出文件: %s", len(discovered), self.output_path)
        return discovered


def manual_instructions() -> str:
    return (
        "如果自动检测不到接口，请手动排查：\n"
        "1) 打开官方赛程页 -> F12 -> Network。\n"
        "2) 过滤 XHR/Fetch，刷新页面。\n"
        "3) 观察包含 date、match、jczq 等参数的请求。\n"
        "4) 复制请求 URL/Method/Query/PostData。\n"
        "5) 用 curl 或 requests 复现，确认返回稳定 JSON。"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="检测官方赛程页 XHR/JSON 接口")
    parser.add_argument("--url", default=settings.primary_page_url, help="待检测页面 URL")
    args = parser.parse_args()

    detector = InterfaceDetector()
    try:
        records = detector.detect(args.url)
        if not records:
            print(manual_instructions())
        else:
            print(f"发现 {len(records)} 条候选请求，详情见 {detector.output_path}")
    except Exception as exc:
        logger.error("自动检测失败: %s", exc)
        print(manual_instructions())


if __name__ == "__main__":
    main()
