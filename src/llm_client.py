"""訂正報告書の重要度分類に特化したプロンプトとロジック。LLM呼び出し自体は llm_provider に委譲する。"""
from __future__ import annotations

import json
import re
from typing import Any

from app_config import LlmConfig
from llm_provider import LlmError, chat_complete

DEFAULT_BASE_URL = "http://localhost:1234/v1"

# 後方互換のため、他モジュールからの `from llm_client import LmStudioError` を維持する
LmStudioError = LlmError

SYSTEM_PROMPT = """あなたは有価証券報告書等の訂正報告書を一次スクリーニングするアシスタントです。
入力される「書類概要」と「訂正理由に関する本文抜粋」を根拠に、以下2軸で分類してください。
本文抜粋がある場合はそちらを優先し、書類概要は補助情報として扱ってください。

- importance: "重要" または "軽微" のいずれか
  - "重要": 決算数値の修正、会計処理・会計方針の誤り、業績・財務諸表への影響が疑われるもの
  - "軽微": 誤字脱字、記載整備、様式・形式的な訂正など、数値や会計処理に影響しないもの
  - 本文抜粋がない、または情報不足で判断がつかない場合は "重要" 側に倒してください(見逃し防止のため)

- reason: 分類理由を日本語で一言(20〜40文字程度、本文の具体的な訂正内容に触れること)

出力は必ず次のJSON形式のみで返してください。前置き・説明・Markdownのコードブロックは不要です。
{"importance": "重要" または "軽微", "reason": "一言の理由"}
"""


def _extract_json(text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise LlmError(f"モデル出力からJSONを抽出できませんでした: {text!r}")
    return json.loads(match.group(0))


def classify_amendment(
    doc_description: str,
    *,
    model: str,
    body_excerpt: str = "",
    base_url: str = DEFAULT_BASE_URL,
    enable_thinking: bool = True,
) -> dict[str, Any]:
    """docDescription(+本文抜粋があればそれも)を分類し、{"importance": ..., "reason": ..., "elapsedSeconds": ...} を返す。"""
    user_content = f"【書類概要】\n{doc_description or '(なし)'}\n\n【本文抜粋】\n{body_excerpt or '(取得できませんでした)'}"

    config = LlmConfig(
        provider="lmstudio", base_url=base_url, model=model, enable_thinking=enable_thinking
    )
    result = chat_complete(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        config=config,
    )

    parsed = _extract_json(result["content"])
    importance = str(parsed.get("importance", "")).strip()
    reason = str(parsed.get("reason", "")).strip()

    if importance not in ("重要", "軽微"):
        raise LlmError(f"想定外のimportance値: {importance!r} (raw: {result['content']!r})")

    return {"importance": importance, "reason": reason, "elapsedSeconds": result["elapsedSeconds"]}
