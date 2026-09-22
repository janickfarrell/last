from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import yaml

from check_host import Endpoint, reachable_from_country_tcp
from checker import CheckResult, check_nodes, collect_nodes, render_outputs
from config import load_settings
from geo import GeoResolver
from speed_test import find_fast_nodes, render_fast_list
from subs import node_from_clash_proxy, node_from_share_link
from telegram_sender import send_document, send_message

logger = logging.getLogger(__name__)


def load_subscription_urls(path: str) -> list[str]:
    file_path = Path(path)
    if not file_path.is_file():
        raise RuntimeError(f"subscriptions file not found: {path}")
    urls: list[str] = []
    for line in file_path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if value and not value.startswith("#"):
            urls.append(value)
    if not urls:
        raise RuntimeError("no subscription URLs were found")
    return urls


def safe_output_path(value: str | None, default: str) -> Path:
    path = Path(value or default)
    if path.is_absolute() or ".." in path.parts:
        raise RuntimeError(f"output path must stay inside the workspace: {path}")
    return path


def write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def endpoint_key(outbound: dict) -> str:
    return "|".join(str(outbound.get(key) or "") for key in ("type", "server", "server_port", "tag"))


def collect_endpoints(result: CheckResult) -> tuple[list[Endpoint], list[tuple[str, str, str]]]:
    endpoints: list[Endpoint] = []
    entries: list[tuple[str, str, str]] = []
    seen_endpoints: set[str] = set()

    for link in result.healthy_links:
        try:
            node = node_from_share_link(link)
            outbound = node.outbound
            host = str(outbound.get("server") or "").strip()
            port = int(outbound.get("server_port"))
        except (TypeError, ValueError, KeyError):
            continue
        if not host or not 1 <= port <= 65535:
            continue
        key = endpoint_key(outbound)
        entries.append((link, host, key))
        if key not in seen_endpoints:
            seen_endpoints.add(key)
            endpoints.append(Endpoint(host=host, port=port, line=link))

    for proxy in result.healthy_clash_proxies:
        try:
            node = node_from_clash_proxy(proxy)
            if not node:
                continue
            outbound = node.outbound
            host = str(outbound.get("server") or "").strip()
            port = int(outbound.get("server_port"))
        except (TypeError, ValueError, KeyError):
            continue
        if not host or not 1 <= port <= 65535:
            continue
        key = endpoint_key(outbound)
        if key not in seen_endpoints:
            seen_endpoints.add(key)
            endpoints.append(Endpoint(host=host, port=port, line=f"{host}:{port}\t{node.tag}"))

    return endpoints, entries


async def group_links_by_country(entries: list[tuple[str, str, str]]) -> dict[str, list[str]]:
    resolver = GeoResolver(float(os.environ.get("GEOIP_MIN_INTERVAL_SECONDS", "1.5")))
    countries = await resolver.countries_for(host for _, host, _ in entries)
    grouped: dict[str, list[str]] = {}
    seen: dict[str, set[str]] = {}
    for link, host, key in entries:
        country = countries.get(host)
        if not country:
            continue
        country_seen = seen.setdefault(country, set())
        if key in country_seen:
            continue
        country_seen.add(key)
        grouped.setdefault(country, []).append(link)
    return grouped


def write_protocol_outputs(result: CheckResult, base_dir: Path, test_url: str) -> None:
    by_protocol: dict[str, list[dict]] = {}
    for proxy in result.healthy_clash_proxies:
        if not isinstance(proxy, dict):
            continue
        protocol = str(proxy.get("type") or "").lower()
        if protocol:
            by_protocol.setdefault(protocol, []).append(proxy)

    for protocol, proxies in by_protocol.items():
        names = [str(proxy.get("name")) for proxy in proxies if proxy.get("name")]
        if not names:
            continue
        document = {
            "port": 7890,
            "socks-port": 7891,
            "allow-lan": True,
            "mode": "Rule",
            "log-level": "silent",
            "proxies": proxies,
            "proxy-groups": [{"name": "AUTO", "type": "url-test", "url": test_url, "interval": 300, "proxies": names}],
            "rules": ["MATCH,AUTO"],
        }
        write_bytes(base_dir / f"healthy_{protocol}.yaml", yaml.safe_dump(document, allow_unicode=True, sort_keys=False).encode("utf-8"))


