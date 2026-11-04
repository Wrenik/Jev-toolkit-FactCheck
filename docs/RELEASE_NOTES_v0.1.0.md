# jev-toolkit-factcheck v0.1.0

A fact checker with hover evidence. Claude (or any LLM) lists, per claim, a source URL and a verbatim quote in `claims.json`. This tool fetches the page, proves the quote is really there (with character offsets), asks a judge whether the passage supports the claim, and writes one self-contained HTML report where hovering a claim shows source, quote and the highlighted passage.

## Highlights
- Quotes are verified by plain code, not by a model: exact, normalised (quotes, dashes, case, whitespace, ligatures, hyphenation), elided with `...`, and misquotes caught (changed number, dropped "not", quote cut mid-number).
- Safe fetching: no private addresses (IPv4, IPv6, NAT64, obfuscated forms), no DNS-rebinding gap, every redirect re-checked, size caps, hidden text ignored.
- Page text is treated as hostile: injection-like passages never reach the judge.
- Works offline: `python -m jev_factcheck demo`, and `check --no-judge` needs no key.
- A contract for the LLM: JSON Schema, example, prompt and Claude skill included.

## Try it
See the README: install into a fresh venv, run `python -m jev_factcheck demo --out demo.html`, then `check` your own `claims.json`. A finished report is in `docs/example_report.html`.

## Limits (please read)
- It checks support by the cited source, not that the source is true.
- Evaluation: 50 hand-labelled claims on invented pages; not evidence of real-world accuracy. The full chain with real pages and the real judge has not been run end to end.
- PDFs, paywalled and script-rendered pages are reported as unavailable.
- The judge is TypeSafe Jev (US-hosted) for now; `--no-judge` sends nothing. Plan: a local or European model behind the same interface.

## Requirements
Python 3.11+, the sibling package `jev-toolkit-usage`. The scanner is optional.
