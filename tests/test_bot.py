from unittest.mock import MagicMock

import pytest

from app import bot


def firestore_with(instructions: object, *, exists: bool = True) -> MagicMock:
    db = MagicMock()
    snapshot = db.document.return_value.get.return_value
    snapshot.exists = exists
    snapshot.to_dict.return_value = {"instructions": instructions}
    return db


def test_build_instructions_appends_database_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bot, "BASE_INSTRUCTIONS", "baseline: ")
    db = firestore_with("database")

    assert bot.build_instructions(db, "user-123") == "baseline: database"
    db.document.assert_called_once_with("users/user-123/config/bot")


def test_build_instructions_uses_baseline_when_document_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bot, "BASE_INSTRUCTIONS", "baseline")

    assert (
        bot.build_instructions(firestore_with("ignored", exists=False), "user-123")
        == "baseline"
    )


def test_create_response_always_sets_combined_instructions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bot, "BASE_INSTRUCTIONS", "base")
    client = MagicMock()
    db = firestore_with(" + db")

    bot.create_response(
        client,
        db,
        "user-123",
        model="gpt-5.4",
        input="Hello",
        instructions="caller value must not bypass composition",
    )

    client.responses.create.assert_called_once_with(
        model="gpt-5.4",
        input="Hello",
        instructions="base + db",
    )


def test_append_user_instruction_preserves_existing_instructions() -> None:
    db = firestore_with("Use concise answers.")
    config_ref = db.document.return_value

    bot.append_user_instruction(db, "user-123", "Prefer metric units.")

    config_ref.set.assert_called_once_with(
        {
            "instructions": "Use concise answers.\nPrefer metric units.",
            "updated_at": bot.firestore.SERVER_TIMESTAMP,
        },
        merge=True,
    )


def test_append_user_instruction_ignores_duplicate_line() -> None:
    db = firestore_with("Prefer metric units.\nUse concise answers.")

    bot.append_user_instruction(db, "user-123", " Prefer metric units. ")

    db.document.return_value.set.assert_not_called()


def test_build_instructions_rejects_non_string_database_value() -> None:
    with pytest.raises(TypeError, match="must be a string"):
        bot.build_instructions(firestore_with(123), "user-123")


@pytest.mark.parametrize("user_id", ["", "users/user-123"])
def test_build_instructions_rejects_invalid_user_id(user_id: str) -> None:
    with pytest.raises(ValueError, match="Firestore path segment"):
        bot.build_instructions(firestore_with("database"), user_id)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (" Google Cloud Run! ", "google-cloud-run"),
        ("---", "general"),
        ("A" * 120, "a" * 100),
    ],
)
def test_normalize_topic_key(value: str, expected: str) -> None:
    assert bot.normalize_topic_key(value) == expected


def test_resolve_ambiguous_followup_to_active_topic() -> None:
    decision = bot.TopicDecision(
        action="continue",
        topic_key="unrelated-derived-key",
        confidence=0.8,
    )

    assert (
        bot._resolve_topic_key(decision, "cloud-run", {"cloud-run"})
        == "cloud-run"
    )


def test_handle_request_continues_active_topic(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    client.responses.create.return_value.id = "resp-new"
    db = MagicMock()

    config_ref = MagicMock()
    config_ref.get.return_value.exists = False
    state_ref = MagicMock()
    state_ref.get.return_value.exists = True
    state_ref.get.return_value.to_dict.return_value = {
        "active_topic_key": "cloud-run"
    }
    topic_ref = MagicMock()
    refs = {
        "users/user-123/config/bot": config_ref,
        "users/user-123/state/conversation": state_ref,
        "users/user-123/topics/cloud-run": topic_ref,
    }
    db.document.side_effect = refs.__getitem__
    topic_snapshot = MagicMock()
    topic_snapshot.id = "cloud-run"
    topic_snapshot.to_dict.return_value = {"latest_response_id": "resp-old"}
    db.collection.return_value.stream.return_value = iter([topic_snapshot])
    monkeypatch.setattr(
        bot,
        "classify_topic",
        MagicMock(
            return_value=bot.TopicDecision(
                action="continue",
                topic_key="permissions",
                confidence=0.95,
            )
        ),
    )

    response = bot.handle_request(
        client,
        db,
        "user-123",
        "gpt-5.4",
        "What permissions does it need?",
    )

    assert response.id == "resp-new"
    client.responses.create.assert_called_once_with(
        model="gpt-5.4",
        input="What permissions does it need?",
        previous_response_id="resp-old",
        instructions="",
    )
    batch = db.batch.return_value
    assert batch.set.call_count == 2
    batch.commit.assert_called_once_with()


def test_handle_request_starts_new_topic_without_previous_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MagicMock()
    client.responses.create.return_value.id = "resp-first"
    db = MagicMock()

    config_ref = MagicMock()
    config_ref.get.return_value.exists = False
    state_ref = MagicMock()
    state_ref.get.return_value.exists = False
    topic_ref = MagicMock()
    refs = {
        "users/user-123/config/bot": config_ref,
        "users/user-123/state/conversation": state_ref,
        "users/user-123/topics/new-subject": topic_ref,
    }
    db.document.side_effect = refs.__getitem__
    db.collection.return_value.stream.return_value = iter(())
    monkeypatch.setattr(
        bot,
        "classify_topic",
        MagicMock(
            return_value=bot.TopicDecision(
                action="create",
                topic_key="New Subject",
                confidence=0.99,
            )
        ),
    )

    bot.handle_request(client, db, "user-123", "gpt-5.4", "A new subject")

    client.responses.create.assert_called_once_with(
        model="gpt-5.4",
        input="A new subject",
        instructions="",
    )


def test_handle_request_validates_user_before_database_access() -> None:
    db = MagicMock()

    with pytest.raises(ValueError, match="Firestore path segment"):
        bot.handle_request(MagicMock(), db, "users/bad", "gpt-5.4", "Hello")

    db.document.assert_not_called()


def test_handle_request_saves_preference_before_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MagicMock()
    client.responses.create.return_value.id = "resp-new"
    db = MagicMock()

    missing_config = MagicMock()
    missing_config.exists = False
    saved_config = MagicMock()
    saved_config.exists = True
    saved_config.to_dict.return_value = {"instructions": "Prefer metric units."}
    config_ref = MagicMock()
    config_ref.get.side_effect = [missing_config, saved_config]
    state_ref = MagicMock()
    state_ref.get.return_value.exists = False
    topic_ref = MagicMock()
    refs = {
        "users/user-123/config/bot": config_ref,
        "users/user-123/state/conversation": state_ref,
        "users/user-123/topics/preferences": topic_ref,
    }
    db.document.side_effect = refs.__getitem__
    db.collection.return_value.stream.return_value = iter(())
    monkeypatch.setattr(
        bot,
        "classify_topic",
        MagicMock(
            return_value=bot.TopicDecision(
                action="create",
                topic_key="preferences",
                confidence=0.99,
                instruction_update="Prefer metric units.",
            )
        ),
    )

    bot.handle_request(
        client,
        db,
        "user-123",
        "gpt-5.4",
        "Please use metric units from now on.",
    )

    config_ref.set.assert_called_once()
    client.responses.create.assert_called_once_with(
        model="gpt-5.4",
        input="Please use metric units from now on.",
        instructions="Prefer metric units.",
    )
