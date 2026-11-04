"""Turn fetched bytes into plain text without executing anything.

HTML goes through the stdlib parser (no scripts, no network, no rendering). Dropped on purpose:
script/style/noscript/template/svg/iframe/head contents and elements a reader cannot see
(`hidden`, `aria-hidden="true"`, inline `display:none` / `visibility:hidden`). A quote that only
exists in hidden text is therefore "not found": a person reading the page would not see it, and
hidden text is the usual place for injected instructions. The number of dropped characters is reported.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser

_SKIP = {"script", "style", "noscript", "template", "svg", "iframe", "head", "object", "embed", "math", "canvas"}
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
_BLOCK = {
    "p", "div", "br", "li", "ul", "ol", "tr", "table", "section", "article", "header", "footer", "h1", "h2", "h3",
    "h4", "h5", "h6", "blockquote", "pre", "dd", "dt", "dl", "figure", "figcaption", "main", "aside", "nav", "form",
}
_HIDDEN_STYLE = re.compile(r"(?:display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0(?:px|pt|em|rem)?\s*(?:;|$))", re.I)


@dataclass
class PageText:
    text: str
    title: str
    dropped_chars: int  # text inside hidden / non-visible elements that was not kept


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self._skip: list[str] = []
        self._in_title = False
        self.dropped = 0

    def handle_starttag(self, tag, attrs):
        if tag in _VOID:
            if tag == "br" and not self._skip:
                self.parts.append("\n")
            return
        if tag == "title":
            self._in_title = True
        if tag == "body" and self._skip and self._skip[0] == "head":
            self._skip = []  # a <head> that was never closed must not swallow the page
        if self._skip:
            self._skip.append(tag)
            return
        a = {k: (v or "") for k, v in attrs}
        hidden = (
            tag in _SKIP
            or "hidden" in a
            or a.get("aria-hidden", "").lower() == "true"
            or bool(_HIDDEN_STYLE.search(a.get("style", "")))
        )
        if hidden:
            self._skip.append(tag)
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        if tag == "br" and not self._skip:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if self._skip:
            if tag in self._skip:
                while self._skip and self._skip.pop() != tag:
                    pass
            return
        if tag in _BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title_parts.append(data)
        if self._skip:
            if not data.isspace():
                self.dropped += len(data)
            return
        # The <title> lives in <head>, which is skipped; keep body text only.
        self.parts.append(data)


def _tidy(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    lines = [re.sub(r"[ \t\f\v]+", " ", ln).strip() for ln in text.split("\n")]
    out: list[str] = []
    blank = 0
    for ln in lines:
        if ln:
            blank = 0
            out.append(ln)
        else:
            blank += 1
            if blank == 1 and out:
                out.append("")
    return "\n".join(out).strip()


def looks_like_html(raw: str) -> bool:
    head = raw[:2000].lower()
    return "<html" in head or "<body" in head or "<!doctype html" in head or "<p" in head or "<div" in head


def extract_text(raw: str, content_type: str = "text/html") -> PageText:
    if "html" in content_type or (content_type.startswith("text/") and looks_like_html(raw)):
        p = _Extractor()
        try:
            p.feed(raw)
            p.close()
        except Exception:  # the parser is lenient; if it ever raises, fall back to nothing rather than crash
            return PageText("", "", 0)
        return PageText(_tidy("".join(p.parts)), _tidy(" ".join(p.title_parts)), p.dropped)
    return PageText(_tidy(raw), "", 0)
