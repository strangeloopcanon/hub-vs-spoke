"""Unit tests for CLI-backed market router helpers."""

from __future__ import annotations

import json

from hub_vs_spoke.providers.cli_router import (
    _last_codex_agent_message,
    _parse_codex_usage,
    _parse_cursor_response,
)


def test_parse_codex_usage_sums_turns() -> None:
    usage = _parse_codex_usage(
        "\n".join(
            [
                json.dumps({"type": "thread.started"}),
                json.dumps(
                    {
                        "type": "turn.completed",
                        "usage": {"input_tokens": 10, "output_tokens": 3},
                    }
                ),
                json.dumps(
                    {
                        "type": "turn.completed",
                        "usage": {"input_tokens": 5, "output_tokens": 7},
                    }
                ),
            ]
        )
    )

    assert usage.calls == 2
    assert usage.input_tokens == 15
    assert usage.output_tokens == 10


def test_last_codex_agent_message() -> None:
    assert _last_codex_agent_message(
        "\n".join(
            [
                json.dumps(
                    {"type": "item.completed", "item": {"type": "agent_message", "text": "old"}}
                ),
                json.dumps(
                    {"type": "item.completed", "item": {"type": "agent_message", "text": "new"}}
                ),
            ]
        )
    ) == "new"


def test_parse_cursor_response_counts_cache_tokens_as_input() -> None:
    text, usage = _parse_cursor_response(
        json.dumps(
            {
                "type": "result",
                "is_error": False,
                "result": "answer",
                "usage": {
                    "inputTokens": 10,
                    "outputTokens": 20,
                    "cacheReadTokens": 30,
                    "cacheWriteTokens": 40,
                },
            }
        )
    )

    assert text == "answer"
    assert usage.calls == 1
    assert usage.input_tokens == 80
    assert usage.output_tokens == 20
