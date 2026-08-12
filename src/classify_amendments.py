"""data/edinet.db の訂正報告書をローカルLLM(LM Studio)で分類し、CSVに追記する。

前提: LM Studioでモデルをロードし、Developerタブでローカルサーバーを起動しておくこと。

使い方:
    python src/classify_amendments.py --limit 10
    python src/classify_amendments.py --limit 10 --model qwen3-14b
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from llm_client import DEFAULT_BASE_URL, LmStudioError, classify_amendment

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "edinet.db"
DEFAULT_OUT = ROOT / "data" / "classified_amendments.csv"

OUT_FIELDS = [
    "docID",
    "filerName",
    "submitDateTime",
    "docDescription",
    "importance",
    "reason",
    "classifiedAt",
    "model",
]


def load_already_classified(out_path: Path) -> set[str]:
    if not out_path.exists():
        return set()
    with out_path.open(encoding="utf-8-sig", newline="") as f:
        return {row["docID"] for row in csv.DictReader(f)}


def load_candidates(db_path: Path, limit: int, exclude_ids: set[str]) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT docID, filerName, submitDateTime, docDescription "
            "FROM amended_documents ORDER BY submitDateTime"
        ).fetchall()
    finally:
        conn.close()

    candidates = [dict(r) for r in rows if r["docID"] not in exclude_ids]
    return candidates[:limit]


def append_results(out_path: Path, rows: list[dict]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = out_path.exists()
    with out_path.open("a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=OUT_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=10, help="分類する件数(デフォルト10)")
    parser.add_argument("--db", type=str, default=str(DEFAULT_DB), help="入力SQLiteパス")
    parser.add_argument("--out", type=str, default=str(DEFAULT_OUT), help="出力CSVパス")
    parser.add_argument("--model", type=str, default="qwen3-14b", help="LM Studioのモデルid")
    parser.add_argument("--base-url", type=str, default=DEFAULT_BASE_URL)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    db_path = Path(args.db)
    out_path = Path(args.out)

    if not db_path.exists():
        print(f"[error] DBが見つかりません: {db_path}", file=sys.stderr)
        return 1

    already = load_already_classified(out_path)
    candidates = load_candidates(db_path, args.limit, already)

    if not candidates:
        print("[info] 分類対象がありません(すべて分類済み、またはDBが空)。")
        return 0

    print(f"[classify] {len(candidates)} 件を {args.model} で分類します...")

    results = []
    for i, doc in enumerate(candidates, start=1):
        desc = doc["docDescription"] or ""
        print(f"  ({i}/{len(candidates)}) {doc['docID']} {doc['filerName']}: {desc[:40]}")
        try:
            classification = classify_amendment(
                desc, model=args.model, base_url=args.base_url
            )
        except (LmStudioError, Exception) as e:  # noqa: BLE001
            print(f"    [warn] 分類失敗、スキップ: {e}", file=sys.stderr)
            continue

        results.append(
            {
                "docID": doc["docID"],
                "filerName": doc["filerName"],
                "submitDateTime": doc["submitDateTime"],
                "docDescription": desc,
                "importance": classification["importance"],
                "reason": classification["reason"],
                "classifiedAt": dt.datetime.now().isoformat(timespec="seconds"),
                "model": args.model,
            }
        )
        print(f"    -> {classification['importance']} / {classification['reason']}")

    if not results:
        print("[info] 分類できた件数が0件でした。")
        return 1

    append_results(out_path, results)
    print(f"[write] {len(results)} 件を追記しました: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
