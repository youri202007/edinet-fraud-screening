"""config/jicpa_sources.json に基づき、JICPAの監査基準委員会報告書等のPDFをダウンロードする。

著作物のため、ダウンロード先(data/knowledge_base/jicpa/)はgitignore対象。
既にダウンロード済みのファイルはスキップする(再実行安全)。

使い方:
    python src/download_jicpa_standards.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
SOURCES_PATH = ROOT / "config" / "jicpa_sources.json"
OUT_DIR = ROOT / "data" / "knowledge_base" / "jicpa"

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; edinet-fraud-screening research tool)"}


def main() -> int:
    sources = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
    documents = sources["documents"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    ok, skipped, failed = 0, 0, 0
    for i, doc in enumerate(documents, start=1):
        out_path = OUT_DIR / f"{doc['id']}.pdf"
        if out_path.exists():
            print(f"  ({i}/{len(documents)}) [skip] {doc['id']}: {doc['title']}")
            skipped += 1
            continue

        print(f"  ({i}/{len(documents)}) [get]  {doc['id']}: {doc['title']}")
        try:
            res = requests.get(doc["url"], headers=HEADERS, timeout=30)
            res.raise_for_status()
            if "pdf" not in res.headers.get("Content-Type", "").lower():
                raise ValueError(f"PDFではないレスポンス(Content-Type: {res.headers.get('Content-Type')})")
            out_path.write_bytes(res.content)
            ok += 1
        except Exception as e:  # noqa: BLE001
            print(f"    [warn] 失敗: {e}", file=sys.stderr)
            failed += 1

        time.sleep(1.0)  # サーバーへの負荷軽減

    print(f"\n完了: 成功={ok} スキップ={skipped} 失敗={failed} (合計{len(documents)})")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
