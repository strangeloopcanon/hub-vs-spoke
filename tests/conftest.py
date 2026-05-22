"""Shared fixtures for the test suite."""

from __future__ import annotations

import pytest

from hub_vs_spoke.agents.mock_agent import MockAgent
from hub_vs_spoke.tasks.base import EvalMethod, Task, TaskCategory, TaskRegistry
from hub_vs_spoke.types import TokenBudget

# ---------------------------------------------------------------------------
# Mock agents
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_hub() -> MockAgent:
    """A mock hub agent that returns structured JSON decompositions."""
    return MockAgent(
        name="hub",
        model_name="mock-hub-model",
        responses=[
            # Decomposition response
            '["Subtask 1: Research the topic", '
            '"Subtask 2: Write the draft", '
            '"Subtask 3: Review and edit"]',
            # Synthesis response
            "This is the synthesised final answer combining all worker outputs.",
        ],
    )


@pytest.fixture
def mock_spokes() -> list[MockAgent]:
    """Three mock spoke agents."""
    return [
        MockAgent(
            name=f"spoke-{i}", model_name="mock-spoke-model", responses=[f"Spoke {i} result"]
        )
        for i in range(3)
    ]


@pytest.fixture
def mock_peers() -> list[MockAgent]:
    """Three mock peer agents for spoke-spoke topology."""
    return [
        MockAgent(
            name=f"peer-{i}",
            model_name="mock-peer-model",
            responses=[
                # First call: decomposition or execution
                '["Peer subtask A", "Peer subtask B", "Peer subtask C"]'
                if i == 0
                else f"Peer {i} completed its subtask",
                # Second call: review or synthesis
                "LGTM" if i == 1 else "Final synthesised answer from peer mesh.",
            ],
        )
        for i in range(3)
    ]


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@pytest.fixture
def simple_task() -> Task:
    return Task(
        task_id="test-001",
        category=TaskCategory.CODING,
        prompt="Write a function that adds two numbers.",
        description="Simple addition function",
        expected_answer="def add(a, b): return a + b",
        eval_method=EvalMethod.EXACT_MATCH,
        eval_rubric="Must return sum of two arguments.",
        difficulty="easy",
    )


@pytest.fixture
def reasoning_task() -> Task:
    return Task(
        task_id="test-002",
        category=TaskCategory.REASONING,
        prompt="What is 2 + 2?",
        description="Trivial math",
        expected_answer="4",
        eval_method=EvalMethod.EXACT_MATCH,
        difficulty="easy",
    )


@pytest.fixture
def default_budget() -> TokenBudget:
    return TokenBudget(max_total_tokens=50_000, max_turns=20)


@pytest.fixture
def tight_budget() -> TokenBudget:
    """Budget that will be exhausted quickly — useful for testing budget limits."""
    return TokenBudget(max_total_tokens=500, max_turns=3)


@pytest.fixture
def sample_registry() -> TaskRegistry:
    """A small registry with a couple of test tasks."""
    reg = TaskRegistry()
    reg.register(Task(
        task_id="reg-001",
        category=TaskCategory.CODING,
        prompt="Write hello world",
        eval_method=EvalMethod.CODE_EXECUTION,
    ))
    reg.register(Task(
        task_id="reg-002",
        category=TaskCategory.REASONING,
        prompt="What is 1+1?",
        expected_answer="2",
        eval_method=EvalMethod.EXACT_MATCH,
    ))
    return reg
