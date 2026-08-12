"""取得結果のCSV/SQLiteへの蓄積。"""
from __future__ import annotations

import csv
import sqlite3
from pathlib import Path
from typing import Any, Iterable

FIELDS = [
    "docID",
    "queryDate",
    "submitDateTime",
    "edinetCode",
    "filerName",
    "docTypeCode",
    "ordinanceCode",
    "formCode",
    "docDescription",
    "currentReportReason",
]


def _row_from_doc(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "docID": doc.get("docID"),
        "queryDate": doc.get("_queryDate"),
        "submitDateTime": doc.get("submitDateTime"),
        "edinetCode": doc.get("edinetCode"),
        "filerName": doc.get("filerName"),
        "docTypeCode": doc.get("docTypeCode"),
        "ordinanceCode": doc.get("ordinanceCode"),
        "formCode": doc.get("formCode"),
        "docDescription": doc.get("docDescription"),
        "currentReportReason": doc.get("currentReportReason"),
    }


def write_csv(docs: Iterable[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [_row_from_doc(d) for d in docs]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def write_sqlite(docs: Iterable[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [_row_from_doc(d) for d in docs]

    conn = sqlite3.connect(path)
    try:
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS amended_documents (
                docID TEXT PRIMARY KEY,
                queryDate TEXT,
                submitDateTime TEXT,
                edinetCode TEXT,
                filerName TEXT,
                docTypeCode TEXT,
                ordinanceCode TEXT,
                formCode TEXT,
                docDescription TEXT,
                currentReportReason TEXT
            )
            """
        )
        conn.executemany(
            f"""
            INSERT OR REPLACE INTO amended_documents ({', '.join(FIELDS)})
            VALUES ({', '.join('?' for _ in FIELDS)})
            """,
            [tuple(row[f] for f in FIELDS) for row in rows],
        )
        conn.commit()
    finally:
        conn.close()
