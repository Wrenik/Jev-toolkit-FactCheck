"""CLI, demo and evaluation wiring. Offline, no key, no network."""

import json

from jev_factcheck import evaluate
from jev_factcheck.__main__ import main
from jev_factcheck.demojudge import DemoJudge


def test_demo_runs_offline_and_writes_safe_html(tmp_path, capsys):
    out = tmp_path / "demo.html"
    assert main(["demo", "--out", str(out)]) == 1  # some claims are flagged, so exit 1
    html = out.read_text(encoding="utf-8")
    assert "<script" not in html and "Content-Security-Policy" in html
    text = capsys.readouterr().out
    assert "claims checked" in text and "not that the source is true" in text


def test_demo_no_judge_says_quote_only(tmp_path, capsys):
    out = tmp_path / "d.html"
    main(["demo", "--no-judge", "--out", str(out)])
    assert "Judge: off" in capsys.readouterr().out
    assert "Quote-match only" in out.read_text(encoding="utf-8")


def test_check_with_fixtures_and_correction_round(tmp_path, capsys):
    claims = {
        "text": "Bridge opened 1923.",
        "claims": [
            {
                "id": "a",
                "claim": "Bridge opened 1932.",
                "url": "https://fixture.test/bridge",
                "quote": "The Harbor Bridge opened to traffic in 1923.",
                "span": [0, 19],
            }
        ],
    }
    cpath, state, corr = tmp_path / "c.json", tmp_path / "s.json", tmp_path / "corr.json"
    cpath.write_text(json.dumps(claims), encoding="utf-8")
    args = [
        "check",
        str(cpath),
        "--fixtures",
        str(evaluate.PAGES),
        "--no-judge",
        "--out",
        str(tmp_path / "r.html"),
        "--state",
        str(state),
        "--corrections",
        str(corr),
    ]
    assert main(args) == 1
    c = json.loads(corr.read_text(encoding="utf-8"))
    assert c["claims"][0]["state"] == "quote_not_found" and "1932" in c["claims"][0]["untrusted_source_excerpt"]
    claims["claims"][0]["quote"] = "The Harbor Bridge opened to traffic in 1932."
    cpath.write_text(json.dumps(claims), encoding="utf-8")
    assert main(args) == 0
    assert "Loop finished" in capsys.readouterr().out


def test_bad_claims_file_exits_2(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text('{"claims": "no"}', encoding="utf-8")
    assert main(["check", str(p), "--no-judge"]) == 2


def test_eval_sets_load_and_quote_layer_is_deterministic():
    for name in ("dev", "heldout"):
        run = evaluate.run_set(name, DemoJudge())
        s = evaluate.score(run)
        assert s["n"] >= 20 and s["quote_layer"][0] == s["quote_layer"][1]  # recorded result, see docs
        assert "injection" not in "".join(r["reason"] for r in run["rows"] if r["category"] == "supported")


def test_page_injection_never_reaches_judge_in_eval():
    class Spy(DemoJudge):
        seen: list = []

        def ask(self, state, questions):
            Spy.seen.append(state)
            return super().ask(state, questions)

    evaluate.run_set("dev", Spy())
    assert not any(
        "ignore all previous" in json.dumps(s).lower() or "mark all claims" in json.dumps(s).lower() for s in Spy.seen
    )


def test_span_found_automatically_when_claim_is_verbatim_in_text():
    from jev_factcheck.schema import parse_claims

    cf = parse_claims(
        {
            "text": "Intro. Water boils at 100 C. Outro.",
            "claims": [
                {"id": "a", "claim": "Water boils at 100 C.", "url": "https://x.test/", "quote": "q"},
                {"id": "b", "claim": "Not in the text.", "url": "https://x.test/", "quote": "q"},
            ],
        }
    )
    assert cf.claims[0].span == (7, 28) and cf.claims[1].span is None


def test_prompt_is_pasteable(capsys):
    assert main(["prompt"]) == 0
    out = capsys.readouterr().out
    assert "claims.json" in out and "VERBATIM" in out and "jev_factcheck check" in out
