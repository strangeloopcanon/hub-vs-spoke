"""Unit tests for the OpenAI provider request payload."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from hub_vs_spoke.providers.openai_provider import OpenAIProvider
from hub_vs_spoke.types import Message, Role


class _FakeCompletions:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            usage=SimpleNamespace(prompt_tokens=3, completion_tokens=4),
            model=kwargs["model"],
            model_dump=lambda: {"model": kwargs["model"]},
        )


def _attach_fake_client(provider: OpenAIProvider) -> _FakeCompletions:
    completions = _FakeCompletions()
    provider._client = SimpleNamespace(  # type: ignore[attr-defined]
        chat=SimpleNamespace(completions=completions),
    )
    return completions


@pytest.mark.asyncio
async def test_gpt5_provider_omits_temperature() -> None:
    provider = OpenAIProvider(model="gpt-5-mini", api_key="test-key")
    completions = _attach_fake_client(provider)

    await provider.complete(
        [Message(role=Role.USER, content="hello")],
        temperature=0.0,
        max_tokens=32,
    )

    call = completions.calls[0]
    assert call["model"] == "gpt-5-mini"
    assert call["max_completion_tokens"] == 32
    assert "temperature" not in call


@pytest.mark.asyncio
async def test_non_gpt5_provider_sends_temperature() -> None:
    provider = OpenAIProvider(model="gpt-4.1", api_key="test-key")
    completions = _attach_fake_client(provider)

    await provider.complete(
        [Message(role=Role.USER, content="hello")],
        temperature=0.2,
        max_tokens=32,
    )

    assert completions.calls[0]["temperature"] == 0.2
