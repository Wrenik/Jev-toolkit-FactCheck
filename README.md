# Jev-toolkit-FactCheck

A fact checker with **hover evidence**. The LLM lists, per claim, a source URL and a **verbatim quote**; plain code checks that the quote really exists in the fetched page (exact and normalised matching, with character offsets); a judgement model ([TypeSafe Jev](https://docs.typesafe.ai)) rates whether the quoted passage supports the claim (with a probability); unusual source domains are flagged against your own per-topic lists; failures go back to the LLM for correction under a hard round limit that also stops when the source simply lacks the information. The output is one static HTML page: hover (or focus) a claim to see source, URL, quote and the matched passage highlighted with offsets.

Part of the Jev tool family; the shared judge layer lives in [Jev-toolkit-usage](https://github.com/Wrenik/Jev-toolkit-usage). Siblings: [Compiler](https://github.com/Wrenik/Jev-toolkit-Compiler), [Scanner](https://github.com/Wrenik/Jev-toolkit-Scanner), [Monitor](https://github.com/Wrenik/Jev-toolkit-Monitor) and [Sources](https://github.com/Wrenik/Jev-toolkit-Sources) (source restriction, built on this one). (Links work once the repositories are public.)

## Status and limits: read this first

* It checks **support by the cited source**, not that the source is true, and it does not replace your own judgement.
* The numbers in [docs/FACT_CHECKER.md](docs/FACT_CHECKER.md) come from 50 hand-labelled claims on **invented** pages (30 dev, 20 held-out). That set is friendly: Jev agreeing on 50/50 UI states is **not evidence of real-world accuracy**. Nine extra, untuned judge-only pairs were agreed on 7/9.
* Paywalled pages, script-rendered pages and PDFs are not read (reported as "source unavailable"); paraphrase never counts as a quote (by design).
* The chain Claude, `claims.json`, real web pages, Jev has not been run end to end in a real session; only fixtures and a fake network transport were tested.

## Privacy

With the judge on, per claim whose quote was found, the claim, the quote and a short window (about 300 characters each side) of the matched passage go to **TypeSafe's Jev**, a US-hosted service whose data-processing location is not verified, after secret redaction (best effort). Nothing else is sent: not the rest of the page, not the answer, not the URL. `--no-judge` sends nothing anywhere. Jev is used because it is the only typed-answer judgement model on the market today; **the plan is to replace it with a local or European model** behind the `Judge` interface in `jev_core`; this package never imports the TypeSafe SDK. The tool also contacts the websites you cite, from your machine.

## Install

Requires Python 3.11+. Until the repositories are public, install the sibling from a local clone:

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ../Jev-toolkit-usage       # Windows; use .venv/bin/python elsewhere
.venv/Scripts/python -m pip install -e ".[dev]" --no-deps
# optional: the injection scanner adds its offline layers to the passage check
.venv/Scripts/python -m pip install -e ../Jev-toolkit-Scanner --no-deps
```

Once public: `pip install "jev-toolkit-factcheck @ git+https://github.com/Wrenik/Jev-toolkit-FactCheck.git"` (with the scanner: `pip install "jev-toolkit-factcheck[scanner] @ git+..."`). Data (logs, cache, report defaults) lives in `JEV_HOME` (default `~/.jev-toolkit`); a `.env` with `TYPESAFE_API_KEY` there is only needed for the real judge. The scanner is **optional**: without it the built-in rules in `jev_factcheck.guard` are used on their own.

## Try it in 60 seconds (offline, no key)

```bash
python -m jev_factcheck demo                 # invented pages, word-overlap stand-in judge (not Jev)
python -m jev_factcheck eval                 # the labelled sets with the stand-in judge (a baseline)
python -m jev_factcheck prompt               # the instructions to paste into Claude Code
```

The demo writes its report under `JEV_HOME/var/` (the path is printed); open it and hover the underlined claims.

## Layout

* `src/jev_factcheck/`: `match.py` (quote matching), `fetch.py` + `netguard.py` + `htmltext.py` (safe fetching), `judging.py` + `guard.py` (what the judge sees), `verdict.py`, `checker.py`, `loop.py` (correction rounds), `sources.py` (per-topic lists), `render.py` (HTML), `evaluate.py` + `evalset/` (labelled sets).
* [docs/FACT_CHECKER.md](docs/FACT_CHECKER.md): design, evaluation with failures, limits, **prior art**.

## Prior art

See "Prior art" in [docs/FACT_CHECKER.md](docs/FACT_CHECKER.md) (AIS, ALCE, AttributionBench, FActScore, SAFE, CiteEval, citefact, RARR and others, and what differs here).

## Contributing and feedback

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md). Issues with inert examples are welcome.

## License

MIT, see [LICENSE](LICENSE).
