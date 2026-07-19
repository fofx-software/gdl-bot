"""Small client for the Telegram HTTP Bot API."""

from typing import Any

import httpx

TELEGRAM_API_ROOT = "https://api.telegram.org"
TELEGRAM_MESSAGE_LIMIT = 4096


def split_message(text: str) -> list[str]:
    """Split text into Telegram-sized messages, preferring line boundaries."""
    remaining = text.strip()
    chunks: list[str] = []
    while remaining:
        if len(remaining) <= TELEGRAM_MESSAGE_LIMIT:
            chunks.append(remaining)
            break
        split_at = remaining.rfind("\n", 0, TELEGRAM_MESSAGE_LIMIT + 1)
        if split_at <= 0:
            split_at = TELEGRAM_MESSAGE_LIMIT
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    return chunks


class TelegramClient:
    def __init__(
        self,
        bot_token: str,
        *,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._base_url = f"{TELEGRAM_API_ROOT}/bot{bot_token}"
        self._http = http_client or httpx.Client(timeout=30)

    def _post(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self._http.post(f"{self._base_url}/{method}", json=payload)
        response.raise_for_status()
        result = response.json()
        if not result.get("ok"):
            raise RuntimeError(
                f"Telegram {method} failed: {result.get('description', 'unknown error')}"
            )
        return result

    def send_message(self, chat_id: int, text: str) -> None:
        for chunk in split_message(text):
            self._post("sendMessage", {"chat_id": chat_id, "text": chunk})

    def set_webhook(self, url: str, secret_token: str) -> None:
        self._post(
            "setWebhook",
            {
                "url": url,
                "secret_token": secret_token,
                "allowed_updates": ["message"],
            },
        )
