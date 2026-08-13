"""data/classified_amendments.csv(Phase2の分類結果)をChromaDBに投入する。

使い方:
    python src/ingest_cases.py
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app_config import load_config
from vector_store import get_client, get_collection, upsert

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "data" / "classified_amendments.csv"


def build_case_text(row: dict) -> str:
    """検索対象テキスト。書類概要と分類理由を中心に構成する。"""
    return (
        f"提出者: {row['filerName']}\n"
        f"書類概要: {row['docDescription']}\n"
        f"重要度: {row['importance']}\n"
        f"分類理由: {row['reason']}"
    )


def main() -> int:
    config = load_config()

    if not CSV_PATH.exists():
        print(f"[error] {CSV_PATH} が見つかりません。先にPhase2の分類を実行してください。", file=sys.stderr)
        return 1

    with CSV_PATH.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        print("[info] 分類済みデータが0件です。")
        return 0

    ids = [row["docID"] for row in rows]
    texts = [build_case_text(row) for row in rows]
    metadatas = [
        {
            "docID": row["docID"],
            "filerName": row["filerName"],
            "submitDateTime": row["submitDateTime"],
            "docDescription": row["docDescription"],
            "importance": row["importance"],
            "reason": row["reason"],
        }
        for row in rows
    ]

    client = get_client(config.chroma)
    collection = get_collection(client, config.chroma.cases_collection)

    print(f"[ingest] {len(rows)} 件の事例を投入します...")
    upsert(collection, ids=ids, texts=texts, metadatas=metadatas, embedding_config=config.embedding)

    print(f"完了: コレクション件数 {collection.count()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
