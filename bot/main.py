"""Точка входа MALUNA-бота.

Порядок запуска: конфиг → логи → контент → база → health-сервер → polling.
Контент читается до подключения к Telegram: если файл не проходит
валидацию, бот не стартует (ТЗ, раздел 14).

Планировщика рассылок здесь нет и быть не должно: бот никогда не пишет
первым, единственная отправка — ответ на действие пользователя.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.fsm.storage.base import DefaultKeyBuilder
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from bot.config import Config, ConfigError, load_config
from bot.content.loader import ContentError
from bot.content.store import ContentStore
from bot.db.database import Database
from bot.db.repo import Repository
from bot.handlers import about, admin, astro, fallback, guide, prediction, ritual, start
from bot.health import start_health_server
from bot.logging_setup import setup_logging
from bot.middlewares.errors import ErrorMiddleware
from bot.services.subscription import SubscriptionChecker

logger = logging.getLogger(__name__)

# Состояние диалога живёт не дольше получаса — дальше сценарий начинается заново.
FSM_TTL_SECONDS = 30 * 60


def build_storage(config: Config):
    """Redis, если задан REDIS_URL, иначе память процесса."""
    if not config.redis_url:
        return MemoryStorage()

    from aiogram.fsm.storage.redis import RedisStorage  # локальный импорт: зависимость опциональна

    logger.info("fsm_storage_redis")
    return RedisStorage.from_url(
        config.redis_url,
        key_builder=DefaultKeyBuilder(with_destiny=True),
        state_ttl=FSM_TTL_SECONDS,
        data_ttl=FSM_TTL_SECONDS,
    )


def build_dispatcher(
    config: Config, content_store: ContentStore, repo: Repository
) -> Dispatcher:
    dispatcher = Dispatcher(storage=build_storage(config))

    # Зависимости приезжают в хендлеры аргументами.
    dispatcher["config"] = config
    dispatcher["content_store"] = content_store
    dispatcher["repo"] = repo
    dispatcher["subscription"] = SubscriptionChecker(config.channel_username)

    error_middleware = ErrorMiddleware(content_store)
    dispatcher.message.middleware(error_middleware)
    dispatcher.callback_query.middleware(error_middleware)

    dispatcher.include_router(start.router)
    dispatcher.include_router(admin.router)
    dispatcher.include_router(prediction.router)
    dispatcher.include_router(ritual.router)
    dispatcher.include_router(astro.router)
    dispatcher.include_router(guide.router)
    dispatcher.include_router(about.router)
    # Последним: ловит свободный текст и кнопки из устаревших сообщений.
    dispatcher.include_router(fallback.router)
    return dispatcher


async def run() -> None:
    config = load_config()
    setup_logging(config.log_level)

    content_store = ContentStore(config.content_dir)

    db = Database(config.db_path)
    await db.connect()
    repo = Repository(db)

    bot = Bot(token=config.bot_token, default=DefaultBotProperties(parse_mode=None))
    dispatcher = build_dispatcher(config, content_store, repo)

    health_runner = await start_health_server(content_store, db, config.health_port)

    try:
        await bot.set_my_commands(
            [
                BotCommand(command="start", description="MALUNA"),
                BotCommand(command="delete", description="delete my data"),
            ]
        )
        # drop_pending_updates: после простоя не отвечаем на старые нажатия.
        await dispatcher.start_polling(bot, drop_pending_updates=True)
    finally:
        await health_runner.cleanup()
        await db.close()
        await bot.session.close()
        logger.info("bot_stopped")


def main() -> None:
    try:
        asyncio.run(run())
    except TelegramUnauthorizedError as exc:
        logging.getLogger(__name__).error("bad_token")
        print(
            "Не удалось запустить бота: Telegram не принял токен.\n"
            "Проверь BOT_TOKEN в файле .env — его выдаёт @BotFather.",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    except (ConfigError, ContentError) as exc:
        # Понятная строка вместо стека: чаще всего это опечатка в .env или в контенте.
        logging.getLogger(__name__).error("startup_failed", extra={"reason": str(exc)})
        print(f"Не удалось запустить бота: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
