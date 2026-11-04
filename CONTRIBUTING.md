# Contributing

Thanks for looking. This is a small learning project, so the bar is "clear and honest", not "enterprise".

1. `python -m venv .venv`, install with `.venv/Scripts/python -m pip install -e ../Jev-toolkit-usage` and then `-e ".[dev]"` (use `.venv/bin/python` on Linux/macOS).
2. Run the tests: `python -m pytest`. They are offline, need no API key and no network (`JEV_JUDGE=fake` is set in CI). Tests marked `live` call the real Jev API and are skipped by default.
3. New behaviour comes with a test. A bug fix comes with a regression test that fails without the fix.
4. Keep documentation claims measured: say what was tested, on how many cases, and what the limits are.
5. Never use the Jev SDK directly (it lives in Jev-toolkit-usage, `jev_core`); this tool talks to the `Judge` interface so the judge can be replaced by a local or European model.
6. Evaluation: add new claims to a **new** held-out set and never tune the matcher or the verdict rules on a set you report on. The frozen `heldout.json` was run once; if you change rules because of it, say so and make a fresh set.

Good first contributions: a quote the matcher gets wrong (with an inert example), a page-extraction case (tables, footnotes) with a fixture, a clearer HTML report.
