"""Static HTML report: the answer text with each claim marked; hover/focus shows the evidence.

Safety: one self-contained file, no scripts, no remote resources, strict CSP meta, every piece of
text passes through html.escape, the source URL is shown as text; the only link is the per-claim "open at the quote" deep link (http/https, noopener, no referrer). Works without hover: claims
carry footnote numbers and every claim's evidence is also listed under the text (and in print).
"""

from __future__ import annotations

from html import escape
from typing import Any

from .verdict import ClaimResult

CSP = "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"
CONTEXT = 140
LABELS = {
    "supported": ("✓", "Supported by the source"),
    "not_supported": ("≠", "Not supported by the source"),
    "quote_not_found": ("✗", "Quote not found in the source"),
    "source_unavailable": ("∅", "Source unavailable"),
    "quote_only": ("~", "Quote found, support not judged"),
}

CSS = """
:root{--bg:#fff;--fg:#1c1c1e;--mut:#5b5b63;--card:#f4f4f6;--bd:#c9c9d0;--ok:#146c2e;--warn:#8a5a00;--bad:#b3261e;--na:#555a66;--q:#33507a;--mark:#ffe58a}
@media (prefers-color-scheme:dark){:root{--bg:#16161a;--fg:#ececf0;--mut:#a3a3ad;--card:#222228;--bd:#3d3d47;--ok:#6fd58d;--warn:#f0b64a;--bad:#ff8a80;--na:#a5abb8;--q:#9bb8e8;--mark:#6b5a10}}
*{box-sizing:border-box}body{margin:0 auto;max-width:46rem;padding:1rem 16px 4rem;background:var(--bg);color:var(--fg);font:16px/1.6 system-ui,sans-serif}
h1{font-size:1.3rem;margin:.2rem 0}h2{font-size:1.05rem;margin:2rem 0 .5rem}
.limit{color:var(--mut);border-left:3px solid var(--bd);padding:.2rem .7rem;margin:.6rem 0}
.sum{display:flex;flex-wrap:wrap;gap:.4rem;margin:.8rem 0;padding:0;list-style:none}
.sum li{background:var(--card);border:1px solid var(--bd);border-radius:6px;padding:.15rem .6rem;font-size:.9rem}
.answer{white-space:pre-wrap;overflow-wrap:anywhere}
.claim{position:relative;border-bottom:2px solid;cursor:help;outline-offset:2px}
.s-supported{color:inherit;border-color:var(--ok)}
.s-not_supported{border-color:var(--warn);border-bottom-style:double;border-bottom-width:4px}
.s-quote_not_found{border-color:var(--bad);border-bottom-style:wavy;border-bottom-width:2px;text-decoration:none}
.s-source_unavailable{border-color:var(--na);border-bottom-style:dotted}
.s-quote_only{border-color:var(--q);border-bottom-style:dashed}
.fn{font-size:.7rem;font-weight:700;vertical-align:super;margin-left:1px;color:var(--mut)}
.tip{display:none;position:absolute;z-index:5;left:0;top:100%;width:min(34rem,86vw);background:var(--card);color:var(--fg);border:1px solid var(--bd);border-radius:8px;padding:.6rem .8rem;font-size:.85rem;line-height:1.45;white-space:normal;box-shadow:0 4px 18px rgba(0,0,0,.25)}
.claim:hover>.tip,.claim:focus>.tip,.claim:focus-within>.tip{display:block}
.ev{background:var(--card);border:1px solid var(--bd);border-radius:8px;padding:.6rem .9rem;margin:.7rem 0;break-inside:avoid}
.ev h3{font-size:.95rem;margin:.1rem 0 .3rem}.tag{font-weight:700}
.t-supported{color:var(--ok)}.t-not_supported{color:var(--warn)}.t-quote_not_found{color:var(--bad)}.t-source_unavailable{color:var(--na)}.t-quote_only{color:var(--q)}
.kv{color:var(--mut);font-size:.85rem;overflow-wrap:anywhere}.kv b{color:var(--fg)}
blockquote{margin:.4rem 0;padding:.2rem .7rem;border-left:3px solid var(--bd);overflow-wrap:anywhere}
mark{background:var(--mark);color:inherit;padding:0 1px}.ctx{color:var(--mut)}
code{font-size:.85em;overflow-wrap:anywhere}
@media print{.tip{display:none!important}.claim{cursor:auto}body{max-width:none}}
"""


def _passage_html(res: ClaimResult) -> str:
    m, text = res.match, res.source_text
    if not m or m.start is None or not text:
        return ""
    segs = sorted(m.segments) or [(m.start, m.end)]
    out: list[str] = []
    pos = max(0, segs[0][0] - CONTEXT)
    out.append('<span class="ctx">' + ("…" if pos > 0 else "") + escape(text[pos : segs[0][0]]) + "</span>")
    for i, (s, e) in enumerate(segs):
        if i:
            out.append('<span class="ctx"> … </span>')
        out.append("<mark>" + escape(text[s:e]) + "</mark>")
    tail_end = min(len(text), segs[-1][1] + CONTEXT)
    out.append('<span class="ctx">' + escape(text[segs[-1][1] : tail_end]) + ("…" if tail_end < len(text) else "") + "</span>")
    return "".join(out)


def _offsets(res: ClaimResult) -> str:
    m = res.match
    if not m or m.start is None:
        return ""
    parts = ", ".join(f"{s}–{e}" for s, e in (m.segments or [(m.start, m.end)]))
    return f"characters {parts} of the extracted page text"


