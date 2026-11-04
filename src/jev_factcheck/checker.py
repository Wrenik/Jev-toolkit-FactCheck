"""Run the whole check for a claims file: fetch, match, (judge), decide."""

from __future__ import annotations

from typing import Any, Protocol

from jev_core import Judge

from .fetch import FetchResult
from .judging import InjectionCheck, judge_support
from .match import match_quote
from .schema import ClaimsFile
from .verdict import ClaimResult, decide


class Fetches(Protocol):
    def fetch(self, url: str) -> FetchResult: ...


def check_claims(
    cf: ClaimsFile,
    fetcher: Fetches,
    judge: Judge | None,
    *,
    injection_check: InjectionCheck | None = None,
    source_check: Any = None,
) -> list[ClaimResult]:
    """`judge=None` is --no-judge mode: only the quote match is checked."""
    pages: dict[str, FetchResult] = {}  # each URL is fetched once per run
    results: list[ClaimResult] = []
    for claim in cf.claims:
        if claim.url not in pages:
            pages[claim.url] = fetcher.fetch(claim.url)
        page = pages[claim.url]
        match = outcome = None
        if page.ok:
            match = match_quote(page.text, claim.quote)
            if match.found and judge is not None:
                outcome = judge_support(judge, claim.claim, claim.quote, page.text, match, injection_check)
        res = decide(claim, page, match, outcome, judging=judge is not None)
        if source_check is not None:
            res.source_flags, res.source_note = source_check(claim.url, claim.topic)
        results.append(res)
    return results


def summarize(results: list[ClaimResult]) -> str:
    """A plain-words summary for the terminal."""
    n = len(results)
    counts: dict[str, int] = {}
    for r in results:
        counts[r.state] = counts.get(r.state, 0) + 1
    lines = [f"{n} claims checked."]
    labels = {
        "supported": "quote found and the judge rates it as supporting the claim",
        "not_supported": "quote found, but the source does not support the claim",
        "quote_not_found": "the quote is NOT in the source",
        "source_unavailable": "the source could not be read",
        "quote_only": "quote found, support not judged",
    }
    for state, text in labels.items():
        if counts.get(state):
            lines.append(f"  {counts[state]:>3}  {text}")
    for r in results:
        if r.state != "supported":
            lines.append(f"  - {r.claim.id}: {r.explanation}")
        if r.flags:
            lines.append(f"  - {r.claim.id}: check this: {'; '.join(r.flags)}")
        if r.source_flags:
            lines.append(f"  - {r.claim.id}: source flag {', '.join(r.source_flags)} (a flag, not a verdict)")
    lines.append("This checks support by the cited source, not that the source is true.")
    return "\n".join(lines)
