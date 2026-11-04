import pytest

from jev_factcheck.sources import SourceListError, load_sources


def test_example_list_flags():
    s = load_sources()
    assert s.check("https://www.who.int/x", "health") == ([], "")
    flags, note = s.check("https://random-blog.test/x", "health")
    assert flags == ["unusual_domain"] and "trusted list" in note
    assert s.check("https://x.test/", "general")[0] == []  # empty trusted list = no opinion
    assert "no_list_for_topic" in s.check("https://x.test/", "cooking")[0]
    assert "insecure_scheme" in s.check("http://nih.gov/", "health")[0]
    assert "ip_literal_host" in s.check("https://93.184.216.34/", "health")[0]
    assert s.check("https://cs.stanford.edu/p", "science")[0] == []
    assert "unusual_domain" in s.check("https://notnature.com/", "science")[0]  # not a subdomain match


def test_suspect_and_bad_file(tmp_path):
    p = tmp_path / "s.toml"
    p.write_text('[topics.t]\nsuspect=["bad.test"]\ntrusted=["ok.test"]\n', encoding="utf-8")
    s = load_sources(p)
    assert s.check("https://sub.bad.test/", "t")[0] == ["suspect_domain"]
    p.write_text("[topics.t]\ntrusted='x'\n", encoding="utf-8")
    with pytest.raises(SourceListError):
        load_sources(p)
    with pytest.raises(SourceListError):
        load_sources(tmp_path / "missing.toml")
