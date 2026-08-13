"""config/web_sources.json の記事(監査実務ブログ等)を取得・本文抽出し、ChromaDBのstandardsコレクションに投入する。

JICPA/FSAの公式基準とは異なり第三者の実務解釈記事のため、category="参考ブログ(非公式)"を付与し、
回答生成プロンプト側で公式基準と明確に区別できるようにしている。

使い方:
    python src/ingest_web_sources.py
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import requests
from bs4 import BeautifulSoup

from app_config import load_config
from text_chunker import chunk_text
from vector_store import get_client, get_collection, upsert

ROOT = Path(__file__).resolve().parent.parent
SOURCES_PATH = ROOT / "config" / "web_sources.json"
CACHE_DIR = ROOT / "data" / "knowledge_base" / "web"

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) edinet-fraud-screening research tool"}

NOISE_TAGS = ["script", "style", "nav", "header", "footer", "aside", "noscript", "form", "iframe"]
# 本文らしき領域を優先して探すためのCSSセレクタ候補(サイトごとに構造が異なるため複数試す)
CONTENT_SELECTORS = [
    "article",
    "div.entry-content",
    "div.post-content",
    "div.note-common-styles__textnote-body",
    "div#note-body",
    "main",
]


def fetch_html(url: str) -> str:
    res = requests.get(url, headers=HEADERS, timeout=30)
    res.raise_for_status()
    # 文字コード自動検出に失敗するサイト(Shift-JIS等)があるため、apparent_encodingで補正する
    if res.encoding is None or res.encoding.lower() in ("iso-8859-1",):
        res.encoding = res.apparent_encoding
    return res.text


def extract_article_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(NOISE_TAGS):
        tag.decompose()

    for selector in CONTENT_SELECTORS:
        node = soup.select_one(selector)
        if node and len(node.get_text(strip=True)) > 200:
            text = node.get_text("\n", strip=True)
            break
    else:
        text = soup.get_text("\n", strip=True)

    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def main() -> int:
    config = load_config()
    sources = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))["documents"]

    client = get_client(config.chroma)
    collection = get_collection(client, config.chroma.standards_collection)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    total_chunks = 0
    for i, doc in enumerate(sources, start=1):
        cache_path = CACHE_DIR / f"{doc['id']}.txt"
        if cache_path.exists():
            text = cache_path.read_text(encoding="utf-8")
            print(f"  ({i}/{len(sources)}) [cache] {doc['id']}: {doc['title']}")
        else:
            try:
                html = fetch_html(doc["url"])
                text = extract_article_text(html)
                cache_path.write_text(text, encoding="utf-8")
                print(f"  ({i}/{len(sources)}) [get]   {doc['id']}: {doc['title']} ({len(text)}文字)")
            except Exception as e:  # noqa: BLE001
                print(f"  ({i}/{len(sources)}) [warn]  {doc['id']} 取得失敗: {e}", file=sys.stderr)
                continue
            time.sleep(1.0)

        chunks = chunk_text(text, chunk_size=1500, overlap=250)
        if not chunks:
            print(f"    [skip] 本文抽出結果が空でした")
            continue

        ids = [f"{doc['id']}::{j}" for j in range(len(chunks))]
        metadatas = [
            {
                "source_id": doc["id"],
                "title": doc["title"],
                "category": doc["category"],
                "chunk_index": j,
                "chunk_count": len(chunks),
                "source_url": doc["url"],
            }
            for j in range(len(chunks))
        ]
        upsert(collection, ids=ids, texts=chunks, metadatas=metadatas, embedding_config=config.embedding)
        total_chunks += len(chunks)
        print(f"    -> {len(chunks)}チャンク投入")

    print(f"\n完了: {len(sources)}記事 / 合計{total_chunks}チャンクを投入しました。")
    print(f"コレクション件数: {collection.count()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
