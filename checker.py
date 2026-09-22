from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import logging

import yaml

from singbox_runner import SingBoxRunner
from subs import Node, fetch_text, node_from_clash_proxy, node_from_share_link, parse_subscription_payload

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CheckResult:
    healthy_links: list[str]
    healthy_clash_proxies: list[dict]


def _has_invalid_ws_path(value: object) -> bool:
    if isinstance(value, dict):
        transport = value.get("transport")
        if isinstance(transport, dict) and transport.get("type") in {"ws", "websocket"}:
            path = transport.get("path")
            if isinstance(path, str):
                index = 0
                while index < len(path):
                    if path[index] == "%":
                        if index + 2 >= len(path) or any(char not in "0123456789abcdefABCDEF" for char in path[index + 1:index + 3]):
                            return True
                        index += 2
                    index += 1
        return any(_has_invalid_ws_path(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_has_invalid_ws_path(item) for item in value)
    return False


def _sanitize_outbound(value: object) -> object:
    if isinstance(value, dict):
        result = {key: _sanitize_outbound(item) for key, item in value.items()}
        string_fields = {"password", "uuid", "id", "shortId", "short_id", "alterId", "flow", "method", "host", "path", "server_name"}
        for key in string_fields:
            if key in result and result[key] is not None and not isinstance(result[key], str):
                result[key] = str(result[key])
        return result
    if isinstance(value, list):
        return [_sanitize_outbound(item) for item in value]
    return value


async def collect_nodes(urls: list[str]) -> list[Node]:
    nodes: list[Node] = []
    seen_tags: set[str] = set()
    for url in urls:
        try:
            text = await fetch_text(url)
            links, proxies = parse_subscription_payload(text)
        except Exception as exc:
            logger.warning("Could not read subscription %s: %s", url, exc)
            continue

        for link in links:
            try:
                node = node_from_share_link(link)
            except (TypeError, ValueError, KeyError) as exc:
                logger.debug("Skipping invalid share link: %s", exc)
                continue
            if node.tag not in seen_tags:
                seen_tags.add(node.tag)
                nodes.append(node)

        for proxy in proxies:
            try:
                node = node_from_clash_proxy(proxy)
            except (TypeError, ValueError, KeyError) as exc:
                logger.debug("Skipping invalid Clash proxy: %s", exc)
                continue
            if node and node.tag not in seen_tags:
                seen_tags.add(node.tag)
                nodes.append(node)
    return nodes


async def check_nodes(
    singbox_path: str,
    clash_api_host: str,
    clash_api_port: int,
    test_url: str,
    timeout_ms: int,
    max_concurrency: int,
    nodes: list[Node],
) -> CheckResult:
    prepared: list[Node] = []
    for node in nodes:
        if not isinstance(node.outbound, dict) or _has_invalid_ws_path(node.outbound):
            logger.info("Skipping malformed outbound %s", node.tag)
            continue
        outbound = _sanitize_outbound(deepcopy(node.outbound))
        if not isinstance(outbound, dict) or not outbound.get("tag"):
            continue
        prepared.append(Node(node.tag, outbound, node.export_link, node.export_clash_proxy))

    if not prepared:
        return CheckResult([], [])

    semaphore = asyncio.Semaphore(max(1, int(max_concurrency)))
    healthy_links: list[str] = []
    healthy_clash: list[dict] = []

    async with SingBoxRunner(singbox_path, clash_api_host, clash_api_port) as runner:
        api = await runner.start([node.outbound for node in prepared])

        async def check_one(node: Node) -> None:
            async with semaphore:
                try:
                    delay = await runner.delay_test(api, node.tag, test_url, int(timeout_ms))
                except Exception as exc:
                    logger.debug("Delay test failed for %s: %s", node.tag, exc)
                    return
                if delay is None:
                    return
                if node.export_link:
                    healthy_links.append(node.export_link)
                if node.export_clash_proxy:
                    healthy_clash.append(node.export_clash_proxy)

        await asyncio.gather(*(check_one(node) for node in prepared))

    return CheckResult(healthy_links, healthy_clash)


def render_outputs(result: CheckResult) -> tuple[bytes, bytes]:
    txt = "\n".join(result.healthy_links).strip()
    txt_bytes = (txt + "\n" if txt else "").encode("utf-8")

    proxies = [proxy for proxy in result.healthy_clash_proxies if isinstance(proxy, dict)]
    by_protocol: dict[str, list[str]] = {}
    all_names: list[str] = []
    for proxy in proxies:
        name = str(proxy.get("name") or "").strip()
        if not name:
            continue
        all_names.append(name)
        protocol = str(proxy.get("type") or "unknown").lower()
        by_protocol.setdefault(protocol, []).append(name)

    proxy_groups: list[dict] = []
    if all_names:
        proxy_groups.append({"name": "AUTO", "type": "url-test", "url": "https://cp.cloudflare.com/generate_204", "interval": 300, "proxies": all_names})
    for protocol, names in sorted(by_protocol.items()):
        proxy_groups.append({"name": f"PROTO-{protocol.upper()}", "type": "url-test", "url": "https://cp.cloudflare.com/generate_204", "interval": 300, "proxies": names})

    yaml_object = {
        "port": 7890,
        "socks-port": 7891,
        "allow-lan": True,
        "mode": "Rule",
        "log-level": "silent",
        "proxies": proxies,
        "proxy-groups": proxy_groups,
        "rules": ["MATCH,AUTO"] if all_names else ["MATCH,DIRECT"],
    }
    return txt_bytes, yaml.safe_dump(yaml_object, allow_unicode=True, sort_keys=False).encode("utf-8")


def build_commit_message(prefix: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    return f"{prefix} {timestamp}"
