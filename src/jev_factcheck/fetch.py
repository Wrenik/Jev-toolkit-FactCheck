"""Fetch a source page safely and return its text.

What this guards against (details in docs/FACT_CHECKER.md, "Fetching"):
  SSRF (see netguard), redirects into private space (each hop is re-checked), huge or endless bodies
  (streamed, capped, gzip bombs capped), wrong content types, slow servers (timeouts), hammering a host
  (per-host delay, cache), scripts (nothing is executed, only text is extracted).

Network access goes through an injectable `Transport`, so tests and the evaluation never touch the net.
`FixtureFetcher` serves local files for URLs listed in a JSON map: the offline demo and tests use it.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import re
import socket
import ssl
import time
import zlib
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urljoin

from . import pdftext
from .htmltext import extract_text
from .netguard import BlockedURL, Resolver, Target, parse_target, resolve_public, system_resolver

USER_AGENT = (
    "jev-factcheck/0.1 (learning project; checks quotes in cited pages; github.com/Wrenik/Jev-toolkit-FactCheck)"
)
ALLOWED_TYPES = ("text/html", "application/xhtml+xml", "text/plain")
MAX_BYTES = 2_000_000
MAX_REDIRECTS = 5
CONNECT_TIMEOUT = 5.0
TOTAL_TIMEOUT = 20.0


_HTTP_HINTS = {
    401: " (login required)",
    402: " (payment required: paywall?)",
    403: " (forbidden: paywall or bot blocking?)",
    404: " (page not found: wrong or invented URL?)",
    410: " (page removed)",
    429: " (rate limited)",
    451: " (blocked for legal reasons)",
}


@dataclass
class FetchResult:
    url: str
    ok: bool
    # ok | blocked | unsupported_type | too_large | timeout | http_error | network_error | too_many_redirects | empty
    status: str
    detail: str = ""
    final_url: str = ""
    http_status: int | None = None
    content_type: str = ""
    text: str = ""
    title: str = ""
    dropped_hidden_chars: int = 0
    dropped_boilerplate_chars: int = 0
    from_cache: bool = False
    redirects: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("text")
        d["text_chars"] = len(self.text)
        d["text_sha256"] = hashlib.sha256(self.text.encode("utf-8")).hexdigest() if self.text else ""
        return d


class Response(Protocol):
    status: int
    headers: dict[str, str]

    def read(self, n: int) -> bytes: ...
    def close(self) -> None: ...


Transport = Callable[[Target, str, float], Response]  # (target, pinned ip, timeout) -> response


class _PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, host, port, ip, timeout):
        super().__init__(host, port, timeout=timeout)
        self._ip = ip

    def connect(self):
        self.sock = socket.create_connection((self._ip, self.port), timeout=self.timeout)


def _tls_context(system_store: bool) -> ssl.SSLContext:
    """Default verification. `system_store` asks the OS verifier instead (the `truststore` package, if present):
    Python on Windows only knows the roots already installed locally, so a valid chain can fail there."""
    if system_store:
        import truststore  # optional; ImportError is handled by the caller

        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    return ssl.create_default_context()


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, port, ip, timeout, system_store=False):
        super().__init__(host, port, timeout=timeout, context=_tls_context(system_store))
        self._ip = ip

    def connect(self):
        sock = socket.create_connection((self._ip, self.port), timeout=self.timeout)
        # Certificate and SNI are checked against the NAME, while the TCP connection goes to the checked IP.
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _HttpResponse:
    def __init__(self, conn, resp):
        self._conn, self._resp = conn, resp
        self.status = resp.status
        self.headers = {k.lower(): v for k, v in resp.getheaders()}

    def read(self, n: int) -> bytes:
        return self._resp.read(n)

    def close(self) -> None:
        self._conn.close()


def real_transport(target: Target, ip: str, timeout: float) -> Response:
    try:
        return _request(target, ip, timeout, system_store=False)
    except ssl.SSLCertVerificationError:
        try:
            import truststore  # noqa: F401
        except ImportError:
            raise
        return _request(target, ip, timeout, system_store=True)  # still verifies, with the OS trust store


def _request(target: Target, ip: str, timeout: float, *, system_store: bool) -> Response:
    if target.scheme == "https":
        conn: http.client.HTTPConnection = _PinnedHTTPS(target.host, target.port, ip, timeout, system_store)
    else:
        conn = _PinnedHTTP(target.host, target.port, ip, timeout)
    default_port = 443 if target.scheme == "https" else 80
    host_header = target.host if target.port == default_port else f"{target.host}:{target.port}"
    conn.request(
        "GET",
        target.path,
        headers={
            "Host": host_header,
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9"
            + (",application/pdf;q=0.5" if pdftext.available() else ""),
            "Accept-Encoding": "gzip, deflate",
            "Connection": "close",
        },
    )
    return _HttpResponse(conn, conn.getresponse())


_META_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?\s*([A-Za-z0-9_.:-]+)""", re.I)
_BOMS = ((b"\xef\xbb\xbf", "utf-8-sig"), (b"\xff\xfe", "utf-16"), (b"\xfe\xff", "utf-16"))


