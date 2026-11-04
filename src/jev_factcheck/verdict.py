"""Combine the layers into one result per claim, with the four UI states.

  supported         quote found AND the judge says it supports the claim (probability shown, never a bare badge)
  not_supported     quote found, but the judge says contradicts / unrelated / not enough / out of context / unsure
  quote_not_found   the quote is not in the source (fabricated, altered, stitched, only similar)
  source_unavailable  the page could not be read (blocked, paywall, PDF, script-rendered, network)
  quote_only        quote found, judge not run (--no-judge, judge down, or injection-like text); NOT a support verdict

`reason` is a stable code; `action` is what the correction loop should ask of the LLM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .fetch import FetchResult
from .fragment import deep_link
from .judging import JudgeOutcome
from .match import _NEGATIONS, MatchResult, normalise
from .schema import Claim

SUPPORT_MIN = 0.60  # P(supports) needed to call it supported
OUT_OF_CONTEXT_MAX = 0.50
SHORT_PAGE = 600  # a page with less text than this and no match is probably not the real article

_NUMBER = re.compile(r"\d[\d.,]*\d|\d")


def _numbers(text: str) -> set[str]:
    """Numbers in a text, comparable across '1,000' / '1000' and a trailing sentence dot."""
    return {n.replace(",", "").rstrip(".") for n in _NUMBER.findall(normalise(text).text)}


def _negated(text: str) -> bool:
    return any(w in _NEGATIONS or w.endswith("n't") for w in re.findall(r"[\w']+", normalise(text).text))


def claim_flags(claim: Claim) -> list[str]:
    """Cheap, deterministic claim-vs-quote checks that need no judge. Flags, never verdicts: a claim may
    legitimately compute or rephrase numbers ('3 of 10' for '30%'), so a human looks at them."""
    flags: list[str] = []
    missing = sorted(_numbers(claim.claim) - _numbers(claim.quote))
    if missing:
        flags.append("claim_number_not_in_quote: " + ", ".join(missing[:5]))
    if _negated(claim.claim) != _negated(claim.quote):
        flags.append("negation_differs_between_claim_and_quote")
    return flags


STATES = ("supported", "not_supported", "quote_not_found", "source_unavailable", "quote_only")


@dataclass
class ClaimResult:
    claim: Claim
    state: str
    reason: str
    action: str  # none | requote | resource | retract | accept_limit
    explanation: str
    fetch: dict[str, Any] = field(default_factory=dict)
    match: MatchResult | None = None
    judge: JudgeOutcome | None = None
    source_text: str = ""  # the extracted page text offsets refer to
    source_flags: list[str] = field(default_factory=list)  # e.g. unusual_domain; flags, not verdicts
    source_note: str = ""
    flags: list[str] = field(default_factory=list)  # claim-vs-quote checks (numbers, negation); see claim_flags

    @property
    def deep_link(self) -> str:
        """Source URL with a `#:~:text=` fragment that scrolls to and highlights the matched quote ("" if none)."""
        m = self.match
        if not m or not m.found or not self.source_text or "pdf" in str(self.fetch.get("content_type", "")):
            return ""
        return deep_link(self.claim.url, self.source_text, m.spans, m.occurrences)

    def to_dict(self, with_text: bool = False) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.claim.id,
            "claim": self.claim.claim,
            "url": self.claim.url,
            "quote": self.claim.quote,
            "state": self.state,
            "reason": self.reason,
            "action": self.action,
            "explanation": self.explanation,
            "fetch": self.fetch,
            "match": self.match.to_dict() if self.match else None,
            "source_flags": self.source_flags,
            "source_note": self.source_note,
            "flags": self.flags,
            "deep_link": self.deep_link,
        }
        if self.judge:
            j = self.judge
            d["judge"] = {
                "ran": j.ran,
                "relation": j.relation,
                "probabilities": j.probabilities,
                "p_support": j.p_support,
                "p_out_of_context": j.p_out_of_context,
                "error": j.error,
                "injection_reason": j.injection_reason,
                "model": j.model,
                "sent_chars": j.sent_chars,
            }
        if with_text:
            d["source_text"] = self.source_text
        return d


def decide(
    claim: Claim, fetched: FetchResult, match: MatchResult | None, judge: JudgeOutcome | None, judging: bool
) -> ClaimResult:
    fdict = fetched.to_dict()
    base: dict[str, Any] = dict(claim=claim, fetch=fdict, match=match, judge=judge, source_text=fetched.text)
    if not fetched.ok:
        return ClaimResult(
            state="source_unavailable",
            reason=fetched.status,
            action="resource",
            explanation=f"The source could not be read ({fetched.status}: {fetched.detail}).",
            **base,
        )
    assert match is not None
    if match.found:
        base["flags"] = claim_flags(claim)
    if not match.found:
        why: tuple[str, str, str] = {
            "altered": ("altered_quote", "requote", "The quote differs from the source in a number or a negation."),
            "near": (
                "paraphrased_quote",
                "requote",
                "The source has a similar passage, but the quote is not verbatim.",
            ),
            "stitched": ("stitched_quote", "requote", "Parts of the quote exist, but not together as quoted."),
            "not_found": ("quote_not_in_source", "requote", "The quote does not appear in the source."),
        }[match.status]
        hint = ""
        if match.status == "not_found" and len(fetched.text) < SHORT_PAGE:
            hint = f" The page text is very short ({len(fetched.text)} characters): it may be a paywall, cookie wall or script-rendered page."
        elif "cuts_number" in match.flags:
            hint = " The quote starts or ends in the middle of a number."
        return ClaimResult(state="quote_not_found", reason=why[0], action=why[1], explanation=why[2] + hint, **base)
    if not judging:
        return ClaimResult(
            state="quote_only",
            reason="not_judged",
            action="accept_limit",
            explanation="The quote exists in the source. Whether it supports the claim was not judged.",
            **base,
        )
    if judge is None or not judge.ran:
        reason_key = "injection_like_text" if judge and judge.injection_reason else "judge_unavailable"
        text = (
            "The matched passage looks like an injection attempt, so it was not sent to the judge."
            if reason_key == "injection_like_text"
            else "The judge was unavailable; only the quote match is verified."
        )
        return ClaimResult(state="quote_only", reason=reason_key, action="accept_limit", explanation=text, **base)
    rel, p = judge.relation, judge.p_support or 0.0
    if rel == "supports" and p >= SUPPORT_MIN and (judge.p_out_of_context or 0.0) < OUT_OF_CONTEXT_MAX:
        return ClaimResult(
            state="supported",
            reason="judge_supports",
            action="none",
            explanation=f"The quote exists and the judge rates support at {p:.0%} (a probability, not a proof).",
            **base,
        )
    if rel == "supports" and (judge.p_out_of_context or 0.0) >= OUT_OF_CONTEXT_MAX:
        return ClaimResult(
            state="not_supported",
            reason="possibly_out_of_context",
            action="requote",
            explanation="The quote exists but may mean something different in its context.",
            **base,
        )
    table = {
        "contradicts": ("contradicted", "resource", "The quote exists, but the passage conflicts with the claim."),
        "unrelated": ("unrelated", "resource", "The quote exists, but is about something else than the claim."),
        "not_enough": (
            "source_lacks_info",
            "retract",
            "The passage is on topic but does not say enough to confirm the claim.",
        ),
        "supports": ("uncertain_support", "requote", f"The judge leans towards support but only at {p:.0%}."),
    }
    reason, action, text = table[rel or "not_enough"]
    return ClaimResult(state="not_supported", reason=reason, action=action, explanation=text, **base)
