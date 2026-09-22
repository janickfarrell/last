from __future__ import annotations

import asyncio
import logging
import socket
import time
from collections.abc import Iterable

import httpx

logger = logging.getLogger(__name__)


class GeoResolver:
    """Async GeoIP resolver with caching, bounded concurrency, and rate limiting."""

    def __init__(self, min_interval_seconds: float = 1.5, concurrency: int = 4) -> None:
        self._min_interval = max(0.0, float(min_interval_seconds))
        self._sem = asyncio.Semaphore(max(1, int(concurrency)))
        self._request_lock = asyncio.Lock()
        self._last_request = 0.0
        self._cache: dict[str, str] = {}

    async def _resolve_ip(self, host: str) -> str | None:
        try:
            return await asyncio.to_thread(socket.gethostbyname, host)
        except OSError:
            return None

    async def country_for(self, host: str) -> str | None:
        host = host.strip()
        if not host:
            return None
        ip = host
        try:
            socket.inet_aton(host)
        except OSError:
            ip = await self._resolve_ip(host) or ""
        if not ip:
            return None
        if ip in self._cache:
            return self._cache[ip]

        async with self._sem:
            if ip in self._cache:
                return self._cache[ip]
            async with self._request_lock:
                wait = self._min_interval - (time.monotonic() - self._last_request)
                if wait > 0:
                    await asyncio.sleep(wait)
                self._last_request = time.monotonic()
                try:
                    base = "https" + "://ipapi.co"
                    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                        response = await client.get(f"{base}/{ip}/json/")
                        response.raise_for_status()
                        code = str(response.json().get("country_code") or "").strip().upper()
                except (httpx.HTTPError, ValueError) as exc:
                    logger.warning("GeoIP lookup failed for %s: %s", ip, exc)
                    return None
            if code:
                self._cache[ip] = code
                return code
        return None

    async def countries_for(self, hosts: Iterable[str]) -> dict[str, str | None]:
        unique = list(dict.fromkeys(h.strip() for h in hosts if h and h.strip()))
        values = await asyncio.gather(*(self.country_for(host) for host in unique))
        return dict(zip(unique, values, strict=False))
