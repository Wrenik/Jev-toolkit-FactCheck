"""Which URLs and addresses the fetcher may connect to (SSRF protection).

The page URL comes from an LLM, so it is attacker-influenced. Rules:
  * http and https only, no user:password@, no empty host, bounded length;
  * every address the name resolves to (A and AAAA) must be public; one private address rejects the host;
  * IPv4-mapped IPv6 (::ffff:10.0.0.1) is unwrapped before the check;
  * the caller then connects to the address that was checked, not to the name again (no DNS rebinding gap).
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

MAX_URL_LEN = 2000
ALLOWED_PORTS: set[int] | None = {80, 443}  # default; set to None to allow any port on a public address

Resolver = Callable[[str, int], list[str]]


class BlockedURL(Exception):
    """The URL or the address behind it is not allowed. `reason` is a short stable code."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class Target:
    scheme: str
    host: str
    port: int
    path: str  # path + query, always starting with "/"
    url: str


# Extra ranges that ipaddress.is_global may let through or that deserve an explicit reason.
_EXTRA_BLOCKED = [ipaddress.ip_network(n) for n in ("100.64.0.0/10", "192.0.0.0/24", "198.18.0.0/15", "169.254.0.0/16", "fc00::/7", "fe80::/10")]


def is_public_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value.split("%")[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        elif ip.sixtofour is not None and not ip.sixtofour.is_global:
            return False
        elif ip.teredo is not None:
            return False  # tunnelled; the embedded client address is not checkable
    if any(ip in net for net in _EXTRA_BLOCKED):
        return False
    return ip.is_global and not ip.is_multicast


def parse_target(url: str) -> Target:
    if not isinstance(url, str) or not url.strip():
        raise BlockedURL("empty_url")
    url = url.strip()
    if len(url) > MAX_URL_LEN:
        raise BlockedURL("url_too_long")
    if any(ord(c) < 33 or ord(c) == 127 for c in url):
        raise BlockedURL("bad_characters", "whitespace or control characters in URL")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise BlockedURL("malformed_url", str(exc)) from exc
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise BlockedURL("bad_scheme", scheme or "none")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise BlockedURL("userinfo_in_url")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise BlockedURL("no_host")
    port = port or (443 if scheme == "https" else 80)
    if ALLOWED_PORTS is not None and port not in ALLOWED_PORTS:
        raise BlockedURL("port_not_allowed", str(port))
    if not host.isascii():
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise BlockedURL("bad_idna_host", str(exc)) from exc
        if not host.isascii():
            raise BlockedURL("bad_idna_host", "host is not ASCII after IDNA")
    if any(label == "" or len(label) > 63 for label in host.split(".")):
        raise BlockedURL("malformed_host", host)
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    return Target(scheme, host, port, path, url)


def system_resolver(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    seen: list[str] = []
    for info in infos:
        addr = info[4][0]
        if addr not in seen:
            seen.append(addr)
    return seen


def resolve_public(target: Target, resolver: Resolver = system_resolver) -> list[str]:
    """Addresses to connect to, all verified public. Raises BlockedURL otherwise."""
    # A literal IP is checked as is (no lookup); "0x7f.1", "2130706433" etc. are caught by ipaddress/getaddrinfo.
    try:
        literal = ipaddress.ip_address(target.host.strip("[]"))
        addrs = [str(literal)]
    except ValueError:
        try:
            addrs = resolver(target.host, target.port)
        except OSError as exc:
            raise BlockedURL("dns_failure", str(exc)) from exc
    if not addrs:
        raise BlockedURL("dns_failure", "no addresses")
    bad = [a for a in addrs if not is_public_ip(a)]
    if bad:
        raise BlockedURL("non_public_address", f"{target.host} resolves to {bad[0]}")
    return addrs
