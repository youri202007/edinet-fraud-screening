"""EDINET API v2 の薄いクライアント。"""
from __future__ import annotations

import datetime as dt
import os
import time
from typing import Any

import requests

BASE_URL = "https://api.edinet-fsa.go.jp/api/v2/documents.json"


class EdinetApiError(RuntimeError):
    pass


def _api_key() -> str:
    key = os.environ.get("EDINET_API_KEY")
    if not key:
        raise EdinetApiError(
            "EDINET_API_KEY が設定されていません。.env に設定してください。"
        )
    return key


def fetch_documents_for_date(
    target_date: dt.date, *, type_: int = 2, timeout: float = 15.0
) -> list[dict[str, Any]]:
    """指定日に提出された書類の一覧(メタデータ)を取得する。"""
    params = {
        "date": target_date.isoformat(),
        "type": type_,
        "Subscription-Key": _api_key(),
    }
    res = requests.get(BASE_URL, params=params, timeout=timeout)
    res.raise_for_status()
    body = res.json()

    status_code = body.get("metadata", {}).get("status")
    if status_code not in ("200", 200):
        message = body.get("metadata", {}).get("message", "unknown error")
        raise EdinetApiError(f"{target_date}: EDINET API error {status_code}: {message}")

    return body.get("results", []) or []


def fetch_documents_for_range(
    start_date: dt.date, end_date: dt.date, *, sleep_seconds: float = 0.5
) -> list[dict[str, Any]]:
    """[start_date, end_date] の範囲(両端含む)の書類一覧をまとめて取得する。"""
    if start_date > end_date:
        raise ValueError("start_date must be <= end_date")

    all_results: list[dict[str, Any]] = []
    current = start_date
    while current <= end_date:
        docs = fetch_documents_for_date(current)
        for doc in docs:
            doc["_queryDate"] = current.isoformat()
        all_results.extend(docs)
        current += dt.timedelta(days=1)
        if current <= end_date:
            time.sleep(sleep_seconds)
    return all_results
