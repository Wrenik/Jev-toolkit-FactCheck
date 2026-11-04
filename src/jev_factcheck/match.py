"""Deterministic quote matching with offsets into the ORIGINAL fetched text.

The quote is what the LLM claims the source says. This module answers one question and nothing
else: is that quote really in the source text, and where? It never judges meaning.

Statuses (see docs/FACT_CHECKER.md, "Quote matching"):

  exact       the quote occurs character for character.
  normalised  it occurs after harmless normalisation only (case, whitespace, curly quotes, dash
              variants, NFKC, soft hyphens/zero-width characters, line-break hyphenation, HTML entities).
  elided      the quote uses "..." / "[...]" and every piece occurs, in order.
  near        no match, but a passage is very similar. Reported, NEVER counted as "found".
  altered     near, and a number or a negation word differs: the worst silent error (a 5% that
              became 15%, a "not" that vanished). Always a misquote.
  stitched    no match as a whole, but separate pieces of the quote exist at different places.
  not_found   nothing close. Fabricated, or the page has no such text (paywall, script-rendered).

Only exact / normalised / elided count as "the quote exists". Offsets (`start`, `end`, and each
segment) are indexes into the text passed in, which is the extracted page text that the report also
stores, so the highlight is reproducible.
"""

from __future__ import annotations

import difflib
import functools
import html
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

FOUND_STATUSES = ("exact", "normalised", "elided")

MIN_QUOTE_CHARS = 20  # shorter quotes match too easily; flagged "short_quote"
MIN_SEGMENT_CHARS = 8  # each piece around an ellipsis
WIDE_GAP_CHARS = 3000  # an ellipsis that skips more than this is flagged "wide_gap"
NEAR_THRESHOLD = 0.80  # token-level similarity to report a near match at all
STITCH_MIN_PIECE = 20

_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−﹘﹣－"), "-")
_QUOTES = {
    **dict.fromkeys(map(ord, "‘’‚‛′ʼ`´"), "'"),
    **dict.fromkeys(map(ord, "“”„‟″«»"), '"'),
}
_INVISIBLE = set("­​‌‍⁠﻿‎‏‪‫‬‭‮⁦⁧⁨⁩")
_NEGATIONS = {"not", "no", "never", "none", "neither", "nor", "cannot", "without", "n't", "nothing", "nobody", "hardly"}
_NUMBER_WORDS = set(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen "
    "nineteen twenty thirty forty fifty sixty seventy eighty ninety hundred thousand million billion trillion half double triple "
    "first second third fourth fifth majority minority".split()
)
_ELLIPSIS = re.compile(r"\s*(?:\[\s*(?:\.{3}|…)\s*\]|\.{3,}|…)\s*")
_TOKEN = re.compile(r"\d[\d.,]*\d%?|\d%?|[^\W\d_]+(?:'[^\W\d_]+)?|\S")


@dataclass(frozen=True)
class Normalised:
    """Normalised text plus, for every normalised character, the original span it came from."""

    text: str
    starts: tuple[int, ...]
    ends: tuple[int, ...]


@functools.lru_cache(maxsize=8)  # many claims cite the same page; normalising 2 MB is the slow part
def normalise(original: str) -> Normalised:
    out: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    n = len(original)
    i = 0
    while i < n:
        ch = original[i]
        if ch in _INVISIBLE:
            i += 1
            continue
        # Line-break hyphenation: "exam-\nple" -> "example" (only letter-hyphen-newline-lowercase).
        if ch in "-‐‑" and out and out[-1].isalpha():
            j = i + 1
            while j < n and original[j] in " \t\r":
                j += 1
            if j < n and original[j] == "\n":
                k = j + 1
                while k < n and original[k] in " \t\r":
                    k += 1
                if k < n and original[k].islower():
                    i = k
                    continue
        piece = unicodedata.normalize("NFKC", ch)
        piece = piece.translate(_DASHES).translate(_QUOTES).casefold()
        for p in piece:
            if p.isspace():
                if out and out[-1] == " ":
                    ends[-1] = i + 1
                    continue
                p = " "
            out.append(p)
            starts.append(i)
            ends.append(i + 1)
        i += 1
    return Normalised("".join(out), tuple(starts), tuple(ends))


