from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    base_dir: Path = BASE_DIR
    data_raw_dir: Path = BASE_DIR / "data" / "raw"
    data_processed_dir: Path = BASE_DIR / "data" / "processed"
    logs_dir: Path = BASE_DIR / "logs"
    snapshots_dir: Path = BASE_DIR / "data" / "raw" / "snapshots"

    request_timeout: int = int(os.getenv("REQUEST_TIMEOUT", "15"))
    request_retries: int = int(os.getenv("REQUEST_RETRIES", "3"))
    retry_wait_seconds: int = int(os.getenv("RETRY_WAIT_SECONDS", "1"))
    user_agent: str = os.getenv(
        "USER_AGENT",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/123.0 Safari/537.36",
    )
    save_html_snapshot: bool = os.getenv("SAVE_HTML_SNAPSHOT", "true").lower() == "true"
    playwright_headless: bool = os.getenv("PLAYWRIGHT_HEADLESS", "true").lower() == "true"

    # 已确认可用的竞彩足球接口
    football_api_url: str = os.getenv(
        "FOOTBALL_API_URL",
        "https://webapi.sporttery.cn/gateway/uniform/football/getMatchListV1.qry?clientCode=3001",
    )

    # 2026-03 已切换到 zqszsc（竞彩足球赛事总赛程）
    schedule_urls: tuple[str, ...] = (
        "https://www.sporttery.cn/jc/zqszsc/",
        "https://www.sporttery.cn/jc/zqszsc/index.shtml",
    )
    # 后续赛果扩展入口
    result_urls: tuple[str, ...] = (
        "https://www.sporttery.cn/jc/zqsgkj/",
        "https://www.sporttery.cn/jc/zqsgkj/index.shtml",
    )
    notice_urls: tuple[str, ...] = (
        "https://www.sporttery.cn/jc/zqgg/",
    )
    mobile_urls: tuple[str, ...] = (
        "https://m.sporttery.cn/jjc/jczq/",
    )


settings = Settings()

for d in [settings.data_raw_dir, settings.data_processed_dir, settings.logs_dir, settings.snapshots_dir]:
    d.mkdir(parents=True, exist_ok=True)
