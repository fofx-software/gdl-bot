from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import (
    app,
    get_db,
    get_openai_client,
    get_telegram_client,
)
from app.telegram import TELEGRAM_MESSAGE_LIMIT, TelegramClient, split_message


def settings() -> Settings:
    return Settings(
        openai_api_key="test",
        openai_model="gpt-test",
        telegram_bot_token="token",
        telegram_webhook_secret="secret-123",
    )


def test_split_message_respects_telegram_limit() -> None:
    chunks = split_message("a" * (TELEGRAM_MESSAGE_LIMIT + 10))

    assert [len(chunk) for chunk in chunks] == [TELEGRAM_MESSAGE_LIMIT, 10]


def test_telegram_client_sends_message() -> None:
    http = MagicMock()
    http.post.return_value.json.return_value = {"ok": True}
    client = TelegramClient("token", http_client=http)

    client.send_message(123, "Hello")

    http.post.assert_called_once_with(
        "https://api.telegram.org/bottoken/sendMessage",
        json={"chat_id": 123, "text": "Hello"},
    )


def test_webhook_rejects_wrong_secret() -> None:
    app.dependency_overrides[get_settings] = settings
    try:
        response = TestClient(app).post(
            "/telegram",
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
            json={"update_id": 1},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401


def test_webhook_handles_text_message(monkeypatch) -> None:
    db = MagicMock()
    db.document.return_value.get.return_value.exists = False
    openai_client = MagicMock()
    telegram_client = MagicMock()
    bot_response = MagicMock(output_text="Bot reply")
    handle = MagicMock(return_value=bot_response)
    monkeypatch.setattr("app.main.handle_request", handle)
    app.dependency_overrides.update(
        {
            get_settings: settings,
            get_db: lambda: db,
            get_openai_client: lambda: openai_client,
            get_telegram_client: lambda: telegram_client,
        }
    )
    try:
        response = TestClient(app).post(
            "/telegram",
            headers={"X-Telegram-Bot-Api-Secret-Token": "secret-123"},
            json={
                "update_id": 42,
                "message": {
                    "text": "Hello bot",
                    "from": {"id": 99},
                    "chat": {"id": 123},
                },
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.json() == {"status": "ok"}
    handle.assert_called_once_with(
        openai_client,
        db,
        "99",
        "gpt-test",
        "Hello bot",
    )
    telegram_client.send_message.assert_called_once_with(123, "Bot reply")
    db.document.return_value.set.assert_called_once()
