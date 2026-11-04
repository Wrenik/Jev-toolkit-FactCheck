"""The documents a stranger copies from must stay in step with the code."""

import json
import re
from pathlib import Path

from jev_factcheck import schema
from jev_factcheck.__main__ import PROMPT, main
from jev_factcheck.schema import load_claims

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / "src/jev_factcheck/data/claims.schema.json").read_text(encoding="utf-8"))


def test_schema_limits_match_the_code():
    item = SCHEMA["properties"]["claims"]["items"]["properties"]
    assert SCHEMA["properties"]["claims"]["maxItems"] == schema.MAX_CLAIMS
    assert SCHEMA["properties"]["text"]["maxLength"] == schema.MAX_TEXT
    assert item["claim"]["maxLength"] == schema.MAX_CLAIM and item["quote"]["maxLength"] == schema.MAX_QUOTE
    assert item["url"]["maxLength"] == schema.MAX_URL
    assert re.compile(item["id"]["pattern"]).match("c1") and not re.compile(item["id"]["pattern"]).match("bad id")
    assert set(SCHEMA["properties"]["claims"]["items"]["required"]) == {"claim", "url", "quote"}


def test_example_files_validate():
    assert len(load_claims(str(ROOT / "docs/claims.example.json")).claims) == 2
    assert len(load_claims(str(ROOT / "examples/claims.json")).claims) == 3


def test_prompt_docs_are_in_step_with_the_cli_prompt():
    assert PROMPT in (ROOT / "docs/CLAUDE_PROMPT.md").read_text(encoding="utf-8")
    skill = (ROOT / "docs/claude-skill/SKILL.md").read_text(encoding="utf-8")
    assert skill.startswith("---\nname: factcheck\n") and "claims.json" in skill
    assert PROMPT.split("My question:")[0] in skill


def test_committed_example_report_is_current_and_self_contained():
    html = (ROOT / "docs/example_report.html").read_text(encoding="utf-8")
    assert "Content-Security-Policy" in html and "<script" not in html.lower() and "http://" not in html.replace("http://fixture", "")
    assert chr(92) + "Users" + chr(92) not in html and "/home/" not in html


def test_examples_run_offline_and_catch_the_planted_misquote(tmp_path, capsys):
    code = main(["check", str(ROOT / "examples/claims.json"), "--fixtures", str(ROOT / "examples/fixtures"), "--no-judge",
                 "--out", str(tmp_path / "r.html"), "--json", str(tmp_path / "r.json"), "--corrections", str(tmp_path / "c.json")])
    assert code == 1
    res = {r["id"]: r for r in json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))}
    assert res["c1"]["state"] == "quote_only" and res["c2"]["state"] == "quote_not_found" and res["c2"]["reason"] == "altered_quote"
    assert (tmp_path / "c.json").is_file()


def test_validate_and_schema_commands(capsys):
    assert main(["validate", str(ROOT / "docs/claims.example.json")]) == 0
    assert "OK: 2 claims" in capsys.readouterr().out
    assert main(["schema"]) == 0
    assert json.loads(capsys.readouterr().out)["title"].startswith("jev_factcheck")
