"""User-scoped Firestore functions exposed to the OpenAI model."""

import json
import re
from typing import Any

from google.cloud import firestore

_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
_MAX_VALUE_JSON_LENGTH = 20_000

FIRESTORE_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "get_user_data",
        "description": (
            "Read one document from the current user's private Firestore data. "
            "Use the key only; the user path is applied by the application."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Document key using letters, digits, _ or -.",
                }
            },
            "required": ["key"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "list_user_data",
        "description": (
            "List documents in the current user's private Firestore data."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "description": "Maximum number of documents to return.",
                }
            },
            "required": ["limit"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "type": "function",
        "name": "upsert_user_data",
        "description": (
            "Create or replace one document in the current user's private "
            "Firestore data. Pass the document fields as a JSON object string."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Document key using letters, digits, _ or -.",
                },
                "value_json": {
                    "type": "string",
                    "description": "A JSON-encoded object containing document fields.",
                },
            },
            "required": ["key", "value_json"],
            "additionalProperties": False,
        },
        "strict": True,
    },
]


def _validate_key(key: object) -> str:
    if not isinstance(key, str) or not _KEY_PATTERN.fullmatch(key):
        raise ValueError("key must be 1-100 letters, digits, underscores, or hyphens")
    return key


def _document(db: firestore.Client, user_id: str, key: object) -> Any:
    return db.document(f"users/{user_id}/data/{_validate_key(key)}")


def _json(value: object) -> str:
    return json.dumps(value, default=str, separators=(",", ":"))


def execute_firestore_tool(
    db: firestore.Client,
    user_id: str,
    name: str,
    arguments_json: str,
) -> str:
    """Execute one model tool call within the current user's data collection."""
    arguments = json.loads(arguments_json)
    if not isinstance(arguments, dict):
        raise ValueError("tool arguments must be a JSON object")

    if name == "get_user_data":
        snapshot = _document(db, user_id, arguments.get("key")).get()
        if not snapshot.exists:
            return _json({"found": False})
        return _json({"found": True, "data": snapshot.to_dict() or {}})

    if name == "list_user_data":
        limit = arguments.get("limit")
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
            raise ValueError("limit must be an integer from 1 through 50")
        snapshots = db.collection(f"users/{user_id}/data").limit(limit).stream()
        return _json(
            {
                "documents": [
                    {"key": snapshot.id, "data": snapshot.to_dict() or {}}
                    for snapshot in snapshots
                ]
            }
        )

    if name == "upsert_user_data":
        value_json = arguments.get("value_json")
        if not isinstance(value_json, str) or len(value_json) > _MAX_VALUE_JSON_LENGTH:
            raise ValueError("value_json must be a JSON string of at most 20000 characters")
        value = json.loads(value_json)
        if not isinstance(value, dict):
            raise ValueError("value_json must encode a JSON object")
        _document(db, user_id, arguments.get("key")).set(value)
        return _json({"saved": True})

    raise ValueError(f"unknown tool: {name}")
