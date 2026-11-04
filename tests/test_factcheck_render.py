"""The HTML report is self-contained and escapes everything."""

import re

from jev_core import FakeJudge, PickAnswer, YesNoAnswer
from jev_factcheck.checker import check_claims
from jev_factcheck.fetch import FetchResult
from jev_factcheck.render import render_html
from jev_factcheck.schema import parse_claims

XSS = '<script>alert(1)</script><img src=x onerror=alert(2)>"\'&'
PAGE = "Water boils at 100 degrees Celsius at sea level. " + XSS + " Ice melts at 0 degrees."


class Pages:
    def fetch(self, url):
        if "ok" in url:
            return FetchResult(url, True, "ok", text=PAGE, title="T" + XSS)
        return FetchResult(url, False, "http_error", "HTTP 402")


def judge():
    def r(state, q):
        return {"relation": PickAnswer("supports", 0.9, {"supports": 0.9, "contradicts": 0.04, "unrelated": 0.03, "not_enough": 0.03}),
                "out_of_context": YesNoAnswer(0.05)}
    return FakeJudge(r)


def build(text=None):
    text = text or "Water boils at 100 C. Ice melts at 0 C. Something unsourced. " + XSS
    cf = parse_claims({"text": text, "claims": [
        {"id": "a", "claim": "Water boils at 100 C." + XSS, "url": "https://ok.test/a?x=<b>", "quote": "Water boils at 100 degrees Celsius at sea level.", "span": [0, 21]},
        {"id": "b", "claim": "Ice melts at 0 C.", "url": "https://paywall.test/", "quote": "q" * 30, "span": [22, 39]},
        {"id": "c", "claim": "No span here", "url": "https://ok.test/a", "quote": "invented sentence not on the page at all", "topic": "t"}]})
    return text, check_claims(cf, Pages(), judge())


def test_html_is_safe_and_self_contained():
    text, results = build()
    out = render_html(text, results, title="T" + XSS)
    assert "Content-Security-Policy" in out and "default-src &#x27;none&#x27;" in out
    assert "<script" not in out.lower().replace("&lt;script", "")
    assert "<img" not in out and "onerror=" not in re.sub(r"&lt;[^>]*", "", out)
    assert "&lt;script&gt;" in out
    assert not re.search(r'<[^>]*\s(src|action)\s*=', out)
    hrefs = re.findall(r'<a [^>]*href="([^"]*)"[^>]*>', out)  # only the per-claim deep links, http(s) with a text fragment
    assert hrefs and all(h.startswith("https://") and "#:~:text=" in h for h in hrefs)
    assert all('rel="noopener noreferrer nofollow"' in a for a in re.findall(r"<a [^>]*>", out))
    assert not re.search(r"url\(|@import", out)


def test_states_footnotes_and_limit_line():
    text, results = build()
    out = render_html(text, results)
    for s in ("s-supported", "s-source_unavailable"):
        assert s in out
    assert "not that the source is true" in out
    assert out.count('class="fn"') == 2  # claim c has no span: footnote list only
    assert 'id="c3"' in out and "Evidence for each claim" in out
    assert "P(supports) 90%" in out


def test_highlight_offsets_in_output():
    text, results = build()
    out = render_html(text, results)
    assert "<mark>Water boils at 100 degrees Celsius at sea level.</mark>" in out
    assert "characters 0–48 of the extracted page text" in out


def test_text_without_claims_and_empty_results():
    out = render_html("Just <b>text</b>", [])
    assert "Just &lt;b&gt;text&lt;/b&gt;" in out
