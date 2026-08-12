"""PDFバイナリからテキストを抽出し、訂正理由に関する箇所を切り出す。"""
from __future__ import annotations

import io
import re

import pdfplumber

# EDINETの様式は「【有価証券報告書の訂正報告書の提出理由】」のような角括弧見出しが多いため、
# 角括弧見出し(「理由」を含む)を優先して探し、見つからなければ地の文の「訂正の理由」等を探す。
BRACKETED_REASON_HEADING_RE = re.compile(r"【[^】]{0,40}理由[^】]{0,10}】")
PLAIN_REASON_HEADING_RE = re.compile(r"訂正(?:の)?理由")

MAX_PAGES = 15          # PDF全文を読むと重いので先頭N頁までに制限
EXCERPT_CHARS = 4000    # 見出し発見時、そこから取り出す文字数(訂正前後の数値対比表まで含めるため長め)
FALLBACK_CHARS = 3000   # 見出しが見つからない場合、先頭から取る文字数


def extract_text(pdf_bytes: bytes, *, max_pages: int = MAX_PAGES) -> str:
    text_parts: list[str] = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages[:max_pages]:
            page_text = page.extract_text() or ""
            text_parts.append(page_text)
    return "\n".join(text_parts)


def extract_reason_excerpt(pdf_bytes: bytes) -> str:
    """PDF本文から「訂正の理由」周辺のテキストを抜き出す。

    見出しが見つからない場合は、先頭ページ群のテキストをそのまま返す
    (臨時報告書など、見出しなしで理由が書かれている書式もあるため)。
    """
    full_text = extract_text(pdf_bytes)
    if not full_text.strip():
        return ""

    match = BRACKETED_REASON_HEADING_RE.search(full_text) or PLAIN_REASON_HEADING_RE.search(
        full_text
    )
    if match:
        start = match.start()
        return full_text[start : start + EXCERPT_CHARS].strip()

    return full_text[:FALLBACK_CHARS].strip()
