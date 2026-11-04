"""Quote matching: exact, normalised, elided, near, altered, stitched, not found. Offsets map to the original."""

import pytest

from jev_factcheck.match import match_quote, normalise
from jev_factcheck.schema import SchemaError, parse_claims

DOC = (
    "The city council met on Tuesday.  It voted 7-2 to approve the budget.\n"
    "The mayor said the tax rate will not rise in 2027. Funding for parks grew by 5% over last year,\n"
    "while library hours were left unchanged. “We listened,” said the mayor — and acted."
)


def check_span(res, doc=DOC):
    assert res.start is not None
    return doc[res.start : res.end]


def test_exact_with_offsets():
    q = "It voted 7-2 to approve the budget."
    r = match_quote(DOC, q)
    assert r.status == "exact" and check_span(r) == q and r.occurrences == 1


def test_normalised_whitespace_case_quotes_dashes():
    r = match_quote(DOC, "the CITY council met on tuesday. it voted 7-2 to approve the budget.")
    assert r.status == "normalised"
    assert check_span(r).startswith("The city council") and check_span(r).endswith("budget.")
    r = match_quote(DOC, '"We listened," said the mayor - and acted.')
    assert r.status == "normalised" and check_span(r).endswith("acted.")


def test_line_break_in_source_and_hyphenation():
    doc = "Researchers found the effect was signif-\nicant across all trial sites."
    r = match_quote(doc, "the effect was significant across all trial sites")
    assert r.status == "normalised" and check_span(r, doc).endswith("sites")


def test_html_entities_and_nfkc_and_invisible():
    doc = "Profit rose to ﬁfty million (­​AT&T reported it)."
    r = match_quote(doc, "Profit rose to fifty million (AT&amp;T reported it).")
    assert r.status == "normalised"


def test_ellipsis_pieces_in_order():
    r = match_quote(DOC, "The mayor said the tax rate will not rise ... library hours were left unchanged.")
    assert r.status == "elided" and len(r.segments) == 2
    assert DOC[r.segments[0][0] : r.segments[0][1]].startswith("The mayor")
    r2 = match_quote(DOC, "library hours were left unchanged [...] The mayor said the tax rate will not rise")
    assert r2.status != "elided"  # wrong order is not accepted as elided


def test_numbers_changed_is_altered_not_found():
    r = match_quote(DOC, "Funding for parks grew by 15% over last year, while library hours were left unchanged.")
    assert r.status == "altered" and not r.found
    assert any("15%" in d["quote"] or "5%" in d["source"] for d in r.differences)
    assert check_span(r).startswith("Funding for parks")


def test_negation_dropped_is_altered():
    r = match_quote(DOC, "The mayor said the tax rate will rise in 2027.")
    assert r.status == "altered"
    r = match_quote(DOC, "The mayor said the tax rate will never rise in 2027.")
    assert r.status == "altered"


def test_vote_count_changed():
    r = match_quote(DOC, "It voted 9-2 to approve the budget.")
    assert r.status == "altered"


def test_near_but_wording_only():
    r = match_quote(DOC, "The mayor said the tax rate will not go up in 2027.")
    assert r.status == "near" and not r.found and r.similarity >= 0.8


def test_stitched_from_two_places():
    r = match_quote(DOC, "It voted 7-2 to approve the budget. Library hours were left unchanged.")
    assert r.status == "stitched" and len(r.segments) == 2 and not r.found


def test_fabricated_is_not_found():
    r = match_quote(DOC, "The council unanimously banned all cars from the downtown district.")
    assert r.status == "not_found" and r.start is None


def test_empty_and_short():
    assert match_quote(DOC, "   ").status == "not_found"
    assert match_quote("", "something").status == "not_found"
    r = match_quote(DOC, "the mayor")
    assert r.status == "exact" and "short_quote" in r.flags


def test_multiple_occurrences_counted():
    r = match_quote("alpha beta gamma. alpha beta gamma.", "alpha beta gamma.")
    assert r.status == "exact" and r.occurrences == 2 and r.start == 0


def test_normalise_offsets_roundtrip():
    n = normalise("A  B’s  “C”")
    assert n.text == "a b's \"c\""
    assert len(n.starts) == len(n.text)


def test_wide_gap_flag():
    doc = "start of the quote here" + (" filler" * 600) + " end of the quote there"
    r = match_quote(doc, "start of the quote here ... end of the quote there")
    assert r.status == "elided" and "wide_gap" in r.flags


GOOD = {"text": "Hello world.", "claims": [{"id": "a", "claim": "x", "url": "https://e.org", "quote": "q", "span": [0, 5]}]}


def test_schema_ok_and_bounds():
    cf = parse_claims(GOOD)
    assert cf.claims[0].span == (0, 5) and cf.claims[0].topic == "general"
    for bad in (
        {"text": "x", "claims": "no"},
        {"text": "x", "claims": [{"id": "a", "claim": "", "url": "u", "quote": "q"}]},
        {"text": "x", "claims": [{"id": "a b", "claim": "c", "url": "u", "quote": "q"}]},
        {"text": "x", "claims": [{"id": "a", "claim": "c", "url": "u", "quote": "q", "span": [0, 99]}]},
        {"text": "x" * 10, "claims": [
            {"id": "a", "claim": "c", "url": "u", "quote": "q", "span": [0, 6]},
            {"id": "b", "claim": "c", "url": "u", "quote": "q", "span": [4, 8]}]},
        {"text": "x", "claims": [{"id": "a", "claim": "c" * 700, "url": "u", "quote": "q"}]},
        [],
    ):
        with pytest.raises(SchemaError):
            parse_claims(bad)