def normalise_quote(quote: str) -> str:
    """Same normalisation for the quote, after turning HTML entities into characters."""
    if "&" in quote:
        quote = html.unescape(quote)
    return normalise(quote).text.strip()


@dataclass
class MatchResult:
    status: str
    start: int | None = None
    end: int | None = None
    segments: list[tuple[int, int]] = field(default_factory=list)
    occurrences: int = 0
    similarity: float | None = None
    differences: list[dict[str, str]] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    note: str = ""

    @property
    def found(self) -> bool:
        return self.status in FOUND_STATUSES

    def matched_text(self, original: str) -> str:
        if self.start is None or self.end is None:
            return ""
        return original[self.start : self.end]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "start": self.start,
            "end": self.end,
            "segments": [list(s) for s in self.segments],
            "occurrences": self.occurrences,
            "similarity": self.similarity,
            "differences": self.differences,
            "flags": self.flags,
            "note": self.note,
        }


def _find_all(haystack: str, needle: str, limit: int = 50) -> list[int]:
    found: list[int] = []
    pos = haystack.find(needle)
    while pos != -1 and len(found) < limit:
        found.append(pos)
        pos = haystack.find(needle, pos + 1)
    return found


def _span(norm: Normalised, a: int, b: int) -> tuple[int, int]:
    """Normalised [a, b) -> original [start, end), trimmed of surrounding whitespace."""
    while a < b and norm.text[a] == " ":
        a += 1
    while b > a and norm.text[b - 1] == " ":
        b -= 1
    return norm.starts[a], norm.ends[b - 1]


_OPEN_CLOSE = {'"': '"', "“": "”", "„": "“", "«": "»", "‘": "’", "'": "'", "‚": "‘"}


def _strip_wrapping_quotes(q: str) -> str:
    """LLMs often put the quotation marks of the quote itself around it: "like this". Those are not source text."""
    for _ in range(2):
        if len(q) > 2 and q[0] in _OPEN_CLOSE and q[-1] in (_OPEN_CLOSE[q[0]], q[0]) and q[0] not in q[1:-1]:
            q = q[1:-1].strip()
        else:
            break
    return q


def _cuts_number(original: str, s: int, e: int) -> bool:
    """The match starts or ends inside a number ("grew 15" matching "grew 150")."""
    if s > 0 and original[s].isdigit() and original[s - 1].isdigit():
        return True
    if e < len(original) and original[e - 1].isdigit() and (
        original[e].isdigit() or (original[e] in ".," and e + 1 < len(original) and original[e + 1].isdigit())
    ):
        return True
    return False


_BEFORE = re.compile(r"[\w'’-]+")


def _negated_before(original: str, s: int, quote_start: str) -> bool:
    """A negation word shortly before the match, in the same sentence, that the quote does not contain."""
    window = original[max(0, s - 40) : s]
    cut = max(window.rfind(c) for c in (".", "!", "?", ";", chr(10)))
    words = [w.lower().replace("’", "'") for w in _BEFORE.findall(window[cut + 1 :])][-3:]
    return any(w in _NEGATIONS or w.endswith("n't") for w in words) and not any(
        w in _NEGATIONS or w.endswith("n't") for w in quote_start.lower().split()[:3]
    )


def _audit(r: MatchResult, original: str, q: str) -> MatchResult:
    """Boundary checks on a found quote: cutting a number turns it into 'altered'; a negation just before is flagged."""
    spans = r.segments or [(r.start, r.end)]
    if any(_cuts_number(original, a, b) for a, b in spans):
        r.status, r.similarity = "altered", None
        r.flags = r.flags + ["cuts_number"]
        r.note = "the quote starts or ends in the middle of a number"
        return r
    if _negated_before(original, spans[0][0], q):
        r.flags = r.flags + ["preceded_by_negation"]
    return r


