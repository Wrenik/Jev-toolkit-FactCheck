"""A crude offline judge for the demo and as an evaluation BASELINE. It is not Jev and not a model.

It looks at word overlap between the claim and the passage and at negation parity. It exists so that
`python -m jev_factcheck demo` runs with no key and no network, and so the evaluation has a dumb
baseline that a real judge should beat. Its numbers are reported as "word-overlap baseline".
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from jev_core import Pick, PickAnswer, Question, Verdict, YesNo, YesNoAnswer

_WORD = re.compile(r"[a-z0-9][a-z0-9,.%-]*[a-z0-9%]|[a-z0-9]", re.I)
_STOP = set(
    [
        "the",
        "a",
        "an",
        "of",
        "in",
        "on",
        "at",
        "to",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "it",
        "its",
        "and",
        "or",
        "for",
        "with",
        "by",
        "as",
        "that",
        "this",
        "from",
        "has",
        "have",
        "had",
        "will",
        "would",
    ]
)
_NEG = {"not", "no", "never", "none", "cannot", "unchanged", "abolished", "without", "impossible"}


def _words(text: str) -> set[str]:
    return {w.lower().strip(".,") for w in _WORD.findall(text) if w.lower() not in _STOP}


class DemoJudge:
    name = "demo"
    model = "word-overlap-baseline"

    def ask(self, state, questions: Mapping[str, Question]) -> Verdict:
        claim, quote, passage = state["claim"], state["quote"], state["passage"]
        cw, qw = _words(claim), _words(quote)
        overlap = len(cw & qw) / max(1, len(cw))
        neg_claim = bool(cw & _NEG) or " not " in f" {claim.lower()} "
        neg_quote = bool(qw & _NEG)
        if overlap >= 0.6:
            rel = "contradicts" if neg_claim != neg_quote else "supports"
        elif overlap >= 0.25:
            rel = "not_enough"
        else:
            rel = "unrelated"
        probs = {k: 0.05 for k in ("supports", "contradicts", "unrelated", "not_enough")}
        probs[rel] = 0.85
        answers: dict[str, Any] = {}
        for name, q in questions.items():
            if isinstance(q, Pick):
                answers[name] = PickAnswer(rel, 0.85, probs)
            elif isinstance(q, YesNo):
                hedged = any(w in passage.lower() for w in ("critics argue", "claimed", "allegedly", "supposedly"))
                answers[name] = YesNoAnswer(0.8 if hedged else 0.1)
        return Verdict(answers=answers, model=self.model, input_tokens=len(str(state)) // 4, latency_ms=0)
