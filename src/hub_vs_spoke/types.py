"""Shared Pydantic models used across the harness."""

from __future__ import annotations

import time
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Role(StrEnum):
    """Message role in a conversation."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class Message(BaseModel):
    """Single message in a conversation."""

    role: Role
    content: str
    name: str | None = None  # optional agent identity tag


class Usage(BaseModel):
    """Token usage from a single LLM call."""

    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class LLMResponse(BaseModel):
    """Normalised response from any LLM provider."""

    content: str
    model: str
    usage: Usage = Field(default_factory=Usage)
    latency_ms: float = 0.0
    raw: dict[str, Any] = Field(default_factory=dict, exclude=True)


class TokenBudget(BaseModel):
    """Budget constraints for a topology run."""

    max_total_tokens: int = 50_000
    max_turns: int = 20

    def exceeded(self, tokens_used: int, turns_used: int) -> bool:
        return tokens_used >= self.max_total_tokens or turns_used >= self.max_turns


class Turn(BaseModel):
    """A single agent-to-agent communication turn."""

    from_agent: str
    to_agent: str
    message: str
    response: str
    usage: Usage = Field(default_factory=Usage)
    latency_ms: float = 0.0
    model: str = ""
    error: str | None = None


class TopologyResult(BaseModel):
    """Complete result of running a topology on a task."""

    topology_name: str
    task_id: str
    final_answer: str
    turns: list[Turn] = Field(default_factory=list)
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    wall_time_ms: float = 0.0
    errors: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def success(self) -> bool:
        return len(self.final_answer) > 0 and len(self.errors) == 0


class AgentResponse(BaseModel):
    """Response from an Agent.act() call."""

    content: str
    usage: Usage = Field(default_factory=Usage)
    model: str = ""
    latency_ms: float = 0.0


# Pricing per 1M tokens (input, output) in USD — as of February 2026.
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # OpenAI — current generation
    "gpt-5.5": (5.00, 30.00),
    "gpt-5.2": (1.75, 14.00),
    "gpt-5": (1.25, 10.00),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "o4-mini": (1.10, 4.40),
    # Anthropic — current generation
    "claude-opus-4-7": (5.00, 25.00),
    "claude-opus-4-6": (5.00, 25.00),
    "claude-opus-4-5": (5.00, 25.00),
    "claude-sonnet-4-5": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
}


def _lookup_pricing(model: str) -> tuple[float, float]:
    """Look up pricing for a model, falling back to prefix match.

    API responses often include version suffixes (e.g. 'claude-opus-4-5-20251101')
    that aren't in our pricing table.
    """
    if model in MODEL_PRICING:
        return MODEL_PRICING[model]
    # Prefix match: try longest-matching key
    for key in sorted(MODEL_PRICING, key=len, reverse=True):
        if model.startswith(key):
            return MODEL_PRICING[key]
    return (0.0, 0.0)


class CostRecord(BaseModel):
    """Cost breakdown for a single LLM call."""

    model: str
    input_tokens: int
    output_tokens: int
    input_cost_usd: float = 0.0
    output_cost_usd: float = 0.0

    @property
    def total_cost_usd(self) -> float:
        return self.input_cost_usd + self.output_cost_usd

    @classmethod
    def from_usage(cls, model: str, usage: Usage) -> CostRecord:
        pricing = _lookup_pricing(model)
        input_cost = (usage.input_tokens / 1_000_000) * pricing[0]
        output_cost = (usage.output_tokens / 1_000_000) * pricing[1]
        return cls(
            model=model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            input_cost_usd=input_cost,
            output_cost_usd=output_cost,
        )


class Timer:
    """Simple context-manager timer that records elapsed milliseconds."""

    def __init__(self) -> None:
        self.start: float = 0.0
        self.elapsed_ms: float = 0.0

    def __enter__(self) -> Timer:
        self.start = time.perf_counter()
        return self

    def __exit__(self, *_: object) -> None:
        self.elapsed_ms = (time.perf_counter() - self.start) * 1000
