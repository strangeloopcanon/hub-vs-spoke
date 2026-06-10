"""Tests for benchmark runner configuration wiring."""

from __future__ import annotations

from scripts.run_benchmark import DEFAULT_CONFIGS, _build_market_topology, _summary_cost_usd


def test_frontier_cli_market_config_uses_cli_refs_and_codex_judge() -> None:
    config = next(c for c in DEFAULT_CONFIGS if c.label == "frontier-cli-market")
    topology = _build_market_topology(config)

    assert config.collect_shadow is False
    assert config.judge_model == "codex:gpt-5.5"
    assert config.judge_include_self is False
    assert topology._worker_configs == [
        ("codex-gpt-5.5", "codex:gpt-5.5"),
        (
            "cursor-claude-opus-4-7-thinking-high",
            "cursor:claude-opus-4-7-thinking-high",
        ),
        ("gpt-5-mini", "gpt-5-mini"),
    ]
    assert topology._judge_workers == ["codex-gpt-5.5"]
    assert topology._judge_include_self is False


def test_summary_cost_uses_one_market_session_cost_per_rep() -> None:
    rows = [
        {
            "config_label": "frontier-cli-market",
            "repetition": 0,
            "total_cost_usd": 999,
            "market_session_total_cost_usd": 1.25,
        },
        {
            "config_label": "frontier-cli-market",
            "repetition": 0,
            "total_cost_usd": 999,
            "market_session_total_cost_usd": 1.25,
        },
        {
            "config_label": "frontier-cli-market",
            "repetition": 1,
            "total_cost_usd": 999,
            "market_session_total_cost_usd": 2.0,
        },
    ]

    assert _summary_cost_usd(rows) == 3.25
