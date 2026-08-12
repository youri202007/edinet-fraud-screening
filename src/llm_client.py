"""LM Studioのローカルサーバー(OpenAI互換API)への薄いクライアント。"""
from __future__ import annotations

import json
import re
from typing import Any

import requests

DEFAULT_BASE_URL = "http://localhost:1234/v1"

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


class LmStudioError(RuntimeError):
    pass


def _strip_think_tags(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = _strip_think_tags(text)
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not match:
        raise LmStudioError(f"モデル出力からJSONを抽出できませんでした: {text!r}")
    return json.loads(match.group(0))


def classify_amendment(
    doc_description: str,
    *,
    model: str,
    body_excerpt: str = "",
    base_url: str = DEFAULT_BASE_URL,
    timeout: float = 120.0,
) -> dict[str, str]:
    """docDescription(+本文抜粋があればそれも)を分類し、{"importance": ..., "reason": ...} を返す。"""
    user_content = f"【書類概要】\n{doc_description or '(なし)'}\n\n【本文抜粋】\n{body_excerpt or '(取得できませんでした)'}"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.1,
        "max_tokens": 2000,
    }
    res = requests.post(f"{base_url}/chat/completions", json=payload, timeout=timeout)
    res.raise_for_status()
    body = res.json()
    content = body["choices"][0]["message"]["content"]

    result = _extract_json(content)
    importance = str(result.get("importance", "")).strip()
    reason = str(result.get("reason", "")).strip()

    if importance not in ("重要", "軽微"):
        raise LmStudioError(f"想定外のimportance値: {importance!r} (raw: {content!r})")

    return {"importance": importance, "reason": reason}
