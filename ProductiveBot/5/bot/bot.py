# bot.py
"""
Запуск Telegram-бота через long-polling (aiogram v3).

• Без webhook и aiohttp-сервера — идеально для локальной разработки
  или прода за NAT, где настроить TLS/Webhook затруднительно.
• Работает на macOS/Linux/Windows одинаково.
• Логика бота («роутеры») остаётся прежней, меняется только точка входа.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

# ─── ваши модули с роутерами ───────────────────────────────────────────
from bot.handlers import start, tasks, notion, music, pomodoro, today
from bot.handlers import vocab  # NEW


# ──────────────────── env & logging ────────────────────────────────────
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s: %(message)s",
)
log = logging.getLogger("bot")

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    log.critical("Переменная окружения BOT_TOKEN не установлена.")
    raise SystemExit(1)

# ──────────────────── core & routers ───────────────────────────────────
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)

dp = Dispatcher(storage=MemoryStorage())


def register_routers(dispatcher: Dispatcher) -> None:
    """Подключаем все рутеры бота."""
    dispatcher.include_router(start.router)      # /start
    dispatcher.include_router(notion.router)     # /connect_notion …
    dispatcher.include_router(music.router)      # /add_music
    dispatcher.include_router(pomodoro.router)   # /pomodoro
    dispatcher.include_router(today.router)      # /today
    dispatcher.include_router(tasks.router)      # текст/voice
    
    dispatcher.include_router(vocab.router)



register_routers(dp)

# ──────────────────── graceful shutdown ────────────────────────────────
_STOP_SIGNALS = (signal.SIGINT, signal.SIGTERM)


def _setup_stop_signals(loop: asyncio.AbstractEventLoop) -> None:
    for sig in _STOP_SIGNALS:
        loop.add_signal_handler(sig, lambda: asyncio.create_task(_stop(loop)))


async def _stop(loop: asyncio.AbstractEventLoop) -> None:
    """Корректно завершаем работу бота (Ctrl-C / kill)."""
    log.info("← Shutting down...")
    tasks = [t for t in asyncio.all_tasks(loop) if t is not asyncio.current_task()]
    for task in tasks:
        task.cancel()
    with suppress(asyncio.CancelledError):
        await asyncio.gather(*tasks)
    loop.stop()


# ──────────────────── точка входа ───────────────────────────────────────
async def main() -> None:
    log.info("→ Starting bot in polling mode")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        log.info("→ Bot stopped")


if __name__ == "__main__":
    event_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(event_loop)
    _setup_stop_signals(event_loop)

    try:
        event_loop.run_until_complete(main())
    finally:
        event_loop.close()
