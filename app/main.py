"""HTTP entry point for the bot management service."""

from functools import lru_cache

from fastapi import Depends, FastAPI, HTTPException, status
from google.api_core.exceptions import GoogleAPIError
from google.cloud import firestore

app = FastAPI(
    title="GDL Bot Manager",
    description="Minimal API scaffold for managing OpenAI bots.",
    version="0.1.0",
)


@lru_cache
def get_db() -> firestore.Client:
    """Create one Firestore client using Application Default Credentials."""
    return firestore.Client()


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
