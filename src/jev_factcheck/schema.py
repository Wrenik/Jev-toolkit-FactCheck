"""The claims file: the only contract between the LLM (in a Claude Code session) and this tool.

The LLM writes `claims.json`; this tool reads it, checks it and writes `corrections.json` back.
Everything in the file is untrusted text, so it is validated and size-bounded here, once.

    {
      "text": "The answer text, with claims in it.",
      "claims": [
        {"id": "c1", "claim": "Water boils at 100 C at sea level.",
         "url": "https://example.org/boiling", "quote": "Water boils at 100 degrees Celsius ...",
         "topic": "science", "span": [0, 36]}
      ]
    }

`span` is optional: character offsets of the claim inside `text` (used to mark it in the HTML).
If it is missing, the claim is marked where its exact text occurs in `text` (if it does),
otherwise it is shown as a footnote only.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

MAX_CLAIMS = 200
MAX_TEXT = 100_000
MAX_CLAIM = 600
MAX_QUOTE = 1500
MAX_URL = 2000
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_ID = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")


class SchemaError(ValueError):
    """The claims file is malformed. The message says which field."""


@dataclass(frozen=True)
class Claim:
    id: str
    claim: str
    url: str
    quote: str
    topic: str = "general"
    span: tuple[int, int] | None = None


@dataclass
class ClaimsFile:
    text: str
    claims: list[Claim] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "claims": [
                {"id": c.id, "claim": c.claim, "url": c.url, "quote": c.quote, "topic": c.topic,
                 **({"span": list(c.span)} if c.span else {})}
                for c in self.claims
            ],
        }


def _clean(value: Any, field_name: str, limit: int, *, required: bool = True) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise SchemaError(f"{field_name}: expected a string")
    value = _CONTROL.sub("", value)
    if required and not value.strip():
        raise SchemaError(f"{field_name}: must not be empty")
    if len(value) > limit:
        raise SchemaError(f"{field_name}: longer than {limit} characters ({len(value)})")
    return value


def parse_claims(data: Any) -> ClaimsFile:
    if not isinstance(data, dict):
        raise SchemaError("top level must be an object with 'text' and 'claims'")
    text = _clean(data.get("text", ""), "text", MAX_TEXT, required=False)
    raw = data.get("claims")
    if not isinstance(raw, list):
        raise SchemaError("claims: expected a list")
    if len(raw) > MAX_CLAIMS:
        raise SchemaError(f"claims: more than {MAX_CLAIMS}")
    claims: list[Claim] = []
    seen: set[str] = set()
    for i, item in enumerate(raw):
        where = f"claims[{i}]"
        if not isinstance(item, dict):
            raise SchemaError(f"{where}: expected an object")
        cid = item.get("id", f"c{i + 1}")
        if not isinstance(cid, str) or not _ID.match(cid):
            raise SchemaError(f"{where}.id: use 1-40 letters, digits, '_', '.', '-'")
        if cid in seen:
            raise SchemaError(f"{where}.id: duplicate id {cid!r}")
        seen.add(cid)
        span = item.get("span")
        if span is not None:
            if (not isinstance(span, list) or len(span) != 2 or not all(isinstance(x, int) and not isinstance(x, bool) for x in span)
                    or not 0 <= span[0] < span[1] <= len(text)):
                raise SchemaError(f"{where}.span: expected [start, end] inside 'text'")
            span = (span[0], span[1])
        claims.append(
            Claim(
                id=cid,
                claim=_clean(item.get("claim"), f"{where}.claim", MAX_CLAIM),
                url=_clean(item.get("url"), f"{where}.url", MAX_URL).strip(),
                quote=_clean(item.get("quote"), f"{where}.quote", MAX_QUOTE),
                topic=_clean(item.get("topic", "general"), f"{where}.topic", 40).strip() or "general",
                span=span,
            )
        )
    # No explicit span: if the claim sentence appears verbatim in the text (and is free), mark it there.
    taken = [c.span for c in claims if c.span]
    for i, c in enumerate(claims):
        if c.span is None and text:
            pos = text.find(c.claim)
            if pos != -1 and all(pos + len(c.claim) <= a or pos >= b for a, b in taken):
                claims[i] = Claim(c.id, c.claim, c.url, c.quote, c.topic, (pos, pos + len(c.claim)))
                taken.append(claims[i].span)
    spans = sorted(c.span for c in claims if c.span)
    for a, b in zip(spans, spans[1:]):
        if b[0] < a[1]:
            raise SchemaError(f"claims overlap in 'text': {list(a)} and {list(b)}")
    return ClaimsFile(text=text, claims=claims)


def load_claims(path: str) -> ClaimsFile:
    try:
        with open(path, encoding="utf-8-sig") as fh:
            return parse_claims(json.load(fh))
    except json.JSONDecodeError as exc:
        raise SchemaError(f"not valid JSON: {exc}") from exc
