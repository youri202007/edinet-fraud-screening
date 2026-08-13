"""ChromaDB(ローカル永続化)への薄いラッパー。埋め込みはLM Studio経由で事前計算し、Chroma側では計算しない。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import chromadb

from app_config import ChromaConfig, EmbeddingConfig
from llm_provider import embed_texts

ROOT = Path(__file__).resolve().parent.parent


def get_client(chroma_config: ChromaConfig) -> chromadb.ClientAPI:
    persist_dir = ROOT / chroma_config.persist_dir
    persist_dir.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(persist_dir))


def get_collection(client: chromadb.ClientAPI, name: str):
    # embedding_function=None: 埋め込みはこちらで計算して渡すため、Chroma組み込みの埋め込みは使わない
    return client.get_or_create_collection(name=name, embedding_function=None)


def upsert(
    collection,
    *,
    ids: list[str],
    texts: list[str],
    metadatas: list[dict[str, Any]],
    embedding_config: EmbeddingConfig,
    batch_size: int = 32,
) -> None:
    for i in range(0, len(ids), batch_size):
        batch_ids = ids[i : i + batch_size]
        batch_texts = texts[i : i + batch_size]
        batch_meta = metadatas[i : i + batch_size]
        embeddings = embed_texts(batch_texts, config=embedding_config)
        collection.upsert(
            ids=batch_ids, documents=batch_texts, metadatas=batch_meta, embeddings=embeddings
        )


def query(
    collection,
    *,
    text: str,
    embedding_config: EmbeddingConfig,
    n_results: int = 5,
    where: dict[str, Any] | None = None,
) -> dict[str, Any]:
    embedding = embed_texts([text], config=embedding_config)[0]
    return collection.query(query_embeddings=[embedding], n_results=n_results, where=where)
