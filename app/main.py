"""HTTP entry point for the bot management service."""

import secrets
from functools import lru_cache
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, status
from google.api_core.exceptions import GoogleAPIError
from google.cloud import firestore
from openai import OpenAI

from app.bot import handle_request
from app.config import Settings, get_settings
from app.telegram import TelegramClient

app = FastAPI(
    title="GDL Bot Manager",
    description="Minimal API scaffold for managing OpenAI bots.",
    version="0.1.0",
)


@lru_cache
def get_db() -> firestore.Client:
    """Create one Firestore client using Application Default Credentials."""
    return firestore.Client()


@lru_cache
def get_openai_client() -> OpenAI:
    settings = get_settings()
    return OpenAI(api_key=settings.openai_api_key)


@lru_cache
def get_telegram_client() -> TelegramClient:
    settings = get_settings()
    return TelegramClient(settings.telegram_bot_token)


def verify_telegram_secret(
    telegram_secret: str | None = Header(
        default=None,
        alias="X-Telegram-Bot-Api-Secret-Token",
    ),
    settings: Settings = Depends(get_settings),
) -> Settings:
    """Authenticate a Telegram webhook before creating external clients."""
    if telegram_secret is None or not secrets.compare_digest(
        telegram_secret,
        settings.telegram_webhook_secret,
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
    return settings


@app.get("/")
def service_info() -> dict[str, str]:
    return {"service": "gdl-bot", "status": "ok"}


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check that does not depend on external services."""
    return {"status": "ok"}


@app.get("/ready")
def readiness(db: firestore.Client = Depends(get_db)) -> dict[str, str]:
    """Verify that the service can authenticate to and query Firestore."""
    try:
        list(db.collection("_healthchecks").limit(1).stream())
    except GoogleAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Firestore is unavailable",
        ) from exc
    return {"status": "ready", "firestore": "connected"}


@app.post("/telegram")
def telegram_webhook(
    update: dict[str, Any],
    settings: Settings = Depends(verify_telegram_secret),
    db: firestore.Client = Depends(get_db),
    openai_client: OpenAI = Depends(get_openai_client),
    telegram_client: TelegramClient = Depends(get_telegram_client),
) -> dict[str, str]:
    """Handle a Telegram text-message update."""
    update_id = update.get("update_id")
    message = update.get("message")
    if not isinstance(update_id, int) or not isinstance(message, dict):
        return {"status": "ignored"}
    text = message.get("text")
    sender = message.get("from")
    chat = message.get("chat")
    if (
        not isinstance(text, str)
        or not text.strip()
        or not isinstance(sender, dict)
        or not isinstance(sender.get("id"), int)
        or not isinstance(chat, dict)
        or not isinstance(chat.get("id"), int)
    ):
        return {"status": "ignored"}

    update_ref = db.document(f"telegram_updates/{update_id}")
    if update_ref.get().exists:
        return {"status": "duplicate"}

    response = handle_request(
        openai_client,
        db,
        str(sender["id"]),
        settings.openai_model,
        text,
    )
    telegram_client.send_message(chat["id"], response.output_text)
    update_ref.set(
        {
            "processed_at": firestore.SERVER_TIMESTAMP,
            "telegram_user_id": str(sender["id"]),
        }
    )
    return {"status": "ok"}
