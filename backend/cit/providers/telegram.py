"""Telegram Bot API adapter (https://core.telegram.org/bots/api).

Inbound: `getUpdates` polling. A bot only receives messages from chats it was
added to (group messages also require privacy mode off or admin rights;
channel posts require the bot to be a channel admin). No user-account
(MTProto) access is used anywhere.

Outbound alerts (Phase 5) will reuse the same client via `sendMessage`.
The bot token appears in the URL path, so it is registered for redaction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from cit.providers.http import ProviderClient, ProviderError, ProviderPolicy

SOURCE = "telegram_bot"


def policy(token: str, rate_per_minute: float = 20) -> ProviderPolicy:
    return ProviderPolicy(SOURCE, f"https://api.telegram.org/bot{token}", rate_per_minute, None, redact=(token,))


@dataclass(frozen=True)
class TgMessage:
    update_id: int
    chat_id: str
    chat_type: str
    chat_title: str | None
    chat_username: str | None
    message_id: int
    date: datetime
    text: str
    urls: tuple[str, ...]
    is_forwarded: bool
    forwarded_from: str | None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def link(self) -> str | None:
        return f"https://t.me/{self.chat_username}/{self.message_id}" if self.chat_username else None


def _forward_origin(m: dict[str, Any]) -> tuple[bool, str | None]:
    origin = m.get("forward_origin")
    if isinstance(origin, dict):
        chat = origin.get("chat") or origin.get("sender_chat") or {}
        if isinstance(chat, dict) and (chat.get("username") or chat.get("title")):
            return True, str(chat.get("username") or chat.get("title"))
        # Forwarded from a private user: never store their identity.
        return True, "user (hidden)"
    fchat = m.get("forward_from_chat")
    if isinstance(fchat, dict):
        return True, str(fchat.get("username") or fchat.get("title") or "chat")
    if m.get("forward_from") or m.get("forward_sender_name"):
        return True, "user (hidden)"
    return False, None


def parse_updates(payload: Any) -> tuple[list[TgMessage], int | None]:
    """Return (messages, highest update_id). Edits and non-message updates are skipped."""
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        raise ProviderError(SOURCE, f"getUpdates not ok: {str(payload)[:200]}")
    out: list[TgMessage] = []
    max_id: int | None = None
    for u in payload.get("result") or []:
        if not isinstance(u, dict) or not isinstance(u.get("update_id"), int):
            continue
        max_id = u["update_id"] if max_id is None else max(max_id, u["update_id"])
        m = u.get("message") or u.get("channel_post")
        if not isinstance(m, dict):
            continue
        chat = m.get("chat") or {}
        if not isinstance(chat, dict) or "id" not in chat or not isinstance(m.get("date"), int):
            continue
        text = m.get("text") or m.get("caption") or ""
        entities = (m.get("entities") or []) + (m.get("caption_entities") or [])
        urls = tuple(e["url"] for e in entities if isinstance(e, dict) and isinstance(e.get("url"), str))
        fwd, fwd_from = _forward_origin(m)
        out.append(
            TgMessage(
                update_id=u["update_id"],
                chat_id=str(chat["id"]),
                chat_type=str(chat.get("type", "")),
                chat_title=chat.get("title"),
                chat_username=chat.get("username"),
                message_id=int(m.get("message_id", 0)),
                date=datetime.fromtimestamp(m["date"], tz=UTC),
                text=str(text),
                urls=urls,
                is_forwarded=fwd,
                forwarded_from=fwd_from,
            )
        )
    return out, max_id


class TelegramBot:
    def __init__(self, client: ProviderClient):
        self.client = client

    async def get_updates(self, offset: int | None, limit: int = 100) -> tuple[list[TgMessage], int | None]:
        params: dict[str, Any] = {"timeout": 0, "limit": limit, "allowed_updates": '["message","channel_post"]'}
        if offset is not None:
            params["offset"] = offset
        return parse_updates(await self.client.get_json("/getUpdates", params, endpoint="getUpdates"))

    async def send_message(self, chat_id: str, text: str) -> Any:
        return await self.client.post_json(
            "/sendMessage",
            {
                "chat_id": chat_id,
                "text": text[:4096],
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            endpoint="sendMessage",
        )
