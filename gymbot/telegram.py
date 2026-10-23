"""Minimal Telegram Bot API client (plain HTTPS, no framework)."""
from __future__ import annotations

import requests


class TelegramError(Exception):
    def __init__(self, description: str, code: int | None = None):
        super().__init__(description)
        self.code = code


def keyboard(rows: list[list[tuple[str, str]]]) -> dict:
    return {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row] for row in rows]}


class Telegram:
    def __init__(self, token: str):
        self.base = f"https://api.telegram.org/bot{token}/"
        self.http = requests.Session()

    def call(self, method: str, wait: int = 0, **params):
        r = self.http.post(self.base + method, json=params, timeout=wait + 15)
        data = r.json()
        if not data.get("ok"):
            raise TelegramError(data.get("description", "unknown error"), data.get("error_code"))
        return data["result"]

    def updates(self, offset: int, timeout: int) -> list[dict]:
        return self.call("getUpdates", wait=timeout, offset=offset, timeout=timeout,
                         allowed_updates=["message", "callback_query"])

    def send(self, chat_id: int, text: str, kb: dict | None = None) -> int:
        p = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if kb:
            p["reply_markup"] = kb
        return self.call("sendMessage", **p)["message_id"]

    def edit(self, chat_id: int, message_id: int, text: str, kb: dict | None = None) -> None:
        p = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"}
        if kb:
            p["reply_markup"] = kb
        self.call("editMessageText", **p)

    def answer(self, query_id: str, text: str = "") -> None:
        self.call("answerCallbackQuery", callback_query_id=query_id, text=text)

    def delete(self, chat_id: int, message_id: int) -> None:
        self.call("deleteMessage", chat_id=chat_id, message_id=message_id)

    def set_commands(self, commands: list[tuple[str, str]]) -> None:
        self.call("setMyCommands", commands=[{"command": c, "description": d} for c, d in commands])
