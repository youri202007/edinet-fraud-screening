"""EDINET API v2 の薄いクライアント。"""
from __future__ import annotations

import datetime as dt
import os
import time
from typing import Any

import requests

BASE_URL = "https://api.edinet-fsa.go.jp/api/v2/documents.json"
DOCUMENT_URL = "https://api.edinet-fsa.go.jp/api/v2/documents/{doc_id}"

# type: 1=XBRL, 2=PDF, 3=代替書面・添付文書, 4=英文, 5=CSV
DOC_TYPE_PDF = 2


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


def fetch_document_pdf(doc_id: str, *, timeout: float = 30.0) -> bytes:
    """指定書類のPDF本文(バイナリ)を取得する。"""
    params = {"type": DOC_TYPE_PDF, "Subscription-Key": _api_key()}
    url = DOCUMENT_URL.format(doc_id=doc_id)
    res = requests.get(url, params=params, timeout=timeout)
    res.raise_for_status()

    content_type = res.headers.get("Content-Type", "")
    if "pdf" not in content_type.lower():
        raise EdinetApiError(
            f"{doc_id}: PDFが取得できませんでした(Content-Type: {content_type})。"
            "書類がPDF非対応(縦覧終了・様式外 等)の可能性があります。"
        )
    return res.content
