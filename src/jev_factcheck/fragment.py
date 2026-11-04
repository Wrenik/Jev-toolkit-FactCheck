"""Text-fragment deep links (`url#:~:text=...`): clicking a citation opens the source scrolled to the quote.

Built from the match offsets in the extracted page text. Browsers that do not support text fragments
(or pages whose rendered text differs from the extracted text) just open the page: a link that
fails to highlight is harmless, so this is a convenience, never evidence. Only found quotes
(exact / normalised / elided) get a link.

Syntax (WICG Scroll-to-Text Fragment): `#:~:text=[prefix-,]textStart[,textEnd][,-suffix]`; each part is
percent-encoded, and `-`, `,` and `&` MUST be encoded because they are delimiters. `textStart` cannot
span block elements, so it never crosses a newline of the extracted text; a long quote uses the
`textStart,textEnd` range form (the range may span blocks).
"""

from __future__ import annotations

from urllib.parse import quote, urldefrag, urlsplit

WORDS = 5  # words per end of the range form
SHORT_WORDS = 8  # a segment up to this many words is used whole
PREFIX_WORDS = 3
MAX_URL = 1800


def _enc(s: str) -> str:
    return quote(s, safe="").replace("-", "%2D")


def _words(s: str) -> list[str]:
    return s.split()


def text_fragment(text: str, segments: list[tuple[int, int]], occurrences: int = 1) -> str:
    """The `:~:text=` directive (without the leading `#`) for the matched segments, or "" if none can be built."""
    segs = [(s, e) for s, e in sorted(segments) if 0 <= s < e <= len(text)]
    if not segs:
        return ""
    first = text[segs[0][0] : segs[0][1]]
    last = text[segs[-1][0] : segs[-1][1]]
    # textStart must sit inside one block: take only the first line of the first segment / last line of the last.
    head = _words(first.split("\n")[0])
    tail = _words(last.split("\n")[-1])
    if not head or not tail:
        return ""
    if len(segs) == 1 and "\n" not in first.strip() and len(head) <= SHORT_WORDS:
        start, end = " ".join(head), ""
    else:
        start, end = " ".join(head[:WORDS]), " ".join(tail[-WORDS:])
    prefix = ""
    if occurrences > 1:
        before = text[max(0, segs[0][0] - 80) : segs[0][0]].split("\n")[-1]
        pw = _words(before)[-PREFIX_WORDS:]
        prefix = " ".join(pw)
    out = "text="
    if prefix:
        out += _enc(prefix) + "-,"
    out += _enc(start)
    if end:
        out += "," + _enc(end)
    return out


def deep_link(url: str, text: str, segments: list[tuple[int, int]], occurrences: int = 1) -> str:
    """`url` with a text-fragment directive, or "" (not http/https, or nothing to point at, or too long)."""
    if urlsplit(url).scheme not in ("http", "https"):
        return ""
    frag = text_fragment(text, segments, occurrences)
    if not frag:
        return ""
    base = urldefrag(url)[0]  # an existing #anchor is replaced: only one fragment can be used
    link = f"{base}#:~:{frag}"
    return link if len(link) <= MAX_URL else ""
