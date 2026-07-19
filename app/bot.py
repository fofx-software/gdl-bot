"""Centralized OpenAI requests and user-scoped topic routing."""

import re
from typing import Any, Literal

from google.cloud import firestore
from openai import OpenAI
from pydantic import BaseModel, Field

BASE_INSTRUCTIONS = ""
BOT_CONFIG_COLLECTION = "config"
BOT_CONFIG_DOCUMENT = "bot"
CONVERSATION_STATE_DOCUMENT = "conversation"
TOPIC_ROUTER_PROMPT = """Classify the user's message for conversation routing.
Use `continue` for follow-ups, short questions, pronouns, or messages that rely
on the active topic. Use `switch` only when an existing topic is clearly named.
Use `create` only for a clearly new subject. Return a concise topic key made of
lowercase words separated by hyphens. Never include a user ID in the topic key.
If the user states a general preference or instruction that should apply to
future requests, return it as a concise, standalone `instruction_update`.
Otherwise return null. Do not save instructions that apply only to this request.
"""


class TopicDecision(BaseModel):
    """Structured routing decision returned by the topic classifier."""

    action: Literal["continue", "switch", "create"]
    topic_key: str = Field(min_length=1, max_length=100)
    confidence: float = Field(ge=0, le=1)
    instruction_update: str | None = Field(default=None, max_length=500)


def _validate_user_id(user_id: str) -> None:
    if not user_id or "/" in user_id:
        raise ValueError("user_id must be a non-empty Firestore path segment")


def build_instructions(db: firestore.Client, user_id: str) -> str:
    """Combine hard-coded instructions with the optional Firestore value."""
    _validate_user_id(user_id)

    snapshot = db.document(
        f"users/{user_id}/{BOT_CONFIG_COLLECTION}/{BOT_CONFIG_DOCUMENT}"
    ).get()
    if not snapshot.exists:
        return BASE_INSTRUCTIONS

    stored_instructions = (snapshot.to_dict() or {}).get("instructions", "")
    if not isinstance(stored_instructions, str):
        raise TypeError("The Firestore instructions entry must be a string")
    return BASE_INSTRUCTIONS + stored_instructions


def create_response(
    client: OpenAI,
    db: firestore.Client,
    user_id: str,
    **request: Any,
) -> Any:
    """Create an OpenAI response with the current combined instructions."""
    request["instructions"] = build_instructions(db, user_id)
    return client.responses.create(**request)


def append_user_instruction(
    db: firestore.Client,
    user_id: str,
    instruction_update: str,
) -> None:
    """Append one new durable instruction to the user's bot configuration."""
    _validate_user_id(user_id)
    new_instruction = instruction_update.strip()
    if not new_instruction:
        return

    config_ref = db.document(
        f"users/{user_id}/{BOT_CONFIG_COLLECTION}/{BOT_CONFIG_DOCUMENT}"
    )
    snapshot = config_ref.get()
    data = snapshot.to_dict() if snapshot.exists else {}
    current = (data or {}).get("instructions", "")
    if not isinstance(current, str):
        raise TypeError("The Firestore instructions entry must be a string")
    if new_instruction in {line.strip() for line in current.splitlines()}:
        return

    updated = (
        f"{current.rstrip()}\n{new_instruction}"
        if current.strip()
        else new_instruction
    )
    config_ref.set(
        {
            "instructions": updated,
            "updated_at": firestore.SERVER_TIMESTAMP,
        },
        merge=True,
    )


def normalize_topic_key(value: str) -> str:
    """Convert a classifier topic value into a safe Firestore document ID."""
    key = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return key[:100] or "general"


def classify_topic(
    client: OpenAI,
    db: firestore.Client,
    user_id: str,
    model: str,
    user_input: str,
    active_topic_key: str | None,
    existing_topic_keys: list[str],
) -> TopicDecision:
    """Classify a message against the user's active and existing topics."""
    routing_context = (
        f"Active topic: {active_topic_key or '(none)'}\n"
        f"Existing topics: {', '.join(existing_topic_keys) or '(none)'}"
    )
    response = client.responses.parse(
        model=model,
        instructions=build_instructions(db, user_id),
        input=[
            {"role": "developer", "content": TOPIC_ROUTER_PROMPT},
            {"role": "developer", "content": routing_context},
            {"role": "user", "content": user_input},
        ],
        text_format=TopicDecision,
        store=False,
    )
    for output in response.output:
        if output.type != "message":
            continue
        for content in output.content:
            if content.type == "output_text" and content.parsed:
                return content.parsed
    raise RuntimeError("The topic router did not return a parsed decision")


def _resolve_topic_key(
    decision: TopicDecision,
    active_topic_key: str | None,
    existing_topic_keys: set[str],
) -> str:
    proposed_key = normalize_topic_key(decision.topic_key)
    if decision.action == "continue" and active_topic_key:
        return active_topic_key
    if decision.action == "switch" and proposed_key in existing_topic_keys:
        return proposed_key
    if decision.action == "create":
        return proposed_key
    return active_topic_key or proposed_key


def handle_request(
    client: OpenAI,
    db: firestore.Client,
    user_id: str,
    model: str,
    user_input: str,
    *,
    routing_model: str | None = None,
) -> Any:
    """Route a user message, create a response, and advance topic pointers."""
    _validate_user_id(user_id)
    if not user_input.strip():
        raise ValueError("user_input must not be empty")

    state_ref = db.document(
        f"users/{user_id}/state/{CONVERSATION_STATE_DOCUMENT}"
    )
    state_snapshot = state_ref.get()
    state = state_snapshot.to_dict() if state_snapshot.exists else {}
    active_topic_key = (state or {}).get("active_topic_key")

    topic_snapshots = list(db.collection(f"users/{user_id}/topics").stream())
    topics = {snapshot.id: snapshot.to_dict() or {} for snapshot in topic_snapshots}
    decision = classify_topic(
        client,
        db,
        user_id,
        routing_model or model,
        user_input,
        active_topic_key,
        sorted(topics),
    )
    if decision.instruction_update:
        append_user_instruction(db, user_id, decision.instruction_update)
    topic_key = _resolve_topic_key(decision, active_topic_key, set(topics))
    previous_response_id = topics.get(topic_key, {}).get("latest_response_id")

    request: dict[str, Any] = {"model": model, "input": user_input}
    if previous_response_id:
        request["previous_response_id"] = previous_response_id
    response = create_response(client, db, user_id, **request)

    topic_ref = db.document(f"users/{user_id}/topics/{topic_key}")
    batch = db.batch()
    batch.set(
        topic_ref,
        {
            "latest_response_id": response.id,
            "topic_key": topic_key,
            "updated_at": firestore.SERVER_TIMESTAMP,
        },
        merge=True,
    )
    batch.set(
        state_ref,
        {
            "active_topic_key": topic_key,
            "latest_response_id": response.id,
            "updated_at": firestore.SERVER_TIMESTAMP,
        },
        merge=True,
    )
    batch.commit()
    return response
