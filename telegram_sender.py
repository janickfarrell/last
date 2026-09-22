from __future__ import annotations

import httpx


def _telegram_url(token: str, method: str) -> str:
    base = "https" + "://api.telegram.org"
    return f"{base}/bot{token}/{method}"


async def send_message(token: str, chat_id: int, text: str) -> None:
    if not token or not chat_id:
        return
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            _telegram_url(token, "sendMessage"),
            data={"chat_id": str(chat_id), "text": text},
        )
        response.raise_for_status()


async def send_document(
    token: str,
    chat_id: int,
    filename: str,
    content: bytes,
    caption: str | None = None,
) -> None:
    if not token or not chat_id:
        return
    data = {"chat_id": str(chat_id)}
    if caption:
        data["caption"] = caption
    files = {"document": (filename, content)}
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            _telegram_url(token, "sendDocument"),
            data=data,
            files=files,
        )
        response.raise_for_status()