def _decode(raw: bytes, content_type: str) -> str:
    """Bytes -> text. Order: byte-order mark, charset header, <meta charset>, strict UTF-8, then Windows-1252
    (the usual unlabelled legacy encoding); never raises."""
    for bom, enc in _BOMS:
        if raw.startswith(bom):
            return raw.decode(enc, errors="replace")
    charset = None
    for part in content_type.split(";")[1:]:
        k, _, v = part.strip().partition("=")
        if k.lower() == "charset":
            charset = v.strip("\"' ")
    if not charset:
        m = _META_CHARSET.search(raw[:4096])
        if m:
            charset = m.group(1).decode("ascii", "ignore")
    if charset:
        try:
            return raw.decode(charset, errors="replace")
        except LookupError:
            pass
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def _read_body(resp: Response, limit: int) -> tuple[bytes | None, str]:
    """(body, "") or (None, reason). Decompresses with the same cap, so a gzip bomb cannot expand past it."""
    enc = resp.headers.get("content-encoding", "").lower().strip()
    raw = bytearray()
    decomp = None
    if enc in ("gzip", "x-gzip"):
        decomp = zlib.decompressobj(16 + zlib.MAX_WBITS)
    elif enc == "deflate":
        decomp = zlib.decompressobj()
    elif enc not in ("", "identity"):
        return None, f"unsupported content-encoding {enc}"
    wire = 0
    while True:
        chunk = resp.read(65536)
        if not chunk:
            break
        wire += len(chunk)
        if wire > limit * 2:
            return None, "response body too large on the wire"
        if decomp is not None:
            try:
                chunk = decomp.decompress(chunk, limit + 1 - len(raw))
            except zlib.error:
                return None, "corrupt compressed body"
        raw += chunk
        if len(raw) > limit:
            return None, "response body larger than the cap"
    return bytes(raw), ""


def _dial_order(addrs: list[str]) -> list[str]:
    """IPv4 and IPv6 alternating, IPv4 first. A host whose IPv6 route is dead (common) must not cost a full connect
    timeout per address before the working IPv4 address is tried (measured: 8 s each, twice, on a plain home line)."""
    v4 = [a for a in addrs if ":" not in a]
    v6 = [a for a in addrs if ":" in a]
    out: list[str] = []
    for i in range(max(len(v4), len(v6))):
        out += v4[i : i + 1] + v6[i : i + 1]
    return out


