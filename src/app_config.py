"""config/config.json の読み込み。LLM/埋め込みモデルの切り替えはこのファイル経由で行う。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "config.json"


@dataclass(frozen=True)
class LlmConfig:
    provider: str
    base_url: str
    model: str
    enable_thinking: bool


@dataclass(frozen=True)
class EmbeddingConfig:
    provider: str
    base_url: str
    model: str


@dataclass(frozen=True)
class ChromaConfig:
    persist_dir: str
    cases_collection: str
    standards_collection: str


@dataclass(frozen=True)
class AppConfig:
    llm: LlmConfig
    embedding: EmbeddingConfig
    chroma: ChromaConfig


def load_config(path: Path = CONFIG_PATH) -> AppConfig:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return AppConfig(
        llm=LlmConfig(**raw["llm"]),
        embedding=EmbeddingConfig(**raw["embedding"]),
        chroma=ChromaConfig(**raw["chroma"]),
    )
