from __future__ import annotations

from urllib.parse import urlsplit

import aiosqlite

MAX_SUBSCRIPTION_URL_LENGTH = 4096


def normalize_subscription_url(value: str) -> str:
    url = value.strip()
    if len(url) > MAX_SUBSCRIPTION_URL_LENGTH:
        raise ValueError("subscription URL is too long")
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("subscription URL must be an HTTP(S) URL")
    if parsed.username or parsed.password:
        raise ValueError("subscription URL must not contain embedded credentials")
    return url


class Storage:
    def __init__(self, db_path: str = "bot.db") -> None:
        self._db_path = db_path

    async def init(self) -> None:
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute("CREATE TABLE IF NOT EXISTS subscriptions (url TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 1)")
            await db.commit()

    async def add_subscription(self, url: str) -> bool:
        normalized = normalize_subscription_url(url)
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute("INSERT OR IGNORE INTO subscriptions(url, enabled) VALUES(?, 1)", (normalized,))
            await db.commit()
            return cursor.rowcount == 1

    async def remove_subscription(self, url: str) -> bool:
        normalized = normalize_subscription_url(url)
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute("DELETE FROM subscriptions WHERE url = ?", (normalized,))
            await db.commit()
            return cursor.rowcount > 0

    async def list_subscriptions(self) -> list[str]:
        async with aiosqlite.connect(self._db_path) as db:
            cursor = await db.execute("SELECT url FROM subscriptions WHERE enabled = 1 ORDER BY url")
            rows = await cursor.fetchall()
            return [str(row[0]) for row in rows]
