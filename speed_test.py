from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import httpx

from singbox_runner import SingBoxRunner


@dataclass(frozen=True)
class SpeedResult:
    tag: str
    label: str
    download_bps: float
    upload_bps: float

    @property
    def download_kib_s(self) -> float:
        return self.download_bps / 1024.0

    @property
    def upload_kib_s(self) -> float:
        return self.upload_bps / 1024.0


async def _stream_download(client: httpx.AsyncClient, url: str) -> tuple[int, float]:
    start = time.perf_counter()
    total = 0
    async with client.stream("GET", url) as response:
        response.raise_for_status()
        async for chunk in response.aiter_bytes():
            total += len(chunk)
    return total, max(0.001, time.perf_counter() - start)


async def _upload(client: httpx.AsyncClient, url: str, size: int) -> tuple[int, float]:
    payload = b"0" * size
    start = time.perf_counter()
    response = await client.post(url, content=payload, headers={"Content-Type": "application/octet-stream"})
    response.raise_for_status()
    return size, max(0.001, time.perf_counter() - start)


def _format_speed_line(result: SpeedResult) -> str:
    return f"{result.label}\tdl_kib_s={result.download_kib_s:.0f}\tul_kib_s={result.upload_kib_s:.0f}"


async def find_fast_nodes(
    singbox_path: str,
    clash_api_host: str,
    clash_api_port: int,
    outbounds: list[dict],
    labels_by_tag: dict[str, str],
    threshold_kib_s: int = 500,
    max_nodes: int = 20,
    concurrency: int = 1,
    download_bytes: int = 2_000_000,
    upload_bytes: int = 1_000_000,
    timeout_seconds: int = 25,
    download_base: str = "https://speed.cloudflare.com/__down",
    upload_base: str = "https://speed.cloudflare.com/__up",
    selector_tag: str = "PROXY",
) -> list[SpeedResult]:
    del concurrency  # A single selector cannot safely be switched concurrently.
    max_nodes = max(0, int(max_nodes))
    download_bytes = max(1, int(download_bytes))
    upload_bytes = max(1, int(upload_bytes))
    outbounds = [outbound for outbound in outbounds if isinstance(outbound, dict) and outbound.get("tag")][:max_nodes]
    if not outbounds:
        return []

    results: list[SpeedResult] = []
    async with SingBoxRunner(singbox_path, clash_api_host, clash_api_port) as runner:
        api = await runner.start(outbounds, enable_selector=True, selector_tag=selector_tag)
        proxy_url = "http://127.0.0.1:10809"
        for outbound in outbounds:
            tag = str(outbound["tag"])
            try:
                if not await runner.select_outbound(api, selector_tag, tag):
                    continue
                await asyncio.sleep(0.15)
                timeout = httpx.Timeout(timeout_seconds)
                async with httpx.AsyncClient(proxy=proxy_url, timeout=timeout, follow_redirects=True) as client:
                    dl_bytes, dl_elapsed = await _stream_download(client, f"{download_base}?bytes={download_bytes}")
                    ul_bytes, ul_elapsed = await _upload(client, f"{upload_base}?bytes={upload_bytes}", upload_bytes)
            except (httpx.HTTPError, OSError, ValueError):
                continue

            result = SpeedResult(
                tag=tag,
                label=labels_by_tag.get(tag, tag),
                download_bps=dl_bytes / max(0.001, dl_elapsed),
                upload_bps=ul_bytes / max(0.001, ul_elapsed),
            )
            if result.download_bps >= threshold_kib_s * 1024 and result.upload_bps >= threshold_kib_s * 1024:
                results.append(result)

    results.sort(key=lambda result: result.download_bps + result.upload_bps, reverse=True)
    return results


def render_fast_list(results: list[SpeedResult]) -> bytes:
    return ("\n".join(_format_speed_line(result) for result in results).strip() + "\n").encode("utf-8")
