"""実務相談用のシンプルなローカルWeb UI(Streamlit)。

使い方:
    streamlit run src/rag_app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st

from app_config import load_config
from rag_answer import answer_case_query, answer_standard_query, classify_intent

st.set_page_config(page_title="EDINET訂正報告書 実務相談", page_icon="📋")

st.title("📋 EDINET訂正報告書 実務相談")
st.caption(
    "過去の訂正報告書の事例照会、または監査基準委員会報告書に基づく実務手続の参照を行います。"
    "回答は基準の参照に留め、最終判断は利用者に委ねる設計です。すべてローカルLLMで完結します。"
)

config = load_config()

with st.form("question_form"):
    question = st.text_area(
        "質問を入力してください",
        placeholder="例: サンプリングで不備が見つかった場合、サンプル数を拡大すべきですか\n"
        "例: 三菱UFJアセットマネジメントの投資信託でよくある訂正理由は？",
        height=100,
    )
    submitted = st.form_submit_button("質問する")

if submitted:
    if not question.strip():
        st.warning("質問を入力してください。")
    else:
        # 進捗表示は単一の st.status コンテナに集約する。
        # st.spinner/st.info を連続して出し入れすると、まれにStreamlitのReact描画側で
        # 「insertBefore」DOMエラーが発生することがあるため(既知の描画バグ)、
        # 計算中の動的な要素追加・削除を最小限に留めている。
        with st.status("質問の種類を判定しています...", expanded=False) as status:
            intent = classify_intent(question, config)
            if intent == "case":
                status.update(label="類似事例を検索しています...")
                result = answer_case_query(question, config)
            else:
                status.update(label="関連する基準を検索し、回答を生成しています...")
                result = answer_standard_query(question, config)
            status.update(label="完了", state="complete")

        if intent == "case":
            st.info("🔍 過去事例の照会として回答します。")
        else:
            st.info("📖 監査基準の参照として回答します。")

        st.markdown(result.answer_text)

        if result.case_hits:
            with st.expander("検索結果の詳細"):
                for h in result.case_hits:
                    st.markdown(
                        f"- **{h.importance}** {h.filer_name} / {h.doc_description} "
                        f"— {h.reason} (`{h.doc_id}`, 距離={h.distance:.3f})"
                    )
        if result.standard_sources:
            with st.expander("参照した基準の抜粋"):
                for s in result.standard_sources:
                    st.markdown(f"**{s.title}** (距離={s.distance:.3f})")
                    st.text(s.excerpt[:500])
                    st.markdown("---")

st.divider()
st.caption(
    f"LLM: {config.llm.model} / 埋め込み: {config.embedding.model} "
    f"(LM Studio: {config.llm.base_url})"
)
