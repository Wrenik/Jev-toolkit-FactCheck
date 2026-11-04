# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/). Versions follow [SemVer](https://semver.org/).

## [0.1.0] - unreleased

First public version. Cut from the jev-toolkit monorepo and then reviewed.

### Added
- Quote matching with offsets (exact, normalised, elided, near, altered, stitched, not found).
- SSRF-safe fetcher: public addresses only, pinned connection, every redirect re-checked, size and time caps, hidden text ignored.
- Judge layer through the `Judge` interface of `jev_core` (TypeSafe Jev today), prompt-injection guard in front of it.
- Correction loop with a hard round limit, source lists, labelled evaluation sets.
- Static HTML report with hover and keyboard citations (`docs/example_report.html`).
- CLI: `demo`, `check` (`--json`, `--fixtures`, `--state`), `validate`, `schema`, `eval`, `prompt`.
- `claims.json` JSON Schema, examples, copy-paste prompt and Claude skill snippet.
- Claim-vs-quote flags (number missing from the quote, negation differs), page text SHA-256 in results.

### Fixed in the pre-release review
- `<meta charset="...">` with quotes was ignored; unlabelled legacy pages are now decoded as Windows-1252.
- NAT64 / SIIT / site-local IPv6 and `0.0.0.0/8` were treated as public.
- A quote cut in the middle of a number ("15" in "150") counted as found.
- A quote wrapped in its own quotation marks was reported as altered.
- "six" vs "eight" was only `near`, not `altered`.

### Known limits
See "Status and limits" in the README: not tested end to end against real pages and the real judge; no PDF, paywall or script-rendered page support.
