"""data/knowledge_base/jicpa/ のPDF(JICPA監基報等)をチャンク化・埋め込みし、ChromaDBに投入する。

使い方:
    python src/ingest_standards.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app_config import load_config
from doc_text import extract_text
from text_chunker import chunk_text
from vector_store import get_client, reset_collection, upsert

ROOT = Path(__file__).resolve().parent.parent
SOURCES_PATH = ROOT / "config" / "jicpa_sources.json"
PDF_DIR = ROOT / "data" / "knowledge_base" / "jicpa"


def main() -> int:
    config = load_config()
    sources = {d["id"]: d for d in json.loads(SOURCES_PATH.read_text(encoding="utf-8"))["documents"]}

    client = get_client(config.chroma)
    # チャンク方式(サイズ)を変更したときにチャンク数がずれて古いチャンクが残らないよう、毎回作り直す
    collection = reset_collection(client, config.chroma.standards_collection)

    pdf_paths = sorted(PDF_DIR.glob("*.pdf"))
    if not pdf_paths:
        print(f"[error] PDFが見つかりません: {PDF_DIR}", file=sys.stderr)
        return 1

    total_chunks = 0
    for i, pdf_path in enumerate(pdf_paths, start=1):
        doc_id = pdf_path.stem
        meta = sources.get(doc_id, {})
        title = meta.get("title", doc_id)
        category = meta.get("category", "")

        text = extract_text(pdf_path.read_bytes(), max_pages=9999)
        chunks = chunk_text(text, chunk_size=1500, overlap=250)
        if not chunks:
            print(f"  ({i}/{len(pdf_paths)}) [skip] {doc_id}: テキスト抽出結果が空")
            continue

        ids = [f"{doc_id}::{j}" for j in range(len(chunks))]
        metadatas = [
            {
                "source_id": doc_id,
                "title": title,
                "category": category,
                "chunk_index": j,
                "chunk_count": len(chunks),
            }
            for j in range(len(chunks))
        ]

        upsert(
            collection,
            ids=ids,
            texts=chunks,
            metadatas=metadatas,
            embedding_config=config.embedding,
        )
        total_chunks += len(chunks)
        print(f"  ({i}/{len(pdf_paths)}) [ok] {doc_id}: {title} -> {len(chunks)}チャンク")

    print(f"\n完了: {len(pdf_paths)}文書 / 合計{total_chunks}チャンクを投入しました。")
    print(f"コレクション件数: {collection.count()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
