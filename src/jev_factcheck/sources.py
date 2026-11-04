"""Per-topic source lists (editable data) and the "unusual domain" flag.

The lists are written and maintained by the user. This module only compares a URL's host with them
and returns flags. A flag says "look at this source", never "this source is wrong".
"""

from __future__ import annotations

import ipaddress
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_FILE = Path(__file__).parent / "data" / "sources.example.toml"


class SourceListError(ValueError):
    pass


@dataclass
class TopicList:
    trusted: list[str] = field(default_factory=list)
    suspect: list[str] = field(default_factory=list)


@dataclass
class SourceLists:
    topics: dict[str, TopicList]
    version: int = 1
    curated_by: str = ""

    def check(self, url: str, topic: str = "general") -> tuple[list[str], str]:
        """(flags, note). Flags: suspect_domain, unusual_domain, no_list_for_topic, insecure_scheme, ip_literal_host."""
        try:
            parts = urlsplit(url)
            host = (parts.hostname or "").lower().rstrip(".")
        except ValueError:
            return ["unparseable_url"], "URL could not be parsed"
        flags: list[str] = []
        notes: list[str] = []
        if parts.scheme == "http":
            flags.append("insecure_scheme")
        try:
            ipaddress.ip_address(host)
            flags.append("ip_literal_host")
        except ValueError:
            pass
        tl = self.topics.get(topic)
        if tl is None:
            flags.append("no_list_for_topic")
            notes.append(f"no source list for topic {topic!r}")
        else:
            if any(_match(host, e) for e in tl.suspect):
                flags.append("suspect_domain")
                notes.append(f"{host} is on the suspect list for {topic!r}")
            elif tl.trusted and not any(_match(host, e) for e in tl.trusted):
                flags.append("unusual_domain")
                notes.append(f"{host} is not on the trusted list for {topic!r}")
        return flags, "; ".join(notes)


def _match(host: str, entry: str) -> bool:
    entry = entry.lower().strip()
    if entry.startswith("*."):
        return host.endswith(entry[1:])
    return host == entry or host.endswith("." + entry)


def load_sources(path: str | Path | None = None) -> SourceLists:
    p = Path(path) if path else DEFAULT_FILE
    try:
        data = tomllib.loads(p.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise SourceListError(f"cannot read source list {p.name}: {exc}") from exc
    topics: dict[str, TopicList] = {}
    for name, body in (data.get("topics") or {}).items():
        if not isinstance(body, dict):
            raise SourceListError(f"topics.{name}: expected a table")
        lists = {}
        for key in ("trusted", "suspect"):
            val = body.get(key, [])
            if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
                raise SourceListError(f"topics.{name}.{key}: expected a list of strings")
            lists[key] = val
        topics[name] = TopicList(**lists)
    return SourceLists(topics, int(data.get("version", 1)), str(data.get("curated_by", "")))
