"""長いテキストを埋め込み用に適度なサイズへ分割する。"""
from __future__ import annotations


def chunk_text(text: str, *, chunk_size: int = 800, overlap: int = 150) -> list[str]:
    """文字数ベースの単純なスライディングウィンドウ分割。

    改行の少ないPDF抽出テキストを想定し、まず空行で粗く区切ってから、
    chunk_sizeを超える塊はさらにoverlap付きで機械的に分割する。
    """
    if not text.strip():
        return []

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [text.strip()]

    chunks: list[str] = []
    buffer = ""
    for para in paragraphs:
        candidate = f"{buffer}\n\n{para}" if buffer else para
        if len(candidate) <= chunk_size:
            buffer = candidate
            continue

        if buffer:
            chunks.append(buffer)
        if len(para) <= chunk_size:
            buffer = para
        else:
            # 段落自体が長すぎる場合は機械的にスライディングウィンドウで切る
            start = 0
            while start < len(para):
                end = start + chunk_size
                chunks.append(para[start:end])
                start = end - overlap
            buffer = ""

    if buffer:
        chunks.append(buffer)

    return chunks
