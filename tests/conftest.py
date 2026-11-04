"""Keep every test away from the real ~/.jev-toolkit and from any .env."""

import pytest


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("JEV_HOME", str(tmp_path / "jev-home"))
    monkeypatch.setenv("JEV_JUDGE", "fake")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
