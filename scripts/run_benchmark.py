#!/usr/bin/env python
"""CLI benchmark runner: execute the full topology comparison matrix and emit JSONL results.

Usage:
    python scripts/run_benchmark.py                     # run all configurations
    python scripts/run_benchmark.py --category coding   # single category
    python scripts/run_benchmark.py --dry-run           # show matrix without running
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Ensure the src package is importable when running as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import structlog

from hub_vs_spoke.agents.agent import Agent
from hub_vs_spoke.config import get_settings
from hub_vs_spoke.evaluation.deterministic import DeterministicEvaluator
from hub_vs_spoke.evaluation.judge import LLMJudge
from hub_vs_spoke.providers.anthropic_provider import AnthropicProvider
from hub_vs_spoke.providers.openai_provider import OpenAIProvider
from hub_vs_spoke.tasks import TaskCategory, default_registry
from hub_vs_spoke.tasks.base import EvalMethod, Task
from hub_vs_spoke.topologies.hub_spoke import HubSpokeTopology
from hub_vs_spoke.topologies.market import MarketTopology
from hub_vs_spoke.topologies.solo import SoloTopology
from hub_vs_spoke.types import TokenBudget, TopologyResult

logger = structlog.get_logger()

# Shadow tasks: mix of original + hard tasks for counterfactual analysis.
SHADOW_TASK_IDS = {
    "coding-002", "coding-005",
    "reasoning-004",
    "synthesis-001", "synthesis-005",
}


# ---------------------------------------------------------------------------
# Configuration matrix
# ---------------------------------------------------------------------------

@dataclass
class TopologyConfig:
    label: str
    topology_type: str  # "solo", "hub-spoke", "market"
    hub_model: str | None
    spoke_models: list[str] = field(default_factory=list)
    collect_shadow: bool = True
    judge_model: str | None = None
    judge_include_self: bool = True


DEFAULT_CONFIGS: list[TopologyConfig] = [
    TopologyConfig("solo-opus-4.6", "solo", "claude-opus-4-6"),
    TopologyConfig(
        "opus-hub+gpt5-spokes", "hub-spoke", "claude-opus-4-5",
        ["gpt-5.2"] * 3,
    ),
    TopologyConfig(
        "agent-economy", "market", None,
        ["gpt-5.2", "claude-opus-4-6", "gpt-5-mini"],
    ),
    TopologyConfig(
        "frontier-cli-market", "market", None,
        ["codex:gpt-5.5", "cursor:claude-opus-4-7-thinking-high", "gpt-5-mini"],
        collect_shadow=False,
        judge_model="codex:gpt-5.5",
        judge_include_self=False,
    ),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_provider(model: str) -> OpenAIProvider | AnthropicProvider:
    """Create the right provider for a given model name."""
    if model.startswith("claude"):
        return AnthropicProvider(model=model)
    return OpenAIProvider(model=model)


def _build_topology(config: TopologyConfig) -> SoloTopology | HubSpokeTopology:
    """Instantiate a per-task topology from its config.

    Market topology is handled separately via _build_market_topology.
    """
    if config.topology_type == "solo" and config.hub_model:
        agent = Agent(
            name="solo",
            provider=_make_provider(config.hub_model),
            system_prompt="Answer the task directly and concisely.",
            max_tokens=2048,
        )
        return SoloTopology(agent=agent)

    if config.topology_type == "hub-spoke" and config.hub_model:
        hub = Agent(
            name="hub",
            provider=_make_provider(config.hub_model),
            system_prompt=(
                "You are an orchestrator. Decompose tasks and synthesise results."
            ),
            max_tokens=1024,
        )
        spokes = [
            Agent(
                name=f"spoke-{i}",
                provider=_make_provider(m),
                system_prompt="You are a specialist worker. Complete subtasks concisely.",
                max_tokens=768,
            )
            for i, m in enumerate(config.spoke_models)
        ]
        return HubSpokeTopology(hub=hub, spokes=spokes)

    raise ValueError(f"Cannot build per-task topology for type={config.topology_type!r}")


def _build_market_topology(config: TopologyConfig) -> MarketTopology:
    """Build a MarketTopology from config."""
    # Map model names to agent-economy model_ref format.
    # Anthropic API models need 'claude:' prefix for LLMRouter routing.
    worker_configs: list[tuple[str, str]] = []
    for model in config.spoke_models:
        if model.startswith("claude"):
            worker_configs.append((model, f"claude:{model}"))
        elif ":" in model:
            provider, raw_model = model.split(":", 1)
            worker_id = f"{provider}-{raw_model}"
            worker_configs.append((worker_id, model))
        else:
            worker_configs.append((model, model))

    if config.judge_model is not None:
        judge_workers = [
            worker_id
            for worker_id, model_ref in worker_configs
            if model_ref == config.judge_model
        ]
    else:
        # Use the first API-backed OpenAI model as judge by default.
        judge_workers = [
            worker_id
            for worker_id, model_ref in worker_configs
            if ":" not in model_ref and not model_ref.startswith("claude:")
        ]
    if not judge_workers:
        judge_workers = [worker_configs[0][0]]

    return MarketTopology(
        worker_configs,
        judge_workers=judge_workers[:1],
        judge_include_self=config.judge_include_self,
    )


_judge: LLMJudge | None = None


def _get_judge() -> LLMJudge:
    """Lazily create a shared LLMJudge using the configured judge model."""
    global _judge  # noqa: PLW0603
    if _judge is None:
        settings = get_settings()
        _judge = LLMJudge(provider=_make_provider(settings.judge_model))
    return _judge


async def _evaluate(task: Task, answer: str) -> dict[str, Any]:
    """Dispatch evaluation for a task result based on its eval_method.

    Returns a dict with at least: eval_score (float 0-10), eval_match (bool),
    eval_method (str), and optional eval_details.
    """
    method = task.eval_method

    if not answer.strip():
        return {
            "eval_score": 0.0,
            "eval_match": False,
            "eval_method": method.value,
            "eval_details": "Empty answer",
        }

    try:
        if method == EvalMethod.EXACT_MATCH:
            expected = task.expected_answer or ""
            result = DeterministicEvaluator.exact_match(answer, expected)
            return {
                "eval_score": 10.0 if result["match"] else 0.0,
                "eval_match": result["match"],
                "eval_method": method.value,
                "eval_details": result,
            }

        if method == EvalMethod.REGEX_MATCH:
            pattern = task.expected_answer or ""
            result = DeterministicEvaluator.regex_match(answer, pattern)
            return {
                "eval_score": 10.0 if result["match"] else 0.0,
                "eval_match": result["match"],
                "eval_method": method.value,
                "eval_details": result,
            }

        if method == EvalMethod.CODE_EXECUTION:
            result = DeterministicEvaluator.code_execution(
                answer, test_code=task.eval_rubric,
            )
            return {
                "eval_score": 10.0 if result["success"] else 0.0,
                "eval_match": result["success"],
                "eval_method": method.value,
                "eval_details": {
                    k: v for k, v in result.items() if k != "stdout"
                },
            }

        if method == EvalMethod.FUNCTION_CALL_CHECK:
            spec = task.metadata.get("expected_call_spec") or task.metadata.get(
                "expected_tools", [],
            )
            result = DeterministicEvaluator.function_call_check(answer, spec)
            matched = result.get("match", result.get("all_present", False))
            return {
                "eval_score": 10.0 if matched else 0.0,
                "eval_match": bool(matched),
                "eval_method": method.value,
                "eval_details": {
                    k: v for k, v in result.items() if k not in ("parsed_calls",)
                },
            }

        if method == EvalMethod.LLM_JUDGE:
            judge = _get_judge()
            result = await judge.score_absolute(
                task.prompt, answer, task.eval_rubric,
            )
            score = result.get("score", 5)
            return {
                "eval_score": float(score),
                "eval_match": score >= 7,
                "eval_method": method.value,
                "eval_details": result,
            }

    except Exception as exc:
        logger.warning("eval_failed", task_id=task.task_id, error=str(exc))
        return {
            "eval_score": 0.0,
            "eval_match": False,
            "eval_method": method.value,
            "eval_details": f"Evaluation error: {exc}",
        }

    return {
        "eval_score": 0.0,
        "eval_match": False,
        "eval_method": method.value,
        "eval_details": f"Unknown eval method: {method}",
    }


def _result_to_jsonl(
    config: TopologyConfig,
    category: str,
    task_id: str,
    rep: int,
    result: TopologyResult,
    eval_result: dict[str, Any],
) -> dict[str, Any]:
    """Convert a run result + evaluation to a JSONL-serialisable dict."""
    row: dict[str, Any] = {
        "config_label": config.label,
        "topology_type": config.topology_type,
        "hub_model": config.hub_model,
        "spoke_models": config.spoke_models,
        "category": category,
        "task_id": task_id,
        "repetition": rep,
        "success": result.success,
        "total_tokens": result.total_tokens,
        "total_cost_usd": round(result.total_cost_usd, 6),
        "wall_time_ms": round(result.wall_time_ms, 1),
        "num_turns": len(result.turns),
        "num_errors": len(result.errors),
        "errors": result.errors[:5],
        "answer_length": len(result.final_answer),
        "eval_score": eval_result.get("eval_score", 0.0),
        "eval_match": eval_result.get("eval_match", False),
        "eval_method": eval_result.get("eval_method", ""),
    }

    # Market-specific metadata
    if result.metadata:
        for key in (
            "market_winner",
            "market_bids",
            "market_attempts",
            "market_reputation",
            "market_session_total_tokens",
            "market_session_total_cost_usd",
            "market_session_usage_by_model",
            "shadow_answers",
        ):
            if key in result.metadata:
                row[key] = result.metadata[key]

    return row


# ---------------------------------------------------------------------------
# Shadow counterfactual collection
# ---------------------------------------------------------------------------

async def _collect_shadow_answers(
    shadow_tasks: list[Task],
    market_results: dict[str, TopologyResult],
    market_config: TopologyConfig,
    budget: TokenBudget,
) -> dict[str, list[dict[str, Any]]]:
    """For each shadow task, run non-winning models to get counterfactual answers.

    Returns {task_id: [{"model": str, "answer": str, "eval_score": float}, ...]}.
    """
    all_models = list(market_config.spoke_models)
    shadow_data: dict[str, list[dict[str, Any]]] = {}

    for task in shadow_tasks:
        tid = task.task_id
        market_result = market_results.get(tid)
        winner = (
            market_result.metadata.get("market_winner", "")
            if market_result
            else ""
        )

        # Run each non-winning model
        answers: list[dict[str, Any]] = []
        for model in all_models:
            if model == winner:
                # Include the winner's actual answer for comparison
                eval_result = await _evaluate(task, market_result.final_answer)
                answers.append({
                    "model": model,
                    "answer": market_result.final_answer[:500],
                    "eval_score": eval_result.get("eval_score", 0.0),
                    "is_winner": True,
                })
                continue

            logger.info("shadow_run", task_id=tid, model=model)
            agent = Agent(
                name=f"shadow-{model}",
                provider=_make_provider(model),
                system_prompt="Answer the task directly and concisely.",
                max_tokens=2048,
            )
            solo = SoloTopology(agent=agent)
            try:
                result = await solo.run(task, budget)
                eval_result = await _evaluate(task, result.final_answer)
                answers.append({
                    "model": model,
                    "answer": result.final_answer[:500],
                    "eval_score": eval_result.get("eval_score", 0.0),
                    "is_winner": False,
                })
            except Exception as exc:
                logger.warning("shadow_failed", task_id=tid, model=model, error=str(exc))
                answers.append({
                    "model": model,
                    "answer": "",
                    "eval_score": 0.0,
                    "is_winner": False,
                })

        shadow_data[tid] = answers

    return shadow_data


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

async def run_benchmark(
    configs: list[TopologyConfig],
    categories: list[TaskCategory],
    reps: int,
    budget: TokenBudget,
    output_path: Path,
) -> None:
    """Run the full benchmark matrix and write JSONL results."""
    all_results: list[dict[str, Any]] = []
    total_runs = 0
    total_errors = 0

    # Gather all tasks across categories
    all_tasks: list[Task] = []
    for category in categories:
        all_tasks.extend(default_registry.by_category(category))

    with open(output_path, "w") as fout:
        for config in configs:
            if config.topology_type == "market":
                # Market: run all tasks in one engine session
                rows = await _run_market_config(
                    config, all_tasks, reps, budget, fout,
                )
                all_results.extend(rows)
                total_runs += len(rows)
                total_errors += sum(1 for r in rows if r.get("num_errors", 0) > 0)
            else:
                # Solo and hub-spoke: run per-task
                for task in all_tasks:
                    for rep in range(reps):
                        total_runs += 1
                        row = await _run_single_task(
                            config, task, rep, budget, fout,
                        )
                        all_results.append(row)
                        if row.get("num_errors", 0) > 0:
                            total_errors += 1

    _print_summary(all_results, total_runs, total_errors)


async def _run_single_task(
    config: TopologyConfig,
    task: Task,
    rep: int,
    budget: TokenBudget,
    fout: Any,
) -> dict[str, Any]:
    """Run a single task with a per-task topology."""
    topology = _build_topology(config)
    label = f"{config.label}/{task.category.value}/{task.task_id}/rep{rep}"

    logger.info("run_start", run=label)
    t0 = time.perf_counter()

    try:
        result = await topology.run(task, budget)
    except Exception as exc:
        logger.error("run_failed", run=label, error=str(exc))
        result = TopologyResult(
            topology_name=config.topology_type,
            task_id=task.task_id,
            final_answer="",
            errors=[str(exc)],
            wall_time_ms=(time.perf_counter() - t0) * 1000,
        )

    eval_result = await _evaluate(task, result.final_answer)
    row = _result_to_jsonl(
        config, task.category.value, task.task_id, rep, result, eval_result,
    )
    fout.write(json.dumps(row) + "\n")
    fout.flush()

    _log_run_done(label, result, eval_result)
    return row


async def _run_market_config(
    config: TopologyConfig,
    all_tasks: list[Task],
    reps: int,
    budget: TokenBudget,
    fout: Any,
) -> list[dict[str, Any]]:
    """Run the market topology: all tasks in one engine session."""
    rows: list[dict[str, Any]] = []

    for rep in range(reps):
        logger.info("market_session_start", config=config.label, rep=rep)
        market = _build_market_topology(config)

        try:
            results = await market.run_all(all_tasks, budget)
        except Exception as exc:
            logger.error("market_session_failed", error=str(exc))
            # Emit empty results for each task
            for task in all_tasks:
                result = TopologyResult(
                    topology_name="market",
                    task_id=task.task_id,
                    final_answer="",
                    errors=[str(exc)],
                )
                eval_result = await _evaluate(task, "")
                row = _result_to_jsonl(
                    config, task.category.value, task.task_id, rep,
                    result, eval_result,
                )
                fout.write(json.dumps(row) + "\n")
                fout.flush()
                rows.append(row)
            continue

        # Build task lookup for shadow collection
        market_results: dict[str, TopologyResult] = {}
        for task, result in zip(all_tasks, results, strict=False):
            market_results[task.task_id] = result

        # Collect shadow counterfactuals
        shadow_tasks = (
            [t for t in all_tasks if t.task_id in SHADOW_TASK_IDS]
            if config.collect_shadow
            else []
        )
        shadow_data: dict[str, list[dict[str, Any]]] = {}
        if shadow_tasks:
            logger.info("shadow_collection_start", count=len(shadow_tasks))
            shadow_data = await _collect_shadow_answers(
                shadow_tasks, market_results, config, budget,
            )

        # Evaluate and emit results
        for task, result in zip(all_tasks, results, strict=False):
            eval_result = await _evaluate(task, result.final_answer)

            # Attach shadow data if available
            if task.task_id in shadow_data:
                result.metadata["shadow_answers"] = shadow_data[task.task_id]

            row = _result_to_jsonl(
                config, task.category.value, task.task_id, rep,
                result, eval_result,
            )
            fout.write(json.dumps(row) + "\n")
            fout.flush()
            rows.append(row)

            label = f"{config.label}/{task.category.value}/{task.task_id}/rep{rep}"
            _log_run_done(label, result, eval_result)

    return rows


def _log_run_done(
    label: str, result: TopologyResult, eval_result: dict[str, Any],
) -> None:
    """Log completion of a single run."""
    status = "OK" if result.success else "FAIL"
    eval_tag = (
        f"score={eval_result['eval_score']}"
        if eval_result.get("eval_method") == "llm_judge"
        else f"match={eval_result['eval_match']}"
    )
    logger.info(
        "run_done", run=label, status=status,
        tokens=result.total_tokens,
        cost_usd=round(result.total_cost_usd, 4),
        time_ms=round(result.wall_time_ms, 0),
        eval=eval_tag,
    )


def _print_summary(
    results: list[dict[str, Any]], total_runs: int, total_errors: int,
) -> None:
    """Print a human-readable summary of benchmark results."""
    print("\n" + "=" * 90)
    print("BENCHMARK SUMMARY")
    print("=" * 90)
    print(f"Total runs: {total_runs}  |  Errors: {total_errors}\n")

    # By config
    by_config: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        by_config.setdefault(r["config_label"], []).append(r)

    fmt = "{:<30} {:>5} {:>5} {:>6} {:>7} {:>8} {:>8} {:>10}"
    print(fmt.format(
        "Config", "Runs", "Pass", "Rate", "AvgScr", "Cost$", "Tokens", "Time(ms)",
    ))
    print("-" * 90)
    for label, rows in sorted(by_config.items()):
        n = len(rows)
        passed = sum(1 for r in rows if r["eval_match"])
        avg_score = sum(r.get("eval_score", 0) for r in rows) / n
        total_cost = _summary_cost_usd(rows)
        avg_tok = sum(r["total_tokens"] for r in rows) / n
        avg_ms = sum(r["wall_time_ms"] for r in rows) / n
        print(fmt.format(
            label, n, passed, f"{passed / n:.0%}",
            f"{avg_score:.1f}", f"{total_cost:.4f}",
            f"{avg_tok:.0f}", f"{avg_ms:.0f}",
        ))

    # By category
    print()
    cat_fmt = "{:<20} {:>5} {:>5} {:>6} {:>7}"
    print(cat_fmt.format("Category", "Runs", "Pass", "Rate", "AvgScr"))
    print("-" * 48)
    by_cat: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        by_cat.setdefault(r["category"], []).append(r)
    for cat, rows in sorted(by_cat.items()):
        n = len(rows)
        passed = sum(1 for r in rows if r["eval_match"])
        avg_score = sum(r.get("eval_score", 0) for r in rows) / n
        print(cat_fmt.format(cat, n, passed, f"{passed / n:.0%}", f"{avg_score:.1f}"))

    print("=" * 90)


def _summary_cost_usd(rows: list[dict[str, Any]]) -> float:
    """Return total run cost, using market session totals when present."""
    session_costs: dict[tuple[str, int], float] = {}
    for row in rows:
        if "market_session_total_cost_usd" not in row:
            continue
        key = (str(row.get("config_label", "")), int(row.get("repetition", 0)))
        session_costs[key] = float(row.get("market_session_total_cost_usd") or 0.0)
    if session_costs:
        return sum(session_costs.values())
    return sum(float(r.get("total_cost_usd", 0.0) or 0.0) for r in rows)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    from dotenv import load_dotenv
    load_dotenv()

    parser = argparse.ArgumentParser(description="Run hub-vs-spoke benchmark matrix")
    parser.add_argument("--category", type=str, default=None,
                        help="Run only this task category")
    parser.add_argument("--reps", type=int, default=3,
                        help="Repetitions per configuration")
    parser.add_argument("--budget-tokens", type=int, default=30_000,
                        help="Max tokens per run")
    parser.add_argument("--budget-turns", type=int, default=15,
                        help="Max turns per run")
    parser.add_argument("--output", type=str, default="benchmark_results.jsonl",
                        help="Output JSONL path")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the matrix without running")
    parser.add_argument("--config", type=str, default=None,
                        help="Run only configs matching this label substring")
    args = parser.parse_args()

    # Resolve categories
    if args.category:
        try:
            categories = [TaskCategory(args.category)]
        except ValueError:
            print(f"Unknown category: {args.category}")
            print(f"Available: {[c.value for c in TaskCategory]}")
            sys.exit(1)
    else:
        categories = list(TaskCategory)

    # Filter configs
    configs = DEFAULT_CONFIGS
    if args.config:
        configs = [c for c in configs if args.config in c.label]
        if not configs:
            print(f"No configs match '{args.config}'")
            sys.exit(1)

    budget = TokenBudget(max_total_tokens=args.budget_tokens, max_turns=args.budget_turns)

    if args.dry_run:
        print("Benchmark matrix (dry run):\n")
        total = 0
        for config in configs:
            for cat in categories:
                for task in default_registry.by_category(cat):
                    for rep in range(args.reps):
                        total += 1
                        label = f"  {config.label} / {cat.value} / {task.task_id}"
                        if config.topology_type == "market":
                            label += " [market-session]"
                        if (
                            config.collect_shadow
                            and task.task_id in SHADOW_TASK_IDS
                            and config.topology_type == "market"
                        ):
                            label += " [+shadow]"
                        print(f"{label} / rep{rep}")
        print(f"\nTotal task-runs: {total}")
        shadow_count = sum(
            1
            for c in configs
            if c.topology_type == "market" and c.collect_shadow
        ) * len(SHADOW_TASK_IDS) * args.reps
        if shadow_count:
            max_losers = max(
                len(c.spoke_models) - 1
                for c in configs
                if c.topology_type == "market" and c.collect_shadow
            )
            print(
                "Shadow counterfactuals: "
                f"{shadow_count} tasks x up to {max_losers} non-winner models"
            )
        return

    output_path = Path(args.output)
    cats = [c.value for c in categories]
    print(f"Running benchmark -> {output_path}")
    print(f"Configs: {len(configs)}  |  Categories: {cats}  |  Reps: {args.reps}")
    print(f"Budget: {budget.max_total_tokens} tokens, {budget.max_turns} turns\n")
    asyncio.run(run_benchmark(configs, categories, args.reps, budget, output_path))


if __name__ == "__main__":
    main()
