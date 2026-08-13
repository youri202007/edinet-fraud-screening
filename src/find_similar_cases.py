"""fetch_documents.pyで新規取得した訂正報告書に対し、ChromaDBの過去事例(cases)から類似事例を検索してログに残す。

使い方(fetch_documents.pyの後に実行):
    python src/find_similar_cases.py
    python src/find_similar_cases.py --csv data/amendments_2026-08-06_2026-08-12.csv
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app_config import load_config
from vector_store import get_client, get_collection, query

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
LOG_DIR = DATA_DIR / "logs"


def find_latest_amendments_csv() -> Path | None:
    candidates = sorted(DATA_DIR.glob("amendments_*.csv"), key=lambda p: p.stat().st_mtime)
    return candidates[-1] if candidates else None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=str, default=None, help="対象CSV(省略時は最新のamendments_*.csvを自動検出)")
    parser.add_argument("--top-k", type=int, default=3, help="類似事例の件数(デフォルト3)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    csv_path = Path(args.csv) if args.csv else find_latest_amendments_csv()
    if csv_path is None or not csv_path.exists():
        print("[error] 対象CSVが見つかりません。先にfetch_documents.pyを実行してください。", file=sys.stderr)
        return 1

    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        print("[info] 対象0件です。")
        return 0

    config = load_config()
    client = get_client(config.chroma)
    cases = get_collection(client, config.chroma.cases_collection)

    if cases.count() == 0:
        print(
            "[error] casesコレクションが空です。先に src/ingest_cases.py を実行してください。",
            file=sys.stderr,
        )
        return 1

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    today = dt.date.today().isoformat()
    md_path = LOG_DIR / f"similar_cases_{today}.md"
    csv_out_path = LOG_DIR / f"similar_cases_{today}.csv"

    md_lines = [f"# 類似事例照会ログ ({today})", "", f"対象: `{csv_path.name}` ({len(rows)}件)", ""]
    csv_rows = []

    print(f"[search] {len(rows)} 件の新規訂正報告書について類似事例を検索します...")
    for i, row in enumerate(rows, start=1):
        query_text = f"提出者: {row['filerName']}\n書類概要: {row['docDescription']}"
        result = query(cases, text=query_text, embedding_config=config.embedding, n_results=args.top_k + 1)

        md_lines.append(f"## {i}. {row['filerName']} — {row['docDescription']} (`{row['docID']}`)")
        md_lines.append("")

        hits = 0
        for doc_id, meta, dist in zip(
            result["ids"][0], result["metadatas"][0], result["distances"][0]
        ):
            if doc_id == row["docID"] or hits >= args.top_k:
                continue
            hits += 1
            md_lines.append(
                f"- **{meta['importance']}** (距離{dist:.3f}) {meta['filerName']} / "
                f"{meta['docDescription']} — {meta['reason']} (`{doc_id}`)"
            )
            csv_rows.append(
                {
                    "newDocID": row["docID"],
                    "newFilerName": row["filerName"],
                    "newDocDescription": row["docDescription"],
                    "similarDocID": doc_id,
                    "similarFilerName": meta["filerName"],
                    "similarDocDescription": meta["docDescription"],
                    "similarImportance": meta["importance"],
                    "similarReason": meta["reason"],
                    "distance": round(dist, 4),
                }
            )
        if hits == 0:
            md_lines.append("- (類似事例なし)")
        md_lines.append("")
        print(f"  ({i}/{len(rows)}) {row['docID']}: 類似{hits}件")

    md_path.write_text("\n".join(md_lines), encoding="utf-8")

    with csv_out_path.open("w", newline="", encoding="utf-8-sig") as f:
        fieldnames = [
            "newDocID",
            "newFilerName",
            "newDocDescription",
            "similarDocID",
            "similarFilerName",
            "similarDocDescription",
            "similarImportance",
            "similarReason",
            "distance",
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(csv_rows)

    print(f"\n[write] Markdown: {md_path}")
    print(f"[write] CSV: {csv_out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
