from __future__ import annotations

"""
Centralised data-file path resolution for the app layer.

Every store module that reads or writes a data file should use these
functions instead of computing ``Path(__file__).resolve().parents[N] / ...``
inline.  Changing the directory layout only requires editing this file.

Note: ``src/services/result_cleaner.py`` owns the result-file paths on the
src side via its own ``result_paths()`` function — that function is NOT
replaced here to preserve layer separation (src must not import from app).
"""

from pathlib import Path


def _root(base_dir: Path | None = None) -> Path:
    return base_dir or Path(__file__).resolve().parents[2]


# ── directory helpers ──────────────────────────────────────────────────────────

def processed_dir(base_dir: Path | None = None) -> Path:
    return _root(base_dir) / "data" / "processed"


def predictions_dir(base_dir: Path | None = None) -> Path:
    p = _root(base_dir) / "data" / "predictions"
    p.mkdir(parents=True, exist_ok=True)
    return p


def results_dir(base_dir: Path | None = None) -> Path:
    p = _root(base_dir) / "data" / "results"
    p.mkdir(parents=True, exist_ok=True)
    return p


def facts_dir(base_dir: Path | None = None) -> Path:
    p = _root(base_dir) / "data" / "facts"
    p.mkdir(parents=True, exist_ok=True)
    return p


def articles_dir(base_dir: Path | None = None) -> Path:
    p = _root(base_dir) / "data" / "articles"
    p.mkdir(parents=True, exist_ok=True)
    return p


def manual_dir(base_dir: Path | None = None) -> Path:
    p = _root(base_dir) / "data" / "manual"
    p.mkdir(parents=True, exist_ok=True)
    return p


# ── concrete file paths ────────────────────────────────────────────────────────

def gemini_predictions_file(base_dir: Path | None = None) -> Path:
    return predictions_dir(base_dir) / "gemini_predictions.csv"


def chatgpt_predictions_file(base_dir: Path | None = None) -> Path:
    return predictions_dir(base_dir) / "chatgpt_predictions.csv"


def clean_results_file(base_dir: Path | None = None) -> Path:
    return results_dir(base_dir) / "clean_match_results.csv"


def raw_results_file(base_dir: Path | None = None) -> Path:
    return results_dir(base_dir) / "raw_match_results.csv"


def bad_results_file(base_dir: Path | None = None) -> Path:
    return results_dir(base_dir) / "bad_match_results.csv"


def legacy_results_file(base_dir: Path | None = None) -> Path:
    return results_dir(base_dir) / "match_results.csv"


def match_facts_file(base_dir: Path | None = None) -> Path:
    return facts_dir(base_dir) / "match_facts.csv"


def wechat_articles_file(base_dir: Path | None = None) -> Path:
    return articles_dir(base_dir) / "wechat_articles.csv"


def wechat_token_cache_file(base_dir: Path | None = None) -> Path:
    return articles_dir(base_dir) / "wechat_token_cache.json"


def manual_matches_file(base_dir: Path | None = None) -> Path:
    return manual_dir(base_dir) / "history_matches.csv"
