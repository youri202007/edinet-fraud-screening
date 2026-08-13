"""LLM呼び出しの共通部分。configで指定したプロバイダ(現状はLM Studioのみ)への薄いクライアント。

将来別プロバイダ(vLLM/Ollama/クラウドAPI等)に対応する場合、
provider名で分岐するか、この関数のシグネチャを保ったまま実装を差し替える。
"""
from __future__ import annotations

import re
import time
from typing import Any

import requests

from app_config import LlmConfig


class LlmError(RuntimeError):
    pass


def strip_think_tags(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def chat_complete(
    messages: list[dict[str, str]],
    *,
    config: LlmConfig,
    temperature: float = 0.1,
    max_tokens: int = 2000,
    timeout: float = 120.0,
) -> dict[str, Any]:
    """チャット補完を実行し、{"content": ..., "elapsedSeconds": ...} を返す。

    Qwen3系のthinkingモード制御は config.enable_thinking に従う
    (Qwen3の慣例: ユーザーターン末尾への /no_think 付与で抑制)。
    """
    if config.provider != "lmstudio":
        raise LlmError(f"未対応のprovider: {config.provider!r}")

    messages = list(messages)
    if not config.enable_thinking and messages and messages[-1]["role"] == "user":
        messages[-1] = {
            "role": "user",
            "content": messages[-1]["content"] + "\n\n/no_think",
        }

    payload = {
        "model": config.model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    start = time.monotonic()
    res = requests.post(f"{config.base_url}/chat/completions", json=payload, timeout=timeout)
    elapsed = time.monotonic() - start
    res.raise_for_status()
    body = res.json()
    content = body["choices"][0]["message"]["content"]

    return {"content": strip_think_tags(content), "elapsedSeconds": round(elapsed, 1)}


def embed_texts(
    texts: list[str],
    *,
    config,  # EmbeddingConfig
    timeout: float = 60.0,
) -> list[list[float]]:
    """テキストのリストを埋め込みベクトルのリストに変換する。"""
    if config.provider != "lmstudio":
        raise LlmError(f"未対応のprovider: {config.provider!r}")

    payload = {"model": config.model, "input": texts}
    res = requests.post(f"{config.base_url}/embeddings", json=payload, timeout=timeout)
    res.raise_for_status()
    body = res.json()
    # LM Studioのレスポンスはindex順とは限らないため、indexでソートして整合をとる
    data = sorted(body["data"], key=lambda d: d["index"])
    return [d["embedding"] for d in data]
