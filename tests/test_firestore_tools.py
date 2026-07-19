import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app import bot
from app.firestore_tools import execute_firestore_tool


def test_get_user_data_is_scoped_to_current_user() -> None:
    db = MagicMock()
    snapshot = db.document.return_value.get.return_value
    snapshot.exists = True
    snapshot.to_dict.return_value = {"color": "blue"}

    result = execute_firestore_tool(
        db,
        "telegram-42",
        "get_user_data",
        '{"key":"profile"}',
    )

    db.document.assert_called_once_with("users/telegram-42/data/profile")
    assert json.loads(result) == {"found": True, "data": {"color": "blue"}}


@pytest.mark.parametrize("key", ["../config", "other/user", "", "has space"])
def test_user_data_rejects_unsafe_keys(key: str) -> None:
    with pytest.raises(ValueError, match="key must be"):
        execute_firestore_tool(
            MagicMock(),
            "telegram-42",
            "get_user_data",
            json.dumps({"key": key}),
        )


def test_upsert_user_data_requires_an_object() -> None:
    with pytest.raises(ValueError, match="encode a JSON object"):
        execute_firestore_tool(
            MagicMock(),
            "telegram-42",
            "upsert_user_data",
            json.dumps({"key": "profile", "value_json": '["not", "object"]'}),
        )


def test_create_response_executes_tool_and_returns_final_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(bot, "BASE_INSTRUCTIONS", "base")
    db = MagicMock()
    config = db.document.return_value.get.return_value
    config.exists = False
    tool_call = SimpleNamespace(
        type="function_call",
        name="get_user_data",
        arguments='{"key":"profile"}',
        call_id="call-1",
    )
    first = SimpleNamespace(id="resp-tool", output=[tool_call])
    final = SimpleNamespace(id="resp-final", output=[], output_text="Saved data")
    client = MagicMock()
    client.responses.create.side_effect = [first, final]

    response = bot.create_response(
        client,
        db,
        "telegram-42",
        model="gpt-5.6",
        input="Read my profile",
    )

    assert response is final
    second_request = client.responses.create.call_args_list[1].kwargs
    assert second_request["previous_response_id"] == "resp-tool"
    assert second_request["input"][0]["type"] == "function_call_output"
    assert second_request["input"][0]["call_id"] == "call-1"
