"""Health-check эндпоинт для мониторинга: GET /health."""

from __future__ import annotations

import logging

from aiohttp import web

from bot.content.store import ContentStore
from bot.db.database import Database

logger = logging.getLogger(__name__)


def build_app(content_store: ContentStore, db: Database) -> web.Application:
    async def health(_: web.Request) -> web.Response:
        db_ok = await db.healthy()
        snapshot = content_store.current
        payload = {
            "status": "ok" if db_ok else "degraded",
            "database": "ok" if db_ok else "error",
            "content": snapshot.stats(),
        }
        return web.json_response(payload, status=200 if db_ok else 503)

    app = web.Application()
    app.router.add_get("/health", health)
    return app


async def start_health_server(
    content_store: ContentStore, db: Database, port: int
) -> web.AppRunner:
    runner = web.AppRunner(build_app(content_store, db))
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=port)
    await site.start()
    logger.info("health_server_started", extra={"port": port})
    return runner
