"""Round 2: findings from running the chain on real pages (IPv6 dead ends, footnote markers, boilerplate),
text-fragment deep links, optional PDF input, and the large-page cap. No network."""

import time
from urllib.parse import unquote

from jev_factcheck import fragment, match, pdftext
from jev_factcheck.fetch import Fetcher, _dial_order
from jev_factcheck.htmltext import extract_text
from jev_factcheck.match import match_quote
from test_factcheck_fetch import H, PUB, FakeResp, Net


# ---- text fragments ---------------------------------------------------------------------------
def test_fragment_short_quote_is_whole_and_encodes_delimiters():
    text = "Intro. Cost-effective, fast & cheap. Outro."
    s = text.index("Cost")
    f = fragment.text_fragment(text, [(s, s + len("Cost-effective, fast & cheap."))])
    assert f == "text=Cost%2Deffective%2C%20fast%20%26%20cheap."
    assert unquote(f[5:]) == "Cost-effective, fast & cheap."


def test_fragment_long_quote_uses_range_form_and_never_crosses_lines():
    words = " ".join(f"w{i}" for i in range(40))
    text = f"pre\n{words}\nsecond line here ends now\npost"
    s = text.index("w0")
    e = text.index("now") + 3
    start, end = fragment.text_fragment(text, [(s, e)])[5:].split(",")
    assert unquote(start) == "w0 w1 w2 w3 w4"
    assert unquote(end) == "line here ends now" or unquote(end).endswith("ends now")
    assert "\n" not in unquote(start) + unquote(end)


def test_fragment_prefix_when_quote_repeats_and_existing_anchor_replaced():
    text = "alpha beta gamma delta. Also: the same words appear. Later: the same words appear."
    s = text.rindex("the same")
    link = fragment.deep_link("https://x.test/p?a=1#old", text, [(s, s + 14)], occurrences=2)
    assert link.startswith("https://x.test/p?a=1#:~:text=") and "#old" not in link
    assert unquote(link).split("text=")[1] == "words appear. Later:-,the same words"


def test_fragment_refuses_non_http_and_missing_offsets():
    assert fragment.deep_link("javascript:alert(1)", "abc def", [(0, 3)]) == ""
    assert fragment.deep_link("https://x.test/", "abc", []) == ""
    assert fragment.deep_link("https://x.test/", "abc", [(5, 9)]) == ""


# ---- reference markers, boilerplate -----------------------------------------------------------
def test_quote_without_footnote_markers_matches_source_with_them():
    src = "The tower is 330 metres (1,083 ft) tall,[9] about the same height as an 81-storey building.[a] Next."
    r = match_quote(src, "330 metres (1,083 ft) tall, about the same height as an 81-storey building.")
    assert r.status == "normalised" and "reference_markers_ignored" in r.flags
    assert match_quote(src, "tall,[9] about the same height").status == "exact"


def test_markers_never_make_a_different_index_match():
    assert match_quote("value a[1] and more text here", "value a[2] and more text here").found is False


def test_nav_and_footer_dropped_but_aside_and_article_kept():
    html = ("<body><nav>Main menu Random article</nav><main><p>Real article text.</p><aside>Side note kept.</aside></main>"
            '<div role="contentinfo">Privacy policy</div><footer>Copyright</footer></body>')
    p = extract_text(html)
    assert "Real article text." in p.text and "Side note kept." in p.text
    assert "Main menu" not in p.text and "Privacy" not in p.text and "Copyright" not in p.text
    assert p.boilerplate_chars > 0 and p.dropped_chars == 0


# ---- dialing ----------------------------------------------------------------------------------
def test_dial_order_puts_ipv4_first_and_alternates():
    assert _dial_order(["2001:db8::1", "2001:db8::2", "1.1.1.1", "2.2.2.2"]) == ["1.1.1.1", "2001:db8::1", "2.2.2.2", "2001:db8::2"]


def test_dead_ipv6_does_not_block_the_working_ipv4():
    tried = []

    def transport(target, ip, timeout):
        tried.append(ip)
        if ":" in ip:
            raise TimeoutError()
        return FakeResp(headers=H, body=b"<p>hello there world</p>")

    f = Fetcher(transport=transport, resolver=lambda h, p: ["2606:4700::1", "2606:4700::2", "104.20.23.154"], per_host_delay=0)
    assert f.fetch("http://a.test/").ok and tried == ["104.20.23.154"]


# ---- large page cap ---------------------------------------------------------------------------
def test_similar_passage_search_is_skipped_on_huge_pages_but_exact_still_works(monkeypatch):
    monkeypatch.setattr(match, "NEAR_MAX_CHARS", 1000)
    big = "The committee met on Tuesday and reviewed the budget in some detail. " * 40
    assert match_quote(big, "The committee met on Tuesday and reviewed the budget in some detail.").status == "exact"
    r = match_quote(big, "The committee met on Tuesday and reviewed the budget in 5 years in some detail.")
    assert r.status == "not_found" and "near_search_skipped" in r.flags


def test_worst_case_repetitive_large_page_is_fast():
    doc = "The committee met on Tuesday and reviewed the budget for the coming year in some detail. " * 20000
    t = time.perf_counter()
    r = match_quote(doc, "The committee decided on Tuesday to cancel the entire budget for the coming year immediately.")
    assert r.status == "not_found" and time.perf_counter() - t < 8  # about 1 s here; generous for slow CI


# ---- PDF --------------------------------------------------------------------------------------
def _tiny_pdf(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    x = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for o in offs:
        out += b"%010d 00000 n \n" % o
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n" % (len(objs) + 1, x) + b"%%EOF"
    return bytes(out)


PDF = {"Content-Type": "application/pdf"}


def test_pdf_text_is_extracted_when_pypdf_is_present():
    if not pdftext.available():
        return
    f = Fetcher(transport=Net({"http://a.test/d.pdf": FakeResp(headers=PDF, body=_tiny_pdf("The dose is 5 mg daily"))}),
                resolver=PUB, per_host_delay=0)
    r = f.fetch("http://a.test/d.pdf")
    assert r.ok and "The dose is 5 mg daily" in r.text
    assert match_quote(r.text, "The dose is 5 mg daily").status == "exact"


def test_garbage_pdf_is_a_clear_failure_not_a_crash():
    if not pdftext.available():
        return
    f = Fetcher(transport=Net({"http://a.test/d.pdf": FakeResp(headers=PDF, body=b"%PDF-1.7 junk")}), resolver=PUB, per_host_delay=0)
    r = f.fetch("http://a.test/d.pdf")
    assert not r.ok and r.status == "unsupported_type" and "PDF not read" in r.detail


def test_newlines_inside_html_text_are_spaces_but_pre_and_br_keep_lines():
    p = extract_text("<p>a current\nselected\n   representation</p><pre>l1\nl2</pre><p>x<br>y</p>")
    assert "a current selected representation" in p.text and "l1\nl2" in p.text and "x\ny" in p.text
