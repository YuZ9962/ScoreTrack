from __future__ import annotations

import subprocess
import sys
from datetime import date as date_cls
from pathlib import Path
from typing import Any

import pandas as pd


def run_fetch_for_date(date_str: str, project_root: Path) -> dict[str, Any]:
    """调用现有抓取命令并返回统一结构结果。"""
    cmd = [sys.executable, "-m", "src.main", "--date", date_str]
    proc = subprocess.run(
        cmd,
        cwd=str(project_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    csv_path = project_root / "data" / "processed" / f"{date_str}_matches.csv"
    json_path = project_root / "data" / "raw" / f"{date_str}_matches.json"

    if proc.returncode != 0:
        return {
            "ok": False,
            "date": date_str,
            "count": 0,
            "message": "抓取失败：请稍后重试或检查数据源",
            "csv_path": str(csv_path),
            "json_path": str(json_path),
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "returncode": proc.returncode,
        }

    if not csv_path.exists():
        return {
            "ok": False,
            "date": date_str,
            "count": 0,
            "message": "抓取失败：未生成 CSV 文件",
            "csv_path": str(csv_path),
            "json_path": str(json_path),
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "returncode": proc.returncode,
        }

    try:
        df = pd.read_csv(csv_path)
        count = len(df)
    except Exception:
        count = 0

    return {
        "ok": True,
        "date": date_str,
        "count": count,
        "message": f"抓取成功：{date_str}，共 {count} 场，已自动刷新",
        "csv_path": str(csv_path),
        "json_path": str(json_path),
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "returncode": proc.returncode,
    }


def parse_date_input(value: Any) -> str:
    if isinstance(value, date_cls):
        return value.isoformat()
    return str(value)
