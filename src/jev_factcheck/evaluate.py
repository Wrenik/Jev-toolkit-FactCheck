"""Evaluation against hand-labelled claims on local fixture pages. Offline unless --live.

Reports, per set and per layer, counts (never only percentages) and lists every failure:
  1. quote layer: does `found` agree with the label `quote_exists`?  (deterministic, no judge)
  2. judge layer: on claims whose quote exists, does the relation agree with the label `support`?
  3. end to end: does the UI state agree with the label `state`?
With the default demo judge (word overlap) this is a BASELINE. With --live it is Jev.
"""

from __future__ import annotations

import json
from collections import Counter
from importlib import resources
from pathlib import Path

from .checker import check_claims
from .fetch import FixtureFetcher
from .judging import default_injection_check
from .schema import parse_claims

PAGES = Path(str(resources.files("jev_factcheck") / "evalset" / "pages"))
SETS = {"dev": "dev.json", "heldout": "heldout.json"}


def load_set(name: str) -> list[dict]:
    path = Path(str(resources.files("jev_factcheck") / "evalset" / SETS[name]))
    return json.loads(path.read_text(encoding="utf-8"))["claims"]


def run_set(name: str, judge) -> dict:
    labelled = load_set(name)
    cf = parse_claims({"text": "", "claims": [{k: c[k] for k in ("id", "claim", "url", "quote")} for c in labelled]})
    results = check_claims(cf, FixtureFetcher(PAGES), judge, injection_check=default_injection_check())
    rows = []
    for lab, res in zip(labelled, results):
        found = bool(res.match and res.match.found)
        rows.append(
            {
                "id": lab["id"],
                "category": lab["category"],
                "label_state": lab["state"],
                "state": res.state,
                "label_quote": lab["quote_exists"],
                "found": found,
                "match": res.match.status if res.match else None,
                "label_support": lab["support"],
                "relation": res.judge.relation if res.judge and res.judge.ran else None,
                "reason": res.reason,
            }
        )
    return {"set": name, "rows": rows}


def score(run: dict) -> dict:
    rows = run["rows"]
    reachable = [r for r in rows if r["label_state"] != "source_unavailable"]
    quote_ok = [r for r in reachable if r["found"] == r["label_quote"]]
    judged = [r for r in rows if r["label_quote"] and r["found"] and r["relation"] is not None and r["label_support"]]
    judge_ok = [r for r in judged if r["relation"] == r["label_support"]]
    e2e_ok = [r for r in rows if r["state"] == r["label_state"]]
    return {
        "n": len(rows),
        "quote_layer": (len(quote_ok), len(reachable)),
        "judge_layer": (len(judge_ok), len(judged)),
        "end_to_end": (len(e2e_ok), len(rows)),
        "by_category": {
            c: (
                sum(1 for r in rows if r["category"] == c and r["state"] == r["label_state"]),
                sum(1 for r in rows if r["category"] == c),
            )
            for c in sorted({r["category"] for r in rows})
        },
        "confusion": dict(Counter((r["label_support"], r["relation"]) for r in judged)),
        "failures": [r for r in rows if r["state"] != r["label_state"]],
    }


def format_report(run: dict, judge_name: str) -> str:
    s = score(run)

    def f(t):
        return f"{t[0]}/{t[1]}" + (f" ({t[0] / t[1]:.0%})" if t[1] else "")

    lines = [
        f"set={run['set']}  judge={judge_name}  claims={s['n']}",
        f"  quote layer (found vs label, readable sources only): {f(s['quote_layer'])}",
        f"  judge layer (relation vs label, quote found):        {f(s['judge_layer'])}",
        f"  end to end (UI state vs label):                      {f(s['end_to_end'])}",
        "  by category (end to end):",
    ]
    lines += [f"    {c:<32} {f(v)}" for c, v in s["by_category"].items()]
    lines.append("  failures (label -> got):")
    for r in s["failures"]:
        lines.append(
            f"    {r['id']} [{r['category']}] {r['label_state']} -> {r['state']} ({r['reason']}, match={r['match']}, relation={r['relation']})"
        )
    if not s["failures"]:
        lines.append("    none")
    return "\n".join(lines)


def run_tricky(judge) -> str:
    """Judge-only inline pairs (evalset/tricky.json). Prints expected vs got with probabilities; not tuned on."""
    from .judging import judge_support
    from .match import match_quote

    path = Path(str(resources.files("jev_factcheck") / "evalset" / "tricky.json"))
    pairs = json.loads(path.read_text(encoding="utf-8"))["pairs"]
    lines, ok = [], 0
    for p in pairs:
        m = match_quote(p["passage"], p["quote"])
        out = judge_support(judge, p["claim"], p["quote"], p["passage"], m, None)
        if not out.ran:
            lines.append(f"  {p['id']} judge did not run: {out.error or out.injection_reason}")
            continue
        hit = out.relation == p["expected_relation"]
        ooc_exp = p["expected_out_of_context"]
        ooc_ok = ooc_exp is None or ((out.p_out_of_context or 0.0) >= 0.5) == ooc_exp
        ok += hit
        probs = ", ".join(f"{k} {v:.0%}" for k, v in sorted(out.probabilities.items(), key=lambda kv: -kv[1])[:2])
        lines.append(
            f"  {p['id']} expected {p['expected_relation']:<11} got {out.relation:<11} ({probs}); out_of_context {out.p_out_of_context:.0%}"
            f" [{'ok' if hit else 'DIFFERS'}{'' if ooc_ok else ', context flag DIFFERS'}]"
        )
    return f"tricky pairs: relation agrees on {ok}/{len(pairs)}\n" + "\n".join(lines)
