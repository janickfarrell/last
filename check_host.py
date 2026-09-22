from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class CheckHostNode:
    name: str
    country_code: str
    country: str
    city: str


@dataclass(frozen=True)
class Endpoint:
    host: str
    port: int
    line: str

    @property
    def hostport(self) -> str:
        return f"{self.host}:{self.port}"


async def get_nodes(country_code: str) -> list[CheckHostNode]:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get("https://check-host.net/nodes/hosts", headers={"Accept": "application/json"})
        response.raise_for_status()
        data = response.json()

    nodes = data.get("nodes") if isinstance(data, dict) else None
    if not isinstance(nodes, dict):
        return []

    result: list[CheckHostNode] = []
    for name, info in nodes.items():
        if not isinstance(info, dict):
            continue
        location = info.get("location")
        if not isinstance(location, list) or len(location) < 3:
            continue
        if str(location[0]).lower() != country_code.lower():
            continue
        result.append(CheckHostNode(name=str(name), country_code=str(location[0]).lower(), country=str(location[1]), city=str(location[2])))
    return result


async def _start_tcp_check(client: httpx.AsyncClient, endpoint: Endpoint, node_names: list[str]) -> str | None:
    params: list[tuple[str, str]] = [("host", endpoint.hostport), *(('node', name) for name in node_names)]
    try:
        response = await client.get("https://check-host.net/check-tcp", headers={"Accept": "application/json"}, params=params)
        if response.status_code != 200:
            return None
        data = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("ok") != 1 or not data.get("request_id"):
        return None
    return str(data["request_id"])


def _is_success(item: object) -> bool:
    if not isinstance(item, dict) or "error" in item or "time" not in item:
        return False
    return isinstance(item.get("time"), (int, float))


async def _poll_result(client: httpx.AsyncClient, request_id: str, node_names: list[str], max_wait_seconds: int) -> bool:
    deadline = asyncio.get_running_loop().time() + max(1, int(max_wait_seconds))
    while asyncio.get_running_loop().time() < deadline:
        try:
            response = await client.get(f"{{https://check-host.net/check-result/{request_id}}}", headers={"Accept": "application/json"})
            if response.status_code != 200:
                await asyncio.sleep(0.5)
                continue
            data = response.json()
        except (httpx.HTTPError, ValueError):
            await asyncio.sleep(0.5)
            continue
        if not isinstance(data, dict):
            await asyncio.sleep(0.5)
            continue

        all_done = True
        for node in node_names:
            node_result = data.get(node)
            if node_result is None:
                all_done = False
                continue
            if isinstance(node_result, list) and any(_is_success(item) for item in node_result):
                return True
        if all_done:
            return False
        await asyncio.sleep(0.5)
    return False


async def reachable_from_country_tcp(
    endpoints: list[Endpoint],
    country_code: str = "ir",
    max_endpoints: int = 50,
    concurrency: int = 5,
    poll_wait_seconds: int = 15,
) -> list[Endpoint]:
    nodes = await get_nodes(country_code)
    node_names = [node.name for node in nodes]
    if not node_names:
        return []

    selected = list(endpoints)[: max(0, int(max_endpoints))]
    semaphore = asyncio.Semaphore(max(1, int(concurrency)))
    reachable: list[Endpoint] = []

    async with httpx.AsyncClient(timeout=30) as client:
        async def check_one(endpoint: Endpoint) -> None:
            async with semaphore:
                request_id = await _start_tcp_check(client, endpoint, node_names)
                if request_id and await _poll_result(client, request_id, node_names, poll_wait_seconds):
                    reachable.append(endpoint)

        await asyncio.gather(*(check_one(endpoint) for endpoint in selected))
    return reachable
