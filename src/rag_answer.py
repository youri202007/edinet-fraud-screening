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

QUERY_EXPANSION_SYSTEM_PROMPT = """あなたは会計監査の検索クエリ拡張役です。
ユーザーの質問(自然文)を、埋め込み検索(ベクトル検索)で関連文書がヒットしやすいよう、
関連する専門用語を補った検索用テキストに展開してください。

- 質問の意図は変えない。
- 質問文中の言葉(例: 「サンプリング」「不備」)に加え、関連しそうな監査・内部統制の専門用語
  (例: 統制の逸脱、許容逸脱率、信頼上限、UPL、逐次抜取サンプリング、代替的な監査手続、
  J-SOX、業務プロセス、運用状況の評価、誤謬、虚偽表示 等、質問の文脈に応じて関連しそうなもの)
  を自然な形で補い、30〜80文字程度の検索用テキストを1つ作る。
- 質問が財務諸表監査(誤謬・虚偽表示)の文脈かJ-SOX内部統制評価(統制の逸脱)の文脈か
  判断できる場合は、それに応じた語彙を優先する。判断できない場合は両方の語彙を含めてよい。

出力は検索用テキストのみを1行で返す。説明・前置き・JSON等は不要。
"""

RERANK_SYSTEM_PROMPT = """あなたは検索結果の絞り込み役です。
質問に対して、以下の候補(番号・出典・冒頭抜粋)の中から、質問に答えるために本当に役立ちそうな
ものを最大{max_select}件選んでください。具体的な数値例・計算例・手続の詳細が書かれていそうな
候補を優先してください。表面的にキーワードが似ているだけで内容が無関係なものは選ばないでください。

出力は必ず次のJSON形式のみで返してください。
{{"selected": [番号, 番号, ...]}}
"""

STANDARD_ANSWER_SYSTEM_PROMPT = """あなたは経験豊富な監査実務家であり、後輩監査人からの実務相談に答えます。
渡された監査基準委員会報告書等の抜粋を根拠としながら、実務で使える分かりやすい説明をしてください。
生の引用を切り貼りするのではなく、内容を咀嚼して自分の言葉で筋道立てて説明することが最も重要です。

【用語の正確さについて】
- 「統制の逸脱(deviation)」(内部統制評価・J-SOXの運用評価、属性サンプリングで扱う)と、
  「誤謬・虚偽表示(misstatement)」(財務諸表監査の実証手続で扱う、金額ベース)は異なる概念であり、
  質問がどちらの文脈かを抜粋から判断し、正しい用語で答える。両方の抜粋が混ざっている場合は、
  それぞれ別の話であることを明示した上で、質問との関連が強い方を中心に説明する。
- サンプリングリスクに触れる場合、「評価が過大/過小に傾く可能性がある」のような曖昧な言い方ではなく、
  「観測されたサンプル内の逸脱率(または誤謬率)そのものではなく、そこから統計的に導かれる母集団の
  逸脱率の上限(信頼上限、UPL)で判断する必要があり、その上限は観測値より高くなる」という統計的な
  理屈を、抜粋に書かれている範囲で具体的に説明する。

出力は次の構成にしてください。

1. **考え方**: 質問への実務的な回答を、2〜4文程度でまず要約する。断定的な「絶対にこうすべき」ではなく、
   「基準の考え方に沿うと、一般的には〜という整理になります」といった、監査人としての判断の道筋を示す言い方にする。
   抜粋に複数の選択肢(例: 追加サンプルの抽出、代替的な手続、不備として是正し再評価 等)が示唆されている場合は、
   その分岐を簡潔に列挙する。
2. **根拠**: 上記の考え方がどの基準のどの内容に基づくかを、抜粋の文言を踏まえつつ自分の言葉でかみ砕いて説明する。
   基準名は `(基準名)によれば〜` のように文中で自然に触れる。一言一句の引用ではなく要約でよい。
   抜粋に具体的な数値例・計算例があれば、それがどういう前提(信頼度・許容逸脱率・母集団規模等)に基づく例かを
   明示した上で積極的に紹介する(ただし、抜粋にない具体的な数値を新たに作り出してはならない)。
3. **留意点**: 抜粋だけでは判断しきれない部分(状況依存の要素、抜粋に含まれない詳細な手続等)があれば触れる。
   数値例が質問の前提(件数・信頼度等)と完全には一致しない場合は、その差異も指摘する。

抜粋に書かれている内容の範囲を超えて、存在しない基準条文番号や数値を捏造してはいけない。
ただし、監査の一般的な考え方(なぜサンプリングリスクという概念があるか、等)を使って抜粋の内容を
分かりやすく補足説明することは推奨する。抜粋から質問に全く答えられない場合のみ、
その旨を正直に伝え、関連しそうな基準名や章立てを示すに留める。

最後に一言、最終的な適用判断は監査人自身の職業的専門家としての判断に委ねられる旨を添える。
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


def expand_query(question: str, config: AppConfig) -> str:
    """埋め込み検索用に、質問を関連専門用語で補ったテキストへ展開する。

    ユーザーの自然文の質問(例:「25件中1件不備が出たら追加サンプルは必要か」)は、
    監査基準の条文で使われる語彙(統制の逸脱、許容逸脱率、UPL等)とそのまま埋め込み類似度が
    離れてしまうことがあるため、検索専用にクエリを拡張してから埋め込みベクトル検索にかける。
    """
    try:
        result = chat_complete(
            [
                {"role": "system", "content": QUERY_EXPANSION_SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ],
            config=config.llm,
            max_tokens=200,
        )
        expanded = result["content"].strip().strip('"')
        return expanded if expanded else question
    except Exception:  # noqa: BLE001
        return question


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


def _rerank_candidates(
    question: str,
    candidates: list[StandardSource],
    config: AppConfig,
    *,
    max_select: int,
    snippet_chars: int = 220,
) -> list[StandardSource]:
    """候補を短い抜粋のみでLLMに見せ、本当に関連しそうなものだけ選び直す。

    候補プール全体(top_kを広く取った状態)は8192トークン制限に収まらないことが多いため、
    まず短い要約だけで安価に絞り込んでから、選ばれたものだけ全文を最終回答生成に使う。
    """
    if not candidates:
        return []

    listing = "\n\n".join(
        f"[{i}] 出典: {c.title}\n{c.excerpt[:snippet_chars]}" for i, c in enumerate(candidates)
    )
    prompt = RERANK_SYSTEM_PROMPT.format(max_select=max_select)
    result = chat_complete(
        [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"質問: {question}\n\n---候補---\n{listing}"},
        ],
        config=config.llm,
        max_tokens=300,
    )
    try:
        selected_idx = _extract_json(result["content"]).get("selected", [])
    except ValueError:
        selected_idx = []

    selected = [candidates[i] for i in selected_idx if isinstance(i, int) and 0 <= i < len(candidates)]
    return selected[:max_select] if selected else candidates[:max_select]


def answer_standard_query(
    question: str,
    config: AppConfig,
    *,
    top_k: int = 5,
    candidate_pool: int = 25,
) -> AnswerResult:
    client = get_client(config.chroma)
    standards = get_collection(client, config.chroma.standards_collection)

    search_text = expand_query(question, config)
    result = query(
        standards, text=search_text, embedding_config=config.embedding, n_results=candidate_pool
    )

    candidates = [
        StandardSource(title=meta["title"], excerpt=doc, distance=dist)
        for doc, meta, dist in zip(
            result["documents"][0], result["metadatas"][0], result["distances"][0]
        )
    ]

    sources = _rerank_candidates(question, candidates, config, max_select=top_k)

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
        max_tokens=1200,
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
