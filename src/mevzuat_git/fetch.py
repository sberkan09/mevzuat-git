"""Polite, cached HTTP access. Every network request in this project goes through here.

Responses are cached under ``data/raw/<host>/...`` (not committed). A cache entry is the
response body plus a ``.meta.json`` sidecar; "not found" answers are cached too so that
date scans over the Resmî Gazete archive do not repeat misses.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from mevzuat_git import __version__

USER_AGENT = (
    f"mevzuat-git/{__version__} (+https://github.com/sberkan09/mevzuat-git; "
    "research project rebuilding Turkish legislation history)"
)
DEFAULT_CACHE_DIR = Path("data/raw")


class NotFound(Exception):
    """The server says the resource does not exist (404, or mevzuat.gov.tr's error page)."""


@dataclass
class Response:
    url: str
    status: int
    content: bytes
    content_type: str | None
    from_cache: bool


def cache_path(url: str, cache_dir: Path = DEFAULT_CACHE_DIR) -> Path:
    """Map a URL to a stable, readable file path under the cache directory."""
    parts = urlsplit(url)
    path = parts.path.strip("/") or "index"
    name = path
    if parts.query:
        name += "__" + parts.query
    name = re.sub(r"[^A-Za-z0-9._/=&-]", "_", name)
    # Keep file names short enough for every filesystem.
    segments = name.split("/")
    if len(segments[-1]) > 150:
        digest = hashlib.sha1(segments[-1].encode()).hexdigest()[:12]
        segments[-1] = segments[-1][:120] + "_" + digest
    return cache_dir / parts.netloc.lower() / Path(*segments)


def _is_error_redirect(url: httpx.URL) -> bool:
    return "errorpage" in url.path.lower()


class Fetcher:
    """httpx client with an on-disk cache, a per-host rate limit and retries."""

    def __init__(
        self,
        cache_dir: Path = DEFAULT_CACHE_DIR,
        min_interval: float = 1.0,
        timeout: float = 45.0,
        retries: int = 4,
        offline: bool = False,
        client: httpx.Client | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.min_interval = min_interval
        self.retries = retries
        self.offline = offline
        self._last_request: dict[str, float] = {}
        self._client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "tr,en;q=0.5"},
            timeout=httpx.Timeout(timeout, connect=20.0),
            follow_redirects=True,
        )
        self.network_requests = 0

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Fetcher:  # noqa: PYI034
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- cache ---------------------------------------------------------------------------

    def _read_cache(self, url: str) -> Response | None:
        body_path = cache_path(url, self.cache_dir)
        meta_path = body_path.with_name(body_path.name + ".meta.json")
        if not meta_path.exists():
            return None
        meta = json.loads(meta_path.read_text())
        if meta["status"] == 404:
            raise NotFound(url)
        return Response(
            url=url,
            status=meta["status"],
            content=body_path.read_bytes(),
            content_type=meta.get("content_type"),
            from_cache=True,
        )

    def _write_cache(self, url: str, status: int, content: bytes, content_type: str | None,
                     final_url: str) -> None:
        body_path = cache_path(url, self.cache_dir)
        body_path.parent.mkdir(parents=True, exist_ok=True)
        if status != 404:
            body_path.write_bytes(content)
        meta = {
            "url": url,
            "final_url": final_url,
            "status": status,
            "content_type": content_type,
            "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        body_path.with_name(body_path.name + ".meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=1)
        )

    def is_cached(self, url: str) -> bool:
        p = cache_path(url, self.cache_dir)
        return p.with_name(p.name + ".meta.json").exists()

    # -- network -------------------------------------------------------------------------

    def _throttle(self, host: str) -> None:
        last = self._last_request.get(host)
        if last is not None:
            wait = self.min_interval - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
        self._last_request[host] = time.monotonic()

    def get(self, url: str, refresh: bool = False) -> Response:
        """GET ``url``, from cache when possible. Raises :class:`NotFound` on 404."""
        if not refresh:
            cached = self._read_cache(url)
            if cached is not None:
                return cached
        if self.offline:
            raise RuntimeError(f"offline mode and not cached: {url}")

        host = urlsplit(url).netloc.lower()
        delay = 2.0
        last_exc: Exception | None = None
        for attempt in range(self.retries + 1):
            self._throttle(host)
            try:
                self.network_requests += 1
                r = self._client.get(url)
            except httpx.TransportError as exc:  # timeouts, resets
                last_exc = exc
            else:
                if r.status_code == 404 or _is_error_redirect(r.url):
                    self._write_cache(url, 404, b"", None, str(r.url))
                    raise NotFound(url)
                if r.status_code < 500 and r.status_code != 429:
                    r.raise_for_status()
                    ctype = r.headers.get("content-type")
                    self._write_cache(url, r.status_code, r.content, ctype, str(r.url))
                    return Response(url, r.status_code, r.content, ctype, from_cache=False)
                last_exc = httpx.HTTPStatusError(
                    f"{r.status_code} for {url}", request=r.request, response=r
                )
            if attempt < self.retries:
                time.sleep(delay)
                delay *= 2
        assert last_exc is not None
        raise last_exc


def decode_html(content: bytes) -> str:
    """Decode a page from either site.

    mevzuat.gov.tr serves Word-exported HTML that *declares* windows-1254 but is UTF-8;
    resmigazete.gov.tr pages are windows-1254. UTF-8 is tried first because a cp1254
    byte sequence is almost never valid UTF-8.
    """
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("cp1254", errors="replace")
