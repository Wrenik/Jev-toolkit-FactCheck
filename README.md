# Jev-toolkit-FactCheck

[![tests](https://github.com/Wrenik/Jev-toolkit-FactCheck/actions/workflows/tests.yml/badge.svg)](https://github.com/Wrenik/Jev-toolkit-FactCheck/actions/workflows/tests.yml)
![python](https://img.shields.io/badge/python-3.11%2B-blue)
![status](https://img.shields.io/badge/status-alpha-orange)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

(The badges start working once the repository is public.)

A fact checker with **hover evidence**. The LLM lists, per claim, a source URL and a **verbatim quote**; plain code checks that the quote really exists in the fetched page (exact and normalised matching, with character offsets); a judgement model ([TypeSafe Jev](https://docs.typesafe.ai)) rates whether the quoted passage supports the claim (with a probability); unusual source domains are flagged against your own per-topic lists; failures go back to the LLM for correction under a hard round limit that also stops when the source simply lacks the information. The output is one static HTML page: hover (or focus) a claim to see source, URL, quote and the matched passage highlighted with offsets.

## Status and limits

* It checks **support by the cited source**, not that the source is true, and it does not replace your own judgement.
* The numbers in [docs/FACT_CHECKER.md](docs/FACT_CHECKER.md) come from 50 hand-labelled claims on **invented** pages (30 dev, 20 held-out). That set is friendly: Jev agreeing on 50/50 UI states is **not evidence of real-world accuracy**. Nine extra, untuned judge-only pairs were agreed on 7/9.
* Paywalled pages, script-rendered pages and PDFs are not read (reported as "source unavailable"); paraphrase never counts as a quote (by design).
* The chain Claude, `claims.json`, real web pages, Jev has not been run end to end in a real session; only fixtures and a fake network transport were tested.

## Install

Want all six tools? Use [the install script](https://github.com/Wrenik/Jev-toolkit-usage/blob/main/docs/INSTALL_ALL.md) (`scripts/install_all.ps1` or `.sh` in Jev-toolkit-usage) instead of the steps below.

Requires Python 3.11+ and git. Until the repositories are public, install the sibling from a local clone (both repos side by side, e.g. `~/jev/Jev-toolkit-usage` and `~/jev/Jev-toolkit-FactCheck`). Create the environment somewhere else than inside the repos:

```bash
python -m venv ~/jev-venv
source ~/jev-venv/bin/activate              # Windows PowerShell: ~\jev-venv\Scripts\Activate.ps1
cd ~/jev/Jev-toolkit-FactCheck
python -m pip install -e ../Jev-toolkit-usage
python -m pip install -e . --no-deps        # for the tests also: python -m pip install pytest
# optional: the injection scanner adds its offline layers to the passage check
python -m pip install -e ../Jev-toolkit-Scanner --no-deps
```

Optional PDF input: `python -m pip install pypdf` (or the `[pdf]` extra).

Once public: `pip install "jev-toolkit-factcheck @ git+https://github.com/Wrenik/Jev-toolkit-FactCheck.git"` (with the scanner: `pip install "jev-toolkit-factcheck[scanner] @ git+..."`). Data (logs, cache, report defaults) lives in `JEV_HOME` (default `~/.jev-toolkit`); a `.env` with `TYPESAFE_API_KEY` there is only needed for the real judge. The scanner is **optional**: without it the built-in rules in `jev_factcheck.guard` are used on their own.

## Quick try (offline, no key)

```bash
python -m jev_factcheck demo --out demo.html   # invented pages, word-overlap stand-in judge (not Jev)
python -m jev_factcheck eval                   # the labelled sets with the stand-in judge (a baseline)
python -m jev_factcheck prompt                 # the instructions to paste into Claude
```

Open `demo.html` and hover (or Tab to) the underlined claims. A ready-made report is committed at [docs/example_report.html](docs/example_report.html) (download it and open it in a browser; it is a single file, no scripts).

## Check your own claims.json

1. Ask Claude to produce one. Paste the text from [docs/CLAUDE_PROMPT.md](docs/CLAUDE_PROMPT.md) (or `python -m jev_factcheck prompt`), or install [docs/claude-skill/SKILL.md](docs/claude-skill/SKILL.md) as a Claude Code skill. Claude needs web access, because it must open the pages and copy the quotes.
2. The file format ([JSON Schema](src/jev_factcheck/data/claims.schema.json), `python -m jev_factcheck schema`; example: [docs/claims.example.json](docs/claims.example.json)):

   ```json
   {"text": "The answer text.",
    "claims": [{"id": "c1", "claim": "One factual sentence, copied from text.",
                "url": "https://example.org/page", "quote": "Copied VERBATIM from that page ... pieces joined by ...",
                "topic": "general"}]}
   ```

   `id`, `topic` and `span` are optional. Limits: 200 claims, 600 characters per claim, 1500 per quote.
3. `python -m jev_factcheck validate claims.json` checks the shape without touching the network.
4. `python -m jev_factcheck check claims.json --out report.html --no-judge` fetches the cited pages and checks that each quote exists (nothing is sent to any judge). Leave out `--no-judge` once `TYPESAFE_API_KEY` is set up; add `--json results.json` for a machine-readable copy with offsets and probabilities. Add `--state state.json` to get `corrections.json` and the 3-round correction loop.
5. No network handy? `python -m jev_factcheck check examples/claims.json --fixtures examples/fixtures --no-judge` runs the same on a local page; claim c2 has a planted wrong number, which the check catches.

The exit code is 0 only when every claim is supported (or quote-only), 1 otherwise, 2 for a malformed input.

## What the report tells you

Five states per claim: supported (quote found and the judge rates it as supporting, with a probability), not supported, quote not found (fabricated, paraphrased, a changed number or a dropped "not", or the quote stops in the middle of a number), source unavailable (blocked, paywall, PDF, script-rendered, network), and quote only (found, support not judged). Extra "check this" notes appear when the claim has a number the quote lacks, or a negation that differs. They are prompts to look, not verdicts.

## Layout

* `examples/`: a claims file plus a local page for the offline `check` run. `docs/`: example report, prompt, skill, claims examples.
* `src/jev_factcheck/`: `match.py` (quote matching), `fetch.py` + `netguard.py` + `htmltext.py` (safe fetching), `judging.py` + `guard.py` (what the judge sees), `verdict.py`, `checker.py`, `loop.py` (correction rounds), `sources.py` (per-topic lists), `render.py` (HTML), `evaluate.py` + `evalset/` (labelled sets).
* [docs/FACT_CHECKER.md](docs/FACT_CHECKER.md): design, evaluation with failures, limits, **prior art**.

## Privacy

With the judge on, per claim whose quote was found, the claim, the quote and a short window (about 300 characters each side) of the matched passage go to **TypeSafe's Jev**, a US-hosted service whose data-processing location is not verified, after secret redaction (best effort). Nothing else is sent: not the rest of the page, not the answer, not the URL. `--no-judge` sends nothing anywhere. **Jev is used because, as of today, it is the only model of its kind on the market, not because sending data to a US company is the goal. The plan is to replace it with a local model or a European provider** through the `Judge` interface in `jev_core`; this package never imports the TypeSafe SDK. The tool also contacts the websites you cite, from your machine.

## Prior art

See "Prior art" in [docs/FACT_CHECKER.md](docs/FACT_CHECKER.md) (AIS, ALCE, AttributionBench, FActScore, SAFE, CiteEval, citefact, RARR and others, and what differs here).

## The Jev toolkit family

| Repository | What it is | Depends on |
|---|---|---|
| [Jev-toolkit-usage](https://github.com/Wrenik/Jev-toolkit-usage) | `jev_core` (judge interface, Jev adapter, cache, decision log, redaction, settings and data location) and the model/effort router | - |
| [Jev-toolkit-Compiler](https://github.com/Wrenik/Jev-toolkit-Compiler) | context log, search and a compact/clear advisor | usage |
| [Jev-toolkit-Scanner](https://github.com/Wrenik/Jev-toolkit-Scanner) | prompt-injection scanner (experimental) | usage |
| [Jev-toolkit-Monitor](https://github.com/Wrenik/Jev-toolkit-Monitor) | agent monitor (experimental) | usage |
| **Jev-toolkit-FactCheck** (this one) | fact checker with hover evidence | usage (Scanner optional) |
| [Jev-toolkit-Sources](https://github.com/Wrenik/Jev-toolkit-Sources) | source restriction (allowlist policy) | usage, FactCheck |

All six on one machine: [docs/INSTALL_ALL.md](https://github.com/Wrenik/Jev-toolkit-usage/blob/main/docs/INSTALL_ALL.md) (a script does it). The links work once the repositories are public.

## Contributing, security, license

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md). Issues with inert examples are welcome.

Licensed under the [MIT License](LICENSE).
