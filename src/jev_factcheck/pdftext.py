"""Optional PDF text extraction (extra `pdf`: pypdf, pure Python, no network, no JavaScript run).

Limits: page count and characters are capped (a hostile or huge PDF cannot take unbounded time or memory
beyond the 2 MB fetch cap), encrypted files are refused, scanned PDFs without a text layer come out empty
(reported as "empty", never OCR'd). Text order follows pypdf's reading of the content stream, so a
two-column layout can interleave columns: a quote spanning columns may be "not found" while a quote inside
one column matches. Hyphenated line breaks are healed later by the matcher.
"""

from __future__ import annotations

import io

from .htmltext import PageText

MAX_PAGES = 150
MAX_CHARS = 1_500_000


def available() -> bool:
    try:
        import pypdf  # noqa: F401
    except ImportError:
        return False
    return True


def extract_pdf(body: bytes) -> PageText:
    """Text of the PDF, page by page. Raises ValueError with a short reason when it cannot be read."""
    import pypdf

    try:
        reader = pypdf.PdfReader(io.BytesIO(body))
        if reader.is_encrypted:
            raise ValueError("encrypted PDF")
        parts: list[str] = []
        total = 0
        for i, page in enumerate(reader.pages):
            if i >= MAX_PAGES or total > MAX_CHARS:
                break
            t = page.extract_text() or ""
            parts.append(t)
            total += len(t)
        title = ""
        meta = reader.metadata
        if meta and meta.title:
            title = str(meta.title)
    except ValueError:
        raise
    except Exception as exc:  # pypdf raises many types on malformed input
        raise ValueError(f"unreadable PDF ({type(exc).__name__})") from exc
    from .htmltext import _tidy

    return PageText(_tidy("\n\n".join(parts))[:MAX_CHARS], title, 0)
