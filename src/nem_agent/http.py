"""Bounded HTTP client: explicit timeouts, capped retries with backoff, byte ceiling, host politeness."""

from __future__ import annotations

import contextlib
import os
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

USER_AGENT = "nem-event-intelligence-agent/0.1 (independent public-data research project)"
MAX_BYTES_DEFAULT = 60 * 1024 * 1024
RETRY_STATUSES = {429, 500, 502, 503, 504}
# NEMWeb's firewall answers HTTP 403 to bursts of requests from one client. Politeness: at most 3 concurrent
# requests to that host, and a 403 from it is treated as throttling (retried with backoff, then reported).
_HOST_LIMITS = {"nemweb.com.au": threading.BoundedSemaphore(3)}
_THROTTLE_403_HOSTS = {"nemweb.com.au"}
_MIN_SPACING_S = {"nemweb.com.au": 0.3}  # minimum gap between request starts to the same host
_last_start: dict[str, float] = {}
_spacing_lock = threading.Lock()
# Simulation switch for testing retention behaviour: when NEM_AGENT_SIMULATE_ROLLED_OFF=1, every NEMWeb
# "Reports/Current" URL answers a *simulated* 404 (as after NEMWeb's rolling retention removes a file). Archive
# URLs and other hosts are unaffected. The error text says it is simulated; nothing is fabricated.
_CURRENT_PATH = "/reports/current/"
_KEEP_HEADERS = {"etag", "last-modified", "content-type", "content-length", "server", "cf-mitigated"}


@dataclass
class HttpResult:
    url: str
    status: int | None
    content_type: str | None = None
    content_length: int | None = None
    last_modified: str | None = None
    body: bytes | None = None
    error: str | None = None
    attempts: int = 0
    elapsed_s: float = 0.0
    final_url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == 200 and self.error is None


def _space(host: str) -> None:
    gap = _MIN_SPACING_S.get(host)
    if not gap:
        return
    with _spacing_lock:
        now = time.monotonic()
        wait = _last_start.get(host, 0.0) + gap - now
        if wait > 0:
            time.sleep(wait)
        _last_start[host] = time.monotonic()


def _attempt(url: str, method: str, timeout: float, max_bytes: int, result: HttpResult) -> None:
    _space(urlparse(url).hostname or "")
    client = httpx.Client(
        timeout=httpx.Timeout(timeout, connect=min(timeout, 20.0)),
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    )
    with client, client.stream(method, url) as resp:
        result.status = resp.status_code
        result.final_url = str(resp.url)
        result.content_type = resp.headers.get("content-type")
        cl = resp.headers.get("content-length")
        result.content_length = int(cl) if cl and cl.isdigit() else None
        result.last_modified = resp.headers.get("last-modified")
        result.headers = {k.lower(): v for k, v in resp.headers.items() if k.lower() in _KEEP_HEADERS}
        result.body = None
        result.error = None
        if method != "GET":
            return
        if result.content_length and result.content_length > max_bytes:
            raise ValueError(f"content-length {result.content_length} exceeds cap {max_bytes}")
        chunks: list[bytes] = []
        total = 0
        for chunk in resp.iter_bytes():
            total += len(chunk)
            if total > max_bytes:
                raise ValueError(f"body exceeds cap {max_bytes} bytes")
            chunks.append(chunk)
        result.body = b"".join(chunks)
        result.content_length = total


def fetch(
    url: str,
    *,
    method: str = "GET",
    timeout: float = 90.0,
    retries: int = 3,
    backoff_s: float = 2.0,
    max_bytes: int = MAX_BYTES_DEFAULT,
) -> HttpResult:
    """Fetch ``url``; never raises for HTTP/network errors (they are returned in ``HttpResult``)."""
    result = HttpResult(url=url, status=None)
    if os.environ.get("NEM_AGENT_SIMULATE_ROLLED_OFF") == "1" and "nemweb.com.au" in url and \
            _CURRENT_PATH in urlparse(url).path.lower():
        result.status, result.error = 404, "HTTP 404 (SIMULATED: NEM_AGENT_SIMULATE_ROLLED_OFF=1)"
        return result
    start = time.monotonic()
    host = urlparse(url).hostname or ""
    limiter = _HOST_LIMITS.get(host)
    retry_statuses = RETRY_STATUSES | ({403} if host in _THROTTLE_403_HOSTS else set())
    for attempt in range(1, retries + 1):
        result.attempts = attempt
        try:
            with limiter if limiter is not None else contextlib.nullcontext():
                _attempt(url, method, timeout, max_bytes, result)
        except ValueError as exc:  # size cap: not retryable
            result.error = str(exc)
            result.body = None
            break
        except httpx.HTTPError as exc:
            result.error = f"{type(exc).__name__}: {exc}"
            if attempt < retries:
                time.sleep(backoff_s * 2 ** (attempt - 1))
            continue
        if result.status in retry_statuses and attempt < retries:
            time.sleep(backoff_s * 2 ** (attempt - 1))
            continue
        break
    result.elapsed_s = round(time.monotonic() - start, 3)
    if result.status is not None and result.status != 200 and result.error is None:
        result.error = f"HTTP {result.status}"
    return result