async def main() -> None:
    settings = load_settings()
    urls = load_subscription_urls(os.environ.get("SUBSCRIPTIONS_FILE", "subscriptions.txt"))
    await send_message(settings.telegram_bot_token, settings.admin_chat_id, "شروع بررسی...")

    nodes = await collect_nodes(urls)
    if not nodes:
        await send_message(settings.telegram_bot_token, settings.admin_chat_id, "هیچ نودی استخراج نشد")
        return

    result = await check_nodes(
        singbox_path=settings.singbox_path,
        clash_api_host=settings.clash_api_host,
        clash_api_port=settings.clash_api_port,
        test_url=settings.test_url,
        timeout_ms=settings.test_timeout_ms,
        max_concurrency=settings.max_concurrency,
        nodes=nodes,
    )
    txt_bytes, yaml_bytes = render_outputs(result)

    txt_path = safe_output_path(settings.github_output_txt_path, "healthy.txt")
    yaml_path = safe_output_path(settings.github_output_yaml_path, "healthy_clash.yaml")
    iran_path = safe_output_path(os.environ.get("GITHUB_OUTPUT_IR_PATH"), "iran_reachable.txt")
    fast_path = safe_output_path(os.environ.get("GITHUB_OUTPUT_FAST_PATH"), "fast_500kbps.txt")
    write_bytes(txt_path, txt_bytes)
    write_bytes(yaml_path, yaml_bytes)
    write_protocol_outputs(result, yaml_path.parent, settings.test_url)

    endpoints, entries = collect_endpoints(result)
    grouped = await group_links_by_country(entries)
    for country, links in grouped.items():
        write_bytes(yaml_path.parent / f"healthy_country_{country}.txt", ("\n".join(links) + "\n").encode("utf-8"))

    country = os.environ.get("CHECK_HOST_COUNTRY", "ir").strip().lower()
    reachable = await reachable_from_country_tcp(
        endpoints,
        country_code=country,
        max_endpoints=int(os.environ.get("CHECK_HOST_MAX_ENDPOINTS", "50")),
        concurrency=int(os.environ.get("CHECK_HOST_CONCURRENCY", "5")),
        poll_wait_seconds=int(os.environ.get("CHECK_HOST_POLL_WAIT_SECONDS", "15")),
    )
    iran_bytes = ("\n".join(endpoint.line for endpoint in reachable) + "\n").encode("utf-8") if reachable else b""
    write_bytes(iran_path, iran_bytes)

    speed_enabled = os.environ.get("SPEED_TEST_ENABLED", "1").strip().lower() not in {"0", "false", "no"}
    fast_bytes = b""
    fast_count = 0
    if speed_enabled:
        speed_outbounds: list[dict] = []
        labels: dict[str, str] = {}
        seen_tags: set[str] = set()
        for node in nodes:
            if node.tag not in seen_tags:
                seen_tags.add(node.tag)
                speed_outbounds.append(node.outbound)
                labels[node.tag] = node.tag
        fast = await find_fast_nodes(
            settings.singbox_path,
            settings.clash_api_host,
            settings.clash_api_port,
            speed_outbounds,
            labels,
            threshold_kib_s=int(os.environ.get("SPEED_TEST_THRESHOLD_KIB_S", "500")),
            max_nodes=int(os.environ.get("SPEED_TEST_MAX_NODES", "10")),
            concurrency=1,
            download_bytes=int(os.environ.get("SPEED_TEST_DOWNLOAD_BYTES", "2000000")),
            upload_bytes=int(os.environ.get("SPEED_TEST_UPLOAD_BYTES", "1000000")),
            timeout_seconds=int(os.environ.get("SPEED_TEST_TIMEOUT_SECONDS", "25")),
        )
        fast_bytes = render_fast_list(fast)
        fast_count = len(fast)
    write_bytes(fast_path, fast_bytes)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    await send_document(settings.telegram_bot_token, settings.admin_chat_id, f"healthy_{timestamp}.txt", txt_bytes, f"Healthy links: {len(result.healthy_links)}")
    await send_document(settings.telegram_bot_token, settings.admin_chat_id, f"healthy_{timestamp}.yaml", yaml_bytes, f"Healthy clash proxies: {len(result.healthy_clash_proxies)}")
    await send_document(settings.telegram_bot_token, settings.admin_chat_id, f"iran_reachable_{timestamp}.txt", iran_bytes, f"Reachable from {country.upper()}: {len(reachable)}")
    await send_document(settings.telegram_bot_token, settings.admin_chat_id, f"fast_{timestamp}.txt", fast_bytes, f"Fast nodes: {fast_count}")
    await send_message(settings.telegram_bot_token, settings.admin_chat_id, f"تمام شد. links={len(result.healthy_links)} proxies={len(result.healthy_clash_proxies)} reachable={len(reachable)} fast={fast_count}")


if __name__ == "__main__":
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(main())