def match_quote(original: str, quote: str) -> MatchResult:
    """Locate `quote` in `original`. Never raises on odd input; empty quotes are not_found."""
    r = _match_quote(original, quote)
    if r.found:
        r = _audit(r, original, quote)
    return r


def _match_quote(original: str, quote: str) -> MatchResult:
    flags: list[str] = []
    q = quote.strip()
    if not q or not original:
        return MatchResult("not_found", note="empty quote or empty source text")
    if "&" in q:
        q = html.unescape(q)
    q = _strip_wrapping_quotes(q)
    if len(q) < MIN_QUOTE_CHARS:
        flags.append("short_quote")

    # 1. Verbatim.
    hits = _find_all(original, q)
    if hits:
        return MatchResult("exact", hits[0], hits[0] + len(q), [(hits[0], hits[0] + len(q))], len(hits), 1.0, flags=flags)

    norm = normalise(original)
    nq = normalise(q).text.strip()

    # 2. Whole quote after normalisation.
    if nq:
        hits = _find_all(norm.text, nq)
        if hits:
            s, e = _span(norm, hits[0], hits[0] + len(nq))
            return MatchResult("normalised", s, e, [(s, e)], len(hits), 1.0, flags=flags)

    # 3. Ellipsis: every piece, in order.
    pieces = [p for p in _ELLIPSIS.split(q) if p.strip()]
    if len(pieces) > 1 or _ELLIPSIS.search(q):
        r = _match_pieces(norm, pieces, flags)
        if r is not None:
            return r

    # 4. Stitched from separate places?
    stitched = _stitched(norm, nq)
    if stitched is not None:
        stitched.flags = flags + stitched.flags
        return stitched

    # 5. Near match with a diff of numbers and negations.
    near = _near(norm, nq)
    if near is not None:
        near.flags = flags + near.flags
        return near

    return MatchResult("not_found", flags=flags, note="no passage in the source is similar to the quote")


def _match_pieces(norm: Normalised, pieces: list[str], flags: list[str]) -> MatchResult | None:
    flags = list(flags)
    segments: list[tuple[int, int]] = []
    cursor = 0
    prev_end = None
    for piece in pieces:
        np_ = normalise(piece).text.strip()
        if len(np_) < MIN_SEGMENT_CHARS:
            flags.append("short_segment")
        if not np_:
            continue
        pos = norm.text.find(np_, cursor)
        if pos == -1:
            return None
        s, e = _span(norm, pos, pos + len(np_))
        if prev_end is not None and s - prev_end > WIDE_GAP_CHARS and "wide_gap" not in flags:
            flags.append("wide_gap")
        segments.append((s, e))
        prev_end = e
        cursor = pos + len(np_)
    if not segments:
        return None
    return MatchResult("elided", segments[0][0], segments[-1][1], segments, 1, 1.0, flags=flags)


def _stitched(norm: Normalised, nq: str) -> MatchResult | None:
    """Split the quote at sentence ends; if every part exists but not together, it is stitched."""
    parts = [p.strip() for p in re.split(r"(?<=[.!?;])\s+", nq) if p.strip()]
    if len(parts) < 2:
        mid = len(nq) // 2
        cut = nq.rfind(" ", 0, mid + 1)
        parts = [nq[:cut].strip(), nq[cut:].strip()] if cut > 0 else []
    if len(parts) < 2 or any(len(p) < STITCH_MIN_PIECE for p in parts):
        return None
    spans: list[tuple[int, int]] = []
    for p in parts:
        pos = norm.text.find(p)
        if pos == -1:
            return None
        spans.append(_span(norm, pos, pos + len(p)))
    return MatchResult(
        "stitched",
        min(s for s, _ in spans),
        max(e for _, e in spans),
        spans,
        1,
        flags=["pieces_not_adjacent"],
        note="each part of the quote exists, but not together as quoted",
    )


