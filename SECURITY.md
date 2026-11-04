# Security policy

This is an experimental learning project. It fetches URLs that an LLM supplies, so the fetch code (`netguard.py`, `fetch.py`) and the HTML report (`render.py`) are the security-relevant parts. Do not rely on it as your only defence.

## Reporting a problem

* A **way around the fetch guard** (reaching a private address, a bad redirect, an oversized body), an **XSS in the report**, or a **passage that steers the judge** is welcome as a normal issue only if the example is inert: use `.invalid` hosts and canary strings, never a live payload or real secrets.
* A vulnerability that you would rather not describe publicly: use GitHub's **private vulnerability reporting** (the repository's Security tab). If that button is missing, open an issue that says only that you have a security report, without details.
* A missing redaction pattern belongs to Jev-toolkit-usage (`jev_core.redact`).

## Scope

In scope: the Python package in `src/` and the claims in the documentation. Out of scope: TypeSafe's service, Claude Code, and attackers who already control your machine. The application-level address checks are not a substitute for an egress firewall.

## Secrets

Never put your `TYPESAFE_API_KEY` in an issue, a log excerpt or a report file. `.env` and `var/` are git-ignored; by default data is kept outside any repository in `~/.jev-toolkit` (`JEV_HOME`).
