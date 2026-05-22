"""Integration tests for hub-spoke and the legacy spoke-spoke peer mesh.

These tests make real API calls and are marked with @pytest.mark.live.
Run with: pytest -m live -v
"""

from __future__ import annotations

import pytest

from hub_vs_spoke.agents.agent import Agent
from hub_vs_spoke.evaluation.reliability import ReliabilityScorer
from hub_vs_spoke.providers.openai_provider import OpenAIProvider
from hub_vs_spoke.tasks.base import Task, TaskCategory
from hub_vs_spoke.topologies.hub_spoke import HubSpokeTopology
from hub_vs_spoke.topologies.spoke_spoke import SpokeSpokeTopology
from hub_vs_spoke.types import TokenBudget
from tests.integration.conftest import skip_no_openai


def _make_agents(
    model: str,
    count: int,
    prefix: str,
    *,
    max_tokens: int = 2048,
) -> list[Agent]:
    """Create N agents using the same model."""
    return [
        Agent(
            name=f"{prefix}-{i}",
            provider=OpenAIProvider(model=model),
            system_prompt="You are a helpful assistant. Be concise and direct.",
            max_tokens=max_tokens,
        )
        for i in range(count)
    ]


# Use a single simple task for fast integration testing.
QUICK_TASK = Task(
    task_id="integration-quick",
    category=TaskCategory.REASONING,
    prompt="What is 15 * 17? Show your work step by step.",
    description="Simple multiplication for integration test",
    expected_answer="255",
)


@pytest.mark.live
@skip_no_openai
class TestHubVsSpokeComparison:
    """Compare topologies on a simple task using real API calls."""

    @pytest.mark.asyncio
    async def test_hub_spoke_produces_answer(self) -> None:
        hub = Agent(
            name="hub",
            provider=OpenAIProvider(model="gpt-5-mini"),
            system_prompt="You are an orchestrator. Decompose tasks and synthesise results.",
            max_tokens=2048,
        )
        spokes = _make_agents("gpt-5-mini", 2, "spoke")
        topology = HubSpokeTopology(hub=hub, spokes=spokes)

        budget = TokenBudget(max_total_tokens=10_000, max_turns=10)
        result = await topology.run(QUICK_TASK, budget)

        assert result.success, f"Hub-spoke failed: {result.errors}"
        assert "255" in result.final_answer, f"Expected 255 in answer: {result.final_answer[:200]}"
        assert result.total_tokens > 0

    @pytest.mark.asyncio
    async def test_spoke_spoke_produces_answer(self) -> None:
        peers = _make_agents("gpt-5-mini", 3, "peer")
        topology = SpokeSpokeTopology(peers=peers)

        budget = TokenBudget(max_total_tokens=10_000, max_turns=10)
        result = await topology.run(QUICK_TASK, budget)

        assert result.success, f"Spoke-spoke failed: {result.errors}"
        assert "255" in result.final_answer, f"Expected 255 in answer: {result.final_answer[:200]}"
        assert result.total_tokens > 0

    @pytest.mark.asyncio
    async def test_head_to_head(self) -> None:
        """Run both topologies on the same task and compare metrics."""
        # Hub-spoke
        hub = Agent(
            name="hub",
            provider=OpenAIProvider(model="gpt-5-mini"),
            system_prompt="You are an orchestrator. Decompose tasks and synthesise results.",
            max_tokens=2048,
        )
        hs_spokes = _make_agents("gpt-5-mini", 2, "hs-spoke")
        hs_topology = HubSpokeTopology(hub=hub, spokes=hs_spokes)

        # Spoke-spoke
        ss_peers = _make_agents("gpt-5-mini", 3, "ss-peer")
        ss_topology = SpokeSpokeTopology(peers=ss_peers)

        budget = TokenBudget(max_total_tokens=15_000, max_turns=12)

        hs_result = await hs_topology.run(QUICK_TASK, budget)
        ss_result = await ss_topology.run(QUICK_TASK, budget)

        # Both should succeed
        assert hs_result.success, f"Hub-spoke failed: {hs_result.errors}"
        assert ss_result.success, f"Spoke-spoke failed: {ss_result.errors}"

        # Compare reliability
        comparison = ReliabilityScorer.compare_topologies([hs_result], [ss_result])
        assert comparison["hub_spoke"]["total_runs"] == 1
        assert comparison["spoke_spoke"]["total_runs"] == 1

        # Log results for manual inspection
        print("\n--- Head-to-head results ---")
        print(f"Hub-spoke tokens: {hs_result.total_tokens}, turns: {len(hs_result.turns)}")
        print(f"Spoke-spoke tokens: {ss_result.total_tokens}, turns: {len(ss_result.turns)}")
        print(f"Hub-spoke time: {hs_result.wall_time_ms:.0f}ms")
        print(f"Spoke-spoke time: {ss_result.wall_time_ms:.0f}ms")
