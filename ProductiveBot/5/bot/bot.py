# bot/webhook_runner.py
import logging, os
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.webhook.aiohttp_server import (
    SimpleRequestHandler, setup_application
)
from dotenv import load_dotenv
from aiogram.fsm.storage.memory import MemoryStorage
from bot.handlers import start, tasks, notion, music, pomodoro, today

# ───────────────────── env & logging ─────────────────────
load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bot")

BOT_TOKEN     = os.getenv("BOT_TOKEN")
BASE_WEBHOOK  = "https://b46d7eb57a75.ngrok-free.app" #os.getenv("WEBHOOK_URL")          # e.g. https://xyz.ngrok-free.app
print("BASE_WEBHOOK: ", BASE_WEBHOOK)

WEBHOOK_PATH  = "/bot/webhook"
WEBHOOK_FULL  = BASE_WEBHOOK.rstrip("/") + WEBHOOK_PATH  # full URL

if not BOT_TOKEN or not BASE_WEBHOOK:
    raise RuntimeError("BOT_TOKEN and WEBHOOK_URL must be set")

# ───────────────────── aiogram core ──────────────────────
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)
dp = Dispatcher()

# ────────── register your routers here ──────────
def register_routers(dp: Dispatcher) -> None:
    """Register all routers."""
    dp.include_router(start.router)  # /start
    dp.include_router(notion.router)  # /connect_notion, /connect_notion_table, /connect_notion_category_table
    dp.include_router(music.router)  # /add_music
    dp.include_router(pomodoro.router)  # /pomodoro
    dp.include_router(today.router)  # /today
    dp.include_router(tasks.router)  # text  and voice messages

register_routers(dp)

# ─────────────────── aiohttp app ─────────────────────────
async def on_startup(app: web.Application):
    log.info("→ Setting webhook %s", WEBHOOK_FULL)
    await bot.set_webhook(WEBHOOK_FULL)

async def on_shutdown(app: web.Application):
    log.info("← Deleting webhook")
    await bot.delete_webhook()
    await dp.storage.close()
    await bot.session.close()

app = web.Application()
app.on_startup.append(on_startup)
app.on_shutdown.append(on_shutdown)

SimpleRequestHandler(
    dispatcher=dp,
    bot=bot
).register(app, path=WEBHOOK_PATH)

setup_application(app, dp, bot=bot)     # graceful task cancellation

# ─────────────────────── runner ──────────────────────────
if __name__ == "__main__":
    log.info("Bot webhook listening on 0.0.0.0:8081")
    web.run_app(app, host="0.0.0.0", port=8081)
