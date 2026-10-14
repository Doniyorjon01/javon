"""
Telegram updates by polling (local development)
===============================================
    python -m scripts.telegram_poll

On a laptop Telegram cannot reach a webhook. With TELEGRAM_MODE=polling (the
default outside production), connecting a bot removes its webhook, and this
script asks Telegram for every active bot's new updates and hands them to the
same handler the webhook uses (services/telegram_updates.py). Stop with Ctrl+C.

Not for production: there TELEGRAM_MODE=webhook and Telegram calls the API.
"""

import asyncio
import contextlib
import logging
import signal

from config import settings
from database import db_telegram, db_tenant
from database.config import SessionLocal, bind_tenant, engine
from services.storage import create_storage
from services.telegram import TelegramClient, TelegramError
from services.telegram_updates import BotContext, BotInfo, StoreInfo, handle_update
from utils.log import configure_logging

logger = logging.getLogger("javon.telegram_poll")

ROUND_PAUSE_S = 1.0


async def poll_once(client: TelegramClient, private_storage: object) -> int:
    """One round over all active bots. Returns how many updates were handled."""
    async with SessionLocal() as db:
        bots = list(await db.scalars(db_telegram.get_polling_bots()))
    handled = 0
    for bot in bots:
        info, tenant_id, offset = BotInfo.of(bot), bot.tenant_id, bot.polling_offset
        try:
            updates = await client.get_updates(info.token, offset=offset)
        except TelegramError as exc:
            logger.warning("getUpdates failed", extra={"tenant_id": tenant_id, "code": exc.code})
            if exc.code == 401:
                async with SessionLocal() as db:
                    await db_telegram.mark_broken(db, info.id, exc.description)
            continue
        for update in updates:
            async with SessionLocal() as db:
                await bind_tenant(db, tenant_id)
                tenant = await db_tenant.get_tenant(db, tenant_id)
                ctx = BotContext(db, client, private_storage, info, StoreInfo.of(tenant))  # type: ignore[arg-type]
                try:
                    await handle_update(ctx, update)
                except Exception:
                    logger.exception("Telegram update failed", extra={"tenant_id": tenant_id})
                await db_telegram.save_polling_offset(db, info.id, int(update["update_id"]) + 1)
            handled += 1
    return handled


async def main() -> None:
    configure_logging(settings.LOG_LEVEL)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    client = TelegramClient()
    private_storage = create_storage(settings.STORAGE_PRIVATE_BUCKET)
    logger.info("Polling Telegram for all active store bots")
    try:
        while not stop.is_set():
            try:
                await poll_once(client, private_storage)
            except Exception:
                logger.exception("Polling round failed")
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=ROUND_PAUSE_S)
    finally:
        await client.aclose()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
