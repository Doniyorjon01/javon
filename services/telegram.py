"""
Telegram Bot API client
=======================
A thin async client over httpx for the few Bot API methods we use. One client
serves every store's bot: the token is an argument of each call, never global
state. Created once in main.lifespan (app.state.telegram) and in the worker.

Why not aiogram (named in the plan): aiogram 3 pins pydantic < 2.14 and we run
2.14; and we need ~10 plain HTTPS calls, not a framework. Updates are handled by
services/telegram_updates.py.

Errors: Telegram answers {"ok": false, "error_code", "description", "parameters"}.
TelegramError carries them; callers decide (a group upgraded to a supergroup
answers with parameters.migrate_to_chat_id; a blocked bot answers 403).

Tokens never appear in logs or exception messages: the URL that contains the
token is not logged, and errors keep only the method name.
"""

import logging
from typing import Any

import httpx

from config import settings

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(10.0, connect=5.0)
MAX_FILE_BYTES = 10 * 1024 * 1024  # receipts are photos; refuse anything bigger


class TelegramError(Exception):
    def __init__(self, method: str, code: int, description: str, parameters: dict[str, Any] | None = None):
        super().__init__(f"{method}: {code} {description}")
        self.method = method
        self.code = code
        self.description = description
        self.parameters = parameters or {}

    @property
    def migrate_to_chat_id(self) -> int | None:
        return self.parameters.get("migrate_to_chat_id")

    @property
    def bot_was_blocked_or_kicked(self) -> bool:
        return self.code == 403


class TelegramClient:
    def __init__(self, http: httpx.AsyncClient | None = None, base_url: str | None = None) -> None:
        self._http = http or httpx.AsyncClient(timeout=TIMEOUT)
        self._base = (base_url or settings.TELEGRAM_API_URL).rstrip("/")

    async def aclose(self) -> None:
        await self._http.aclose()

    async def call(self, token: str, method: str, **params: Any) -> Any:
        payload = {key: value for key, value in params.items() if value is not None}
        try:
            response = await self._http.post(f"{self._base}/bot{token}/{method}", json=payload)
        except httpx.HTTPError as exc:
            # Do not chain: the original exception's message contains the URL (the token).
            raise TelegramError(method, 0, f"network error: {type(exc).__name__}") from None
        try:
            body = response.json()
        except ValueError:
            raise TelegramError(method, response.status_code, "not a JSON answer") from None
        if not body.get("ok"):
            raise TelegramError(
                method,
                body.get("error_code", response.status_code),
                body.get("description", ""),
                body.get("parameters"),
            )
        return body["result"]

    # ------------------------------------------------------------ bot setup
    async def get_me(self, token: str) -> dict[str, Any]:
        return await self.call(token, "getMe")

    async def set_webhook(self, token: str, url: str, secret_token: str) -> None:
        await self.call(
            token,
            "setWebhook",
            url=url,
            secret_token=secret_token,
            allowed_updates=["message", "callback_query", "my_chat_member"],
            drop_pending_updates=True,
        )

    async def delete_webhook(self, token: str) -> None:
        await self.call(token, "deleteWebhook")

    async def get_updates(self, token: str, offset: int | None, wait_s: int = 0) -> list[dict[str, Any]]:
        return await self.call(
            token,
            "getUpdates",
            offset=offset,
            timeout=wait_s,
            allowed_updates=["message", "callback_query", "my_chat_member"],
        )

    async def set_menu_button(self, token: str, text: str, url: str) -> None:
        """The button next to the message field that opens the store's Mini App."""
        await self.call(
            token, "setChatMenuButton", menu_button={"type": "web_app", "text": text, "web_app": {"url": url}}
        )

    async def set_commands(
        self, token: str, commands: list[tuple[str, str]], language_code: str | None = None
    ) -> None:
        await self.call(
            token,
            "setMyCommands",
            commands=[{"command": c, "description": d} for c, d in commands],
            language_code=language_code,
        )

    # ------------------------------------------------------------ messages
    async def send_message(
        self, token: str, chat_id: int, text: str, reply_markup: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return await self.call(
            token,
            "sendMessage",
            chat_id=chat_id,
            text=text,
            parse_mode="HTML",
            reply_markup=reply_markup,
            link_preview_options={"is_disabled": True},
        )

    async def copy_message(self, token: str, chat_id: int, from_chat_id: int, message_id: int) -> None:
        await self.call(
            token, "copyMessage", chat_id=chat_id, from_chat_id=from_chat_id, message_id=message_id
        )

    async def edit_reply_markup(self, token: str, chat_id: int, message_id: int) -> None:
        """Remove the buttons of a message (after one was pressed)."""
        await self.call(
            token,
            "editMessageReplyMarkup",
            chat_id=chat_id,
            message_id=message_id,
            reply_markup={"inline_keyboard": []},
        )

    async def answer_callback(
        self, token: str, callback_query_id: str, text: str, alert: bool = False
    ) -> None:
        await self.call(
            token, "answerCallbackQuery", callback_query_id=callback_query_id, text=text, show_alert=alert
        )

    # ------------------------------------------------------------ files
    async def download_file(self, token: str, file_id: str) -> bytes:
        info = await self.call(token, "getFile", file_id=file_id)
        if info.get("file_size", 0) > MAX_FILE_BYTES or "file_path" not in info:
            raise TelegramError("getFile", 413, "file too large or unavailable")
        try:
            response = await self._http.get(f"{self._base}/file/bot{token}/{info['file_path']}")
        except httpx.HTTPError as exc:
            raise TelegramError("downloadFile", 0, f"network error: {type(exc).__name__}") from None
        if response.status_code != 200 or len(response.content) > MAX_FILE_BYTES:
            raise TelegramError("downloadFile", response.status_code, "download failed")
        return response.content


def inline_keyboard(*rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"inline_keyboard": [row for row in rows if row]}


def callback_button(text: str, data: str) -> dict[str, Any]:
    return {"text": text, "callback_data": data}


def url_button(text: str, url: str) -> dict[str, Any] | None:
    """Telegram rejects non-https and localhost links in buttons; skip those."""
    if not url.startswith("https://") or "localhost" in url:
        return None
    return {"text": text, "url": url}


def web_app_button(text: str, url: str) -> dict[str, Any] | None:
    if not url.startswith("https://"):
        return None
    return {"text": text, "web_app": {"url": url}}