def _detail(res: ClaimResult, n: int, compact: bool) -> str:
    glyph, label = LABELS[res.state]
    h: list[str] = []
    title = f"[{n}] {glyph} {label}"
    j = res.judge
    if j and j.ran and j.p_support is not None:
        title += f" · P(supports) {j.p_support:.0%}"
    h.append(f'<div class="tag t-{res.state}">{escape(title)}</div>')
    h.append(f"<div>{escape(res.explanation)}</div>")
    h.append(f'<div class="kv"><b>Claim:</b> {escape(res.claim.claim)}</div>')
    h.append(f'<div class="kv"><b>Source:</b> <code>{escape(res.claim.url)}</code></div>')
    link = res.deep_link
    if link and not compact:
        h.append(f'<div class="kv"><a href="{escape(link, quote=True)}" target="_blank" rel="noopener noreferrer nofollow">'
                 "Open the source at the quote</a> (browsers with text-fragment support scroll to and highlight it; others just open the page)</div>")
    if res.fetch.get("title"):
        h.append(f'<div class="kv"><b>Page title:</b> {escape(str(res.fetch["title"]))}</div>')
    if not compact:
        h.append(f'<div class="kv"><b>Quote given:</b></div><blockquote>{escape(res.claim.quote)}</blockquote>')
    m = res.match
    if m and m.start is not None:
        h.append(f'<div class="kv"><b>Match:</b> {escape(m.status)}'
                 + (f", similarity {m.similarity:.2f}" if m.similarity is not None and m.similarity < 1 else "")
                 + f", {escape(_offsets(res))}"
                 + (f", {m.occurrences} occurrences" if m.occurrences > 1 else "") + "</div>")
        if not compact:
            h.append("<blockquote>" + _passage_html(res) + "</blockquote>")
        for d in m.differences[:4]:
            h.append(f'<div class="kv"><b>Differs:</b> quote “{escape(d["quote"])}” vs source “{escape(d["source"])}”</div>')
    elif m:
        h.append(f'<div class="kv"><b>Match:</b> {escape(m.status)} – {escape(m.note)}</div>')
    if res.flags:
        h.append(f'<div class="kv"><b>Check this:</b> {escape("; ".join(res.flags))} (a prompt to look, not a verdict)</div>')
    if res.fetch.get("text_sha256"):
        h.append(f'<div class="kv">Page text sha256 {escape(str(res.fetch["text_sha256"])[:16])}…, fetched from {escape(str(res.fetch.get("final_url") or res.claim.url))}</div>')
    if m and m.flags:
        h.append(f'<div class="kv"><b>Quote flags:</b> {escape(", ".join(m.flags))}</div>')
    if j and j.ran and not compact:
        probs = ", ".join(f"{k} {v:.0%}" for k, v in sorted(j.probabilities.items(), key=lambda kv: -kv[1]))
        h.append(f'<div class="kv"><b>Judge ({escape(j.model)}):</b> {escape(probs)}; out of context {j.p_out_of_context:.0%}</div>')
    if j and j.injection_reason:
        h.append(f'<div class="kv"><b>Not judged:</b> passage looked like an injection ({escape(j.injection_reason)})</div>')
    if res.source_flags:
        h.append(f'<div class="kv"><b>Source flags:</b> {escape(", ".join(res.source_flags))} (a flag to look at, not a verdict) {escape(res.source_note)}</div>')
    if res.fetch.get("dropped_hidden_chars"):
        h.append(f'<div class="kv">{res.fetch["dropped_hidden_chars"]} characters of hidden text on the page were ignored.</div>')
    return "".join(h)


def render_html(text: str, results: list[ClaimResult], *, title: str = "Fact check", rounds: list[dict[str, Any]] | None = None,
                judge_note: str = "") -> str:
    numbered = {r.claim.id: i + 1 for i, r in enumerate(results)}
    spans = sorted((r for r in results if r.claim.span), key=lambda r: r.claim.span)
    body: list[str] = []
    pos = 0
    for r in spans:
        s, e = r.claim.span
        if s < pos:
            continue
        body.append(escape(text[pos:s]))
        n = numbered[r.claim.id]
        body.append(
            f'<span class="claim s-{r.state}" tabindex="0">{escape(text[s:e])}<span class="fn">[{n}]</span>'
            f'<span class="tip" role="tooltip">{_detail(r, n, compact=True)}</span></span>'
        )
        pos = e
    body.append(escape(text[pos:]))
    counts: dict[str, int] = {}
    for r in results:
        counts[r.state] = counts.get(r.state, 0) + 1
    summary = "".join(
        f"<li>{LABELS[s][0]} {counts[s]} {escape(LABELS[s][1].lower())}</li>" for s in LABELS if counts.get(s)
    )
    notes = [
        "This page checks support <b>by the cited source</b>, not that the source is true. It does not replace your own judgement.",
        judge_note or "Support is a judge probability, not a proof.",
    ]
    evidence = "".join(f'<div class="ev" id="c{n}">{_detail(r, n, compact=False)}</div>' for n, r in
                       ((numbered[r.claim.id], r) for r in results))
    rounds_html = ""
    if rounds:
        rows = "".join(
            f'<li>Round {escape(str(x.get("round")))}: {escape(str(x.get("summary", "")))}</li>' for x in rounds
        )
        rounds_html = f"<h2>Correction rounds</h2><ul class=\"kv\">{rows}</ul>"
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        f'<meta http-equiv="Content-Security-Policy" content="{escape(CSP)}">'
        '<meta name="referrer" content="no-referrer">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{escape(title)}</title><style>{CSS}</style></head><body>"
        f"<h1>{escape(title)}</h1>"
        + "".join(f'<p class="limit">{n}</p>' for n in notes)
        + f'<ul class="sum">{summary}</ul>'
        + f'<div class="answer">{"".join(body)}</div>'
        + "<h2>Evidence for each claim</h2>" + evidence + rounds_html
        + "</body></html>"
    )
