"""RAGの中核ロジック(質問の意図判定 → 事例検索 or 基準検索+回答生成)。Streamlit等のUIから呼び出す。"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Literal

from app_config import AppConfig, load_config
from llm_provider import chat_complete
from vector_store import get_client, get_collection, query

Intent = Literal["case", "standard"]

INTENT_SYSTEM_PROMPT = """あなたは会計監査支援システムの質問振り分け役です。
ユーザーの質問が次のどちらのタイプかを判定してください。

- "case": 過去の訂正報告書の事例(どんな会社が、どんな理由で訂正したか等)を知りたい質問
- "standard": 監査手続・監査基準の考え方(サンプリングの範囲、リスク対応、不正への対応等)を確認したい質問

出力は必ず次のJSON形式のみで返してください。
{"intent": "case" または "standard"}
"""

STANDARD_ANSWER_SYSTEM_PROMPT = """あなたは会計監査の実務相談に対して、監査基準委員会報告書等の該当箇所を
示しながら回答するアシスタントです。以下のルールを厳守してください。

- 断定的な結論(「〜すべきです」「〜が正解です」等)は述べない。
- 「(基準名)には〜と記載されています」という参照・引用の形式に徹する。
- 必ず、根拠とした基準名を明示する(渡された各文脈の先頭の[出典: ...]を使う)。
- 複数の基準にまたがる場合は、それぞれ分けて記載する。
- 与えられた文脈に書かれていないことは述べない。文脈から答えられない場合は、
  「関連する記載が見つかりませんでした」と述べる。
- 最終的な判断は利用者(監査人)に委ねる旨を末尾に一言添える。
"""


@dataclass
class CaseHit:
    doc_id: str
    filer_name: str
    doc_description: str
    importance: str
    reason: str
    distance: float


@dataclass
class StandardSource:
    title: str
    excerpt: str
    distance: float


@dataclass
class AnswerResult:
    intent: Intent
    answer_text: str
    case_hits: list[CaseHit] = field(default_factory=list)
    standard_sources: list[StandardSource] = field(default_factory=list)
    elapsed_seconds: float = 0.0


def _extract_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError(f"JSONを抽出できませんでした: {text!r}")
    return json.loads(match.group(0))


def classify_intent(question: str, config: AppConfig) -> Intent:
    result = chat_complete(
        [
            {"role": "system", "content": INTENT_SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ],
        config=config.llm,
        max_tokens=200,
    )
    parsed = _extract_json(result["content"])
    intent = parsed.get("intent")
    return "case" if intent == "case" else "standard"


def answer_case_query(question: str, config: AppConfig, *, top_k: int = 5) -> AnswerResult:
    client = get_client(config.chroma)
    cases = get_collection(client, config.chroma.cases_collection)
    result = query(cases, text=question, embedding_config=config.embedding, n_results=top_k)

    hits = [
        CaseHit(
            doc_id=doc_id,
            filer_name=meta["filerName"],
            doc_description=meta["docDescription"],
            importance=meta["importance"],
            reason=meta["reason"],
            distance=dist,
        )
        for doc_id, meta, dist in zip(
            result["ids"][0], result["metadatas"][0], result["distances"][0]
        )
    ]

    if not hits:
        text = "類似する過去事例は見つかりませんでした。"
    else:
        lines = ["質問に類似する過去の訂正報告書事例は以下の通りです(類似度が高い順)。", ""]
        for h in hits:
            lines.append(f"- 【{h.importance}】{h.filer_name} / {h.doc_description} — {h.reason}")
        text = "\n".join(lines)

    return AnswerResult(intent="case", answer_text=text, case_hits=hits)


def answer_standard_query(question: str, config: AppConfig, *, top_k: int = 5) -> AnswerResult:
    client = get_client(config.chroma)
    standards = get_collection(client, config.chroma.standards_collection)
    result = query(standards, text=question, embedding_config=config.embedding, n_results=top_k)

    sources = [
        StandardSource(title=meta["title"], excerpt=doc, distance=dist)
        for doc, meta, dist in zip(
            result["documents"][0], result["metadatas"][0], result["distances"][0]
        )
    ]

    if not sources:
        return AnswerResult(
            intent="standard",
            answer_text="関連する基準の記載が見つかりませんでした。",
            standard_sources=[],
        )

    context = "\n\n".join(f"[出典: {s.title}]\n{s.excerpt}" for s in sources)
    user_content = f"質問: {question}\n\n---参考文脈---\n{context}"

    llm_result = chat_complete(
        [
            {"role": "system", "content": STANDARD_ANSWER_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        config=config.llm,
        max_tokens=1500,
    )

    return AnswerResult(
        intent="standard",
        answer_text=llm_result["content"],
        standard_sources=sources,
        elapsed_seconds=llm_result["elapsedSeconds"],
    )


def answer(question: str, config: AppConfig | None = None) -> AnswerResult:
    config = config or load_config()
    intent = classify_intent(question, config)
    if intent == "case":
        return answer_case_query(question, config)
    return answer_standard_query(question, config)
