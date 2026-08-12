"""EDINETから日次の提出書類一覧を取得し、訂正報告書のみ抽出してローカルに蓄積する。

使い方:
    python src/fetch_documents.py --days 7
    python src/fetch_documents.py --start 2026-08-05 --end 2026-08-12 --format sqlite
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv

from edinet_client import EdinetApiError, fetch_documents_for_range
from storage import write_csv, write_sqlite

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# docDescription に「訂正」を含む書類を「訂正報告書」とみなす。
# (訂正有価証券報告書・訂正四半期報告書・訂正内部統制報告書・訂正大量保有報告書 等、
#  訂正系の書類種別を個別の docTypeCode で網羅するより頑健なため)
AMENDMENT_KEYWORD = "訂正"


def is_amendment(doc: dict[str, Any]) -> bool:
    description = doc.get("docDescription") or ""
    return AMENDMENT_KEYWORD in description


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, help="直近N日分を取得する(--start/--endと併用不可)")
    parser.add_argument("--start", type=str, help="開始日 YYYY-MM-DD")
    parser.add_argument("--end", type=str, help="終了日 YYYY-MM-DD (省略時は今日)")
    parser.add_argument(
        "--format",
        choices=["csv", "sqlite", "both"],
        default="both",
        help="出力形式 (デフォルト: both)",
    )
    parser.add_argument(
        "--out-dir", type=str, default=str(DATA_DIR), help="出力先ディレクトリ"
    )
    return parser.parse_args(argv)


def resolve_date_range(args: argparse.Namespace) -> tuple[dt.date, dt.date]:
    today = dt.date.today()
    if args.start:
        start = dt.date.fromisoformat(args.start)
        end = dt.date.fromisoformat(args.end) if args.end else today
        return start, end
    days = args.days or 7
    end = today
    start = end - dt.timedelta(days=days - 1)
    return start, end


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = parse_args(argv)
    start, end = resolve_date_range(args)
    out_dir = Path(args.out_dir)

    print(f"[fetch] {start} 〜 {end} の書類一覧を取得します...")
    try:
        docs = fetch_documents_for_range(start, end)
    except EdinetApiError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 1

    amendments = [d for d in docs if is_amendment(d)]
    print(f"[fetch] 総件数: {len(docs)} 件 / 訂正報告書: {len(amendments)} 件")

    if not amendments:
        print("[info] 該当する訂正報告書はありませんでした。")
        return 0

    if args.format in ("csv", "both"):
        csv_path = out_dir / f"amendments_{start}_{end}.csv"
        write_csv(amendments, csv_path)
        print(f"[write] CSV: {csv_path}")

    if args.format in ("sqlite", "both"):
        db_path = out_dir / "edinet.db"
        write_sqlite(amendments, db_path)
        print(f"[write] SQLite: {db_path} (table: amended_documents)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
