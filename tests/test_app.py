from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from app.main import app, get_db


def test_health() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_checks_firestore() -> None:
    db = MagicMock()
    db.collection.return_value.limit.return_value.stream.return_value = iter(())
    app.dependency_overrides[get_db] = lambda: db

    try:
        response = TestClient(app).get("/ready")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "firestore": "connected"}
    db.collection.assert_called_once_with("_healthchecks")
