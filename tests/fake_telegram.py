"""
A fake Telegram Bot API for tests
=================================
The real TelegramClient talks HTTP to this in-process transport, so the request
building, JSON handling and error paths are the production code. Every call is
recorded; answers and failures can be scripted per method.

    fake = FakeTelegram()
    fake.fail("sendMessage", 403, "Forbidden: bot was kicked")
    ...
    assert fake.sent_texts(chat_id=-100) == [...]
"""

import json
from dataclasses import dataclass, field
from typing import Any

import httpx

from services.telegram import TelegramClient

BOT_ID = 777000111
BOT_USERNAME = "varaq_test_bot"
# Looks like a real token (the API validates the shape before calling Telegram).
TOKEN = "777000111:AAH-fake_token_for_tests_only_abcdefghij"


@dataclass
class Call:
    token: str
    method: str
    params: dict[str, Any]


@dataclass
class FakeTelegram:
    calls: list[Call] = field(default_factory=list)
    files: dict[str, bytes] = field(default_factory=dict)  # file_id -> content
    me: dict[str, Any] = field(
        default_factory=lambda: {
            "id": BOT_ID,
            "is_bot": True,
            "first_name": "Varaq",
            "username": BOT_USERNAME,
        }
    )
    _failures: dict[str, tuple[int, str, dict[str, Any] | None]] = field(default_factory=dict)
    _message_id: int = 0

    def __post_init__(self) -> None:
        self.client = TelegramClient(
            http=httpx.AsyncClient(transport=httpx.MockTransport(self._handle)), base_url="https://tg.test"
        )

    def fail(
        self, method: str, code: int, description: str, parameters: dict[str, Any] | None = None
    ) -> None:
        self._failures[method] = (code, description, parameters)

    def heal(self, method: str) -> None:
        self._failures.pop(method, None)

    def methods(self) -> list[str]:
        return [call.method for call in self.calls]

    def sent(self, chat_id: int | None = None) -> list[Call]:
        return [
            c
            for c in self.calls
            if c.method == "sendMessage" and (chat_id is None or c.params["chat_id"] == chat_id)
        ]

    def sent_texts(self, chat_id: int | None = None) -> list[str]:
        return [c.params["text"] for c in self.sent(chat_id)]

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.startswith("/file/bot"):
            file_path = path.split("/", 3)[3]
            content = self.files.get(file_path)
            return httpx.Response(200 if content is not None else 404, content=content or b"")
        token, method = path.removeprefix("/bot").split("/", 1)
        params = json.loads(request.content or b"{}")
        self.calls.append(Call(token, method, params))
        if method in self._failures:
            code, description, parameters = self._failures[method]
            body: dict[str, Any] = {"ok": False, "error_code": code, "description": description}
            if parameters:
                body["parameters"] = parameters
            return httpx.Response(code, json=body)
        return httpx.Response(200, json={"ok": True, "result": self._result(method, params)})

    def _result(self, method: str, params: dict[str, Any]) -> Any:
        if method == "getMe":
            return self.me
        if method in ("sendMessage", "copyMessage"):
            self._message_id += 1
            return {"message_id": self._message_id, "chat": {"id": params.get("chat_id")}}
        if method == "getFile":
            file_id = params["file_id"]
            if file_id not in self.files:
                return {"file_id": file_id}
            return {"file_id": file_id, "file_size": len(self.files[file_id]), "file_path": file_id}
        if method == "getUpdates":
            return []
        return True
