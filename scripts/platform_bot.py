"""
Set up the platform bot
=======================
    python -m scripts.platform_bot

Run once after deploying (and after changing PUBLIC_API_URL or SECRET_KEY):

  * TELEGRAM_MODE=webhook: Telegram will POST the bot's updates to
    PUBLIC_API_URL/telegram/platform with a secret header derived from SECRET_KEY;
  * TELEGRAM_MODE=polling: the webhook is removed, so scripts/telegram_poll.py can
    read the updates. NEVER run it in polling mode with the production bot's
    token: the server would stop receiving the bot's messages.

Also sets the /start command. Idempotent. The token is never printed.
"""

import asyncio
import sys

from config import settings
from services.platform_bot import ALLOWED_UPDATES, WEBHOOK_PATH, platform_token, webhook_secret
from services.telegram import TelegramClient, TelegramError
from services.telegram_texts import TEXTS
from utils.i18n import Lang


async def setup() -> str:
    token = platform_token()
    if token is None:
        return "TELEGRAM_LOGIN_BOT_TOKEN is not set: nothing to do"
    client = TelegramClient()
    try:
        me = await client.get_me(token)
        if settings.TELEGRAM_MODE == "webhook":
            url = settings.PUBLIC_API_URL.rstrip("/") + WEBHOOK_PATH
            await client.call(
                token, "setWebhook", url=url, secret_token=webhook_secret(), allowed_updates=ALLOWED_UPDATES
            )
            mode = f"webhook -> {url}"
        else:
            await client.delete_webhook(token)
            mode = "polling (run python -m scripts.telegram_poll)"
        for lang in Lang:
            description = TEXTS["cmd_platform_start"][lang]
            await client.set_commands(token, [("start", description)], lang.value)
    finally:
        await client.aclose()
    return f"@{me.get('username')}: {mode}"


def main() -> None:
    try:
        print(asyncio.run(setup()))
    except TelegramError as exc:
        print(f"Telegram refused: {exc.method} {exc.code} {exc.description}")
        sys.exit(1)


if __name__ == "__main__":
    main()