def _tokens(text: str) -> list[tuple[str, int, int]]:
    return [(m.group(0), m.start(), m.end()) for m in _TOKEN.finditer(text)]


def _is_critical(token: str) -> bool:
    return any(c.isdigit() for c in token) or token in _NEGATIONS or token in _NUMBER_WORDS or token.endswith("n't")


def _near(norm: Normalised, nq: str) -> MatchResult | None:
    qt = _tokens(nq)
    if len(qt) < 4:
        return None
    dt = _tokens(norm.text)
    if len(dt) < 4:
        return None
    qwords = [t[0] for t in qt]
    dwords = [t[0] for t in dt]
    n = 3
    index: dict[tuple[str, ...], list[int]] = {}
    for i in range(len(dwords) - n + 1):
        index.setdefault(tuple(dwords[i : i + n]), []).append(i)
    votes: dict[int, int] = {}
    for j in range(len(qwords) - n + 1):
        for pos in index.get(tuple(qwords[j : j + n]), [])[:200]:
            votes[pos - j] = votes.get(pos - j, 0) + 1
    # Also seed from single rare-ish words so a number swap in a short quote still finds its place.
    if not votes:
        counts: dict[str, int] = {}
        for w in dwords:
            counts[w] = counts.get(w, 0) + 1
        for j, w in enumerate(qwords):
            if len(w) > 3 and counts.get(w, 0) <= 3 and w.isalpha():
                for pos in [i for i, d in enumerate(dwords) if d == w][:3]:
                    votes[pos - j] = votes.get(pos - j, 0) + 1
    if not votes:
        return None
    m = len(qwords)
    best: tuple[float, int, int, list] | None = None
    for off, _ in sorted(votes.items(), key=lambda kv: -kv[1])[:8]:
        lo = max(0, off - 2)
        hi = min(len(dwords), off + m + 2)
        sm = difflib.SequenceMatcher(None, qwords, dwords[lo:hi], autojunk=False)
        ops = sm.get_opcodes()
        eq = [op for op in ops if op[0] == "equal"]
        if not eq:
            continue
        matched = sum(op[2] - op[1] for op in eq)
        d_len = (lo + eq[-1][4]) - (lo + eq[0][3])
        ratio = 2 * matched / (m + d_len)  # window padding does not count against the match
        if best is None or ratio > best[0]:
            best = (ratio, lo, hi, ops)
    if best is None or best[0] < NEAR_THRESHOLD:
        return None
    ratio, lo, hi, ops = best
    equal_idx = [k for k, op in enumerate(ops) if op[0] == "equal"]
    if not equal_idx:
        return None
    first_k, last_k = equal_idx[0], equal_idx[-1]
    # The passage runs from the first to the last op that touches source tokens (equal or replaced), so
    # a changed number at the very end of the quote is still inside the reported span.
    touching = [op for op in ops if op[0] in ("equal", "replace") and op[4] > op[3]]
    first_doc = lo + touching[0][3]
    last_doc = lo + touching[-1][4] - 1
    diffs: list[dict[str, str]] = []
    for k, (tag, i1, i2, j1, j2) in enumerate(ops):
        if tag == "equal":
            continue
        if tag == "insert" and (k < first_k or k > last_k):
            continue  # surrounding context of the window, not part of the quote
        diffs.append({"quote": " ".join(qwords[i1:i2]), "source": " ".join(dwords[lo + j1 : lo + j2])})
    s = dt[first_doc][1]
    e = dt[last_doc][2]
    s_o, e_o = _span(norm, s, e)
    critical = any(
        _is_critical(tok)
        for d in diffs
        for side in ("quote", "source")
        for tok in d[side].split()
    )
    status = "altered" if critical else "near"
    return MatchResult(
        status,
        s_o,
        e_o,
        [(s_o, e_o)],
        1,
        round(ratio, 3),
        diffs,
        flags=["number_or_negation_differs"] if critical else [],
        note="a number or negation differs from the source" if critical else "similar passage, not a verbatim quote",
    )