class Fetcher:
    def __init__(
        self,
        cache_dir: str | Path | None = None,
        *,
        transport: Transport = real_transport,
        resolver: Resolver = system_resolver,
        max_bytes: int = MAX_BYTES,
        timeout: float = TOTAL_TIMEOUT,
        per_host_delay: float = 1.0,
        cache_max_age: float = 7 * 86400,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        wall: Callable[[], float] = time.time,
    ):
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.transport, self.resolver = transport, resolver
        self.max_bytes, self.timeout = max_bytes, timeout
        self.per_host_delay, self.cache_max_age = per_host_delay, cache_max_age
        self._clock, self._sleep, self._wall = clock, sleep, wall
        self._last_hit: dict[str, float] = {}

    # -- cache ---------------------------------------------------------------------------------
    def _cache_path(self, url: str) -> Path | None:
        if not self.cache_dir:
            return None
        return self.cache_dir / (hashlib.sha256(url.encode()).hexdigest()[:40] + ".json")

    def _cache_get(self, url: str) -> FetchResult | None:
        p = self._cache_path(url)
        if not p or not p.is_file():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if self._wall() - data["fetched_at"] > self.cache_max_age:
                return None
            r = FetchResult(**data["result"])
            r.from_cache = True
            return r
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _cache_put(self, url: str, r: FetchResult) -> None:
        p = self._cache_path(url)
        if not p:
            return
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"fetched_at": self._wall(), "result": asdict(r)}), encoding="utf-8")
        except OSError:
            pass  # the cache is an optimisation only

    # -- fetching ------------------------------------------------------------------------------
    def _wait_politely(self, host: str) -> None:
        last = self._last_hit.get(host)
        if last is not None:
            wait = self.per_host_delay - (self._clock() - last)
            if wait > 0:
                self._sleep(wait)
        self._last_hit[host] = self._clock()

    def fetch(self, url: str) -> FetchResult:
        cached = self._cache_get(url)
        if cached is not None:
            return cached
        result = self._fetch_uncached(url)
        if result.ok:
            self._cache_put(url, result)
        return result

    def _fetch_uncached(self, url: str) -> FetchResult:
        chain: list[str] = []
        current = url
        deadline = self._clock() + self.timeout
        for _hop in range(MAX_REDIRECTS + 1):
            try:
                target = parse_target(current)
                addrs = resolve_public(target, self.resolver)
            except BlockedURL as exc:
                return FetchResult(url, False, "blocked", str(exc), redirects=chain)
            self._wait_politely(target.host)
            resp = None
            last_error = ""
            for ip in _dial_order(addrs)[:4]:  # a few addresses, all already verified public
                try:
                    resp = self.transport(target, ip, min(CONNECT_TIMEOUT, max(0.5, deadline - self._clock())))
                    break
                except TimeoutError:
                    last_error = "timeout"
                except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
                    last_error = f"{type(exc).__name__}: {exc}"
            if resp is None:
                kind = "timeout" if last_error == "timeout" else "network_error"
                return FetchResult(url, False, kind, last_error, redirects=chain)
            try:
                if resp.status in (301, 302, 303, 307, 308):
                    loc = resp.headers.get("location", "")
                    if not loc:
                        return FetchResult(
                            url,
                            False,
                            "http_error",
                            f"HTTP {resp.status} without Location",
                            http_status=resp.status,
                            redirects=chain,
                        )
                    current = urljoin(current, loc)
                    chain.append(current)
                    continue
                ctype_full = resp.headers.get("content-type", "").lower()
                ctype = ctype_full.split(";")[0].strip()
                if resp.status != 200:
                    return FetchResult(
                        url,
                        False,
                        "http_error",
                        f"HTTP {resp.status}{_HTTP_HINTS.get(resp.status, '')}",
                        current,
                        resp.status,
                        ctype,
                        redirects=chain,
                    )
                is_pdf = ctype == "application/pdf" and pdftext.available()
                if ctype and ctype not in ALLOWED_TYPES and not is_pdf:
                    kind = "PDF" if ctype == "application/pdf" else ctype
                    hint = (
                        "; cite an HTML page that has the text, or install the 'pdf' extra (pip install jev-toolkit-factcheck[pdf])"
                        if kind == "PDF"
                        else ""
                    )
                    return FetchResult(
                        url,
                        False,
                        "unsupported_type",
                        f"content type {kind} is not read{hint}",
                        current,
                        200,
                        ctype,
                        redirects=chain,
                    )
                declared = resp.headers.get("content-length", "")
                if declared.isdigit() and int(declared) > self.max_bytes * 2:
                    return FetchResult(
                        url, False, "too_large", f"Content-Length {declared}", current, 200, ctype, redirects=chain
                    )
                try:
                    body, why = _read_body(resp, self.max_bytes)
                except TimeoutError:
                    return FetchResult(
                        url, False, "timeout", "while reading the body", current, 200, ctype, redirects=chain
                    )
                except (OSError, http.client.HTTPException) as exc:
                    return FetchResult(
                        url,
                        False,
                        "network_error",
                        f"{type(exc).__name__}: {exc}",
                        current,
                        200,
                        ctype,
                        redirects=chain,
                    )
                if body is None:
                    return FetchResult(url, False, "too_large", why, current, 200, ctype, redirects=chain)
            finally:
                resp.close()
            if is_pdf:
                try:
                    page = pdftext.extract_pdf(body)
                except ValueError as exc:
                    return FetchResult(
                        url, False, "unsupported_type", f"PDF not read: {exc}", current, 200, ctype, redirects=chain
                    )
            else:
                page = extract_text(_decode(body, ctype_full), ctype or "text/html")
            if not page.text.strip():
                return FetchResult(
                    url,
                    False,
                    "empty",
                    "no readable text (script-rendered, scanned PDF without a text layer, or empty page?)",
                    current,
                    200,
                    ctype,
                    dropped_hidden_chars=page.dropped_chars,
                    redirects=chain,
                )
            return FetchResult(
                url,
                True,
                "ok",
                "",
                current,
                200,
                ctype,
                page.text,
                page.title,
                page.dropped_chars,
                page.boilerplate_chars,
                redirects=chain,
            )
        return FetchResult(url, False, "too_many_redirects", f"more than {MAX_REDIRECTS}", redirects=chain)


class FixtureFetcher:
    """Serves local files for URLs: `map` is {url: filename} relative to `root` (JSON file or dict)."""

    def __init__(self, root: str | Path, mapping: dict[str, Any] | None = None):
        self.root = Path(root)
        if mapping is None:
            mapping = json.loads((self.root / "urls.json").read_text(encoding="utf-8"))
        self.mapping = mapping

    def fetch(self, url: str) -> FetchResult:
        entry = self.mapping.get(url.strip())
        if entry is None:
            return FetchResult(url, False, "network_error", "URL not in the fixture map (offline mode)")
        if isinstance(entry, str):
            entry = {"file": entry}
        status = entry.get("status", "ok")
        if status != "ok":  # fixtures can simulate failures: paywall, timeout, pdf ...
            return FetchResult(
                url, False, status, entry.get("detail", "simulated"), http_status=entry.get("http_status")
            )
        path = (self.root / entry["file"]).resolve()
        if self.root.resolve() not in path.parents:
            return FetchResult(url, False, "blocked", "fixture path escapes the fixture folder")
        raw = path.read_bytes().decode("utf-8", errors="replace")
        ctype = entry.get("content_type", "text/html")
        page = extract_text(raw, ctype)
        if not page.text.strip():
            return FetchResult(
                url, False, "empty", "no readable text", url, 200, ctype, dropped_hidden_chars=page.dropped_chars
            )
        return FetchResult(url, True, "ok", "", url, 200, ctype, page.text, page.title, page.dropped_chars)
