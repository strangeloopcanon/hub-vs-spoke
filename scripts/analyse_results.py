#!/usr/bin/env python
"""Analyse benchmark JSONL results with calibration, routing accuracy, and bootstrap CIs.

Usage:
    python scripts/analyse_results.py benchmark_results.jsonl
    python scripts/analyse_results.py results/hard_run.jsonl --csv results/hard_summary.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_results(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with open(path) as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                print(f"Warning: skipping invalid JSON on line {i}")
    return rows


# ---------------------------------------------------------------------------
# Grouping helpers
# ---------------------------------------------------------------------------


def _group_by(rows: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        groups.setdefault(r[key], []).append(r)
    return groups


def _agg(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute aggregate stats for a group of result rows."""
    n = len(rows)
    if n == 0:
        return {}
    eval_matches = sum(1 for r in rows if r.get("eval_match"))
    scores = [r.get("eval_score", 0.0) for r in rows]
    costs = [r.get("total_cost_usd", 0.0) for r in rows]
    tokens = [r.get("total_tokens", 0) for r in rows]
    times = [r.get("wall_time_ms", 0.0) for r in rows]
    errors = sum(r.get("num_errors", 0) for r in rows)
    return {
        "runs": n,
        "pass": eval_matches,
        "rate": eval_matches / n,
        "avg_score": sum(scores) / n,
        "total_cost": sum(costs),
        "avg_cost": sum(costs) / n,
        "avg_tokens": sum(tokens) / n,
        "avg_time_ms": sum(times) / n,
        "total_errors": errors,
    }


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

W = 100  # table width


def _header(title: str) -> None:
    print()
    print("=" * W)
    print(f"  {title}")
    print("=" * W)


def print_by_topology(rows: list[dict[str, Any]]) -> None:
    """Per-topology-type comparison (the main question)."""
    _header("BY TOPOLOGY TYPE")
    groups = _group_by(rows, "topology_type")

    fmt = "{:<20} {:>5} {:>5} {:>6} {:>7} {:>9} {:>8} {:>10} {:>6}"
    print(fmt.format(
        "Topology", "Runs", "Pass", "Rate", "AvgScr", "Cost$", "AvgTok", "AvgMs", "Errs",
    ))
    print("-" * W)
    for topo_type in sorted(groups):
        a = _agg(groups[topo_type])
        print(fmt.format(
            topo_type, a["runs"], a["pass"], f"{a['rate']:.0%}",
            f"{a['avg_score']:.1f}", f"{a['total_cost']:.4f}",
            f"{a['avg_tokens']:.0f}", f"{a['avg_time_ms']:.0f}",
            a["total_errors"],
        ))


def print_by_config(rows: list[dict[str, Any]]) -> None:
    """Per-config breakdown."""
    _header("BY CONFIG")
    groups = _group_by(rows, "config_label")

    fmt = "{:<30} {:>5} {:>5} {:>6} {:>7} {:>9} {:>8} {:>10}"
    print(fmt.format(
        "Config", "Runs", "Pass", "Rate", "AvgScr", "Cost$", "AvgTok", "AvgMs",
    ))
    print("-" * W)
    for label in sorted(groups):
        a = _agg(groups[label])
        print(fmt.format(
            label, a["runs"], a["pass"], f"{a['rate']:.0%}",
            f"{a['avg_score']:.1f}", f"{a['total_cost']:.4f}",
            f"{a['avg_tokens']:.0f}", f"{a['avg_time_ms']:.0f}",
        ))


def print_by_category(rows: list[dict[str, Any]]) -> None:
    """Per-category breakdown, split by config."""
    _header("BY CATEGORY x CONFIG")
    categories = sorted({r["category"] for r in rows})
    configs = sorted({r["config_label"] for r in rows})

    fmt = "{:<15} {:<25} {:>5} {:>5} {:>6} {:>7} {:>9}"
    print(fmt.format("Category", "Config", "Runs", "Pass", "Rate", "AvgScr", "Cost$"))
    print("-" * W)
    for cat in categories:
        for cfg in configs:
            subset = [
                r for r in rows
                if r["category"] == cat and r["config_label"] == cfg
            ]
            if not subset:
                continue
            a = _agg(subset)
            print(fmt.format(
                cat, cfg, a["runs"], a["pass"], f"{a['rate']:.0%}",
                f"{a['avg_score']:.1f}", f"{a['total_cost']:.4f}",
            ))


def print_head_to_head(rows: list[dict[str, Any]]) -> None:
    """Per-task comparison across conditions, averaged over reps."""
    _header("HEAD-TO-HEAD (per task, averaged over reps)")

    configs = sorted({r["config_label"] for r in rows})

    # Accumulate all scores per (task, config), then average.
    task_cfg_scores: dict[str, dict[str, list[float]]] = {}
    for r in rows:
        tid = r["task_id"]
        cfg = r["config_label"]
        task_cfg_scores.setdefault(tid, {}).setdefault(cfg, []).append(
            r.get("eval_score", 0.0),
        )

    by_task: dict[str, dict[str, float]] = {}
    for tid, cfg_map in task_cfg_scores.items():
        by_task[tid] = {
            cfg: sum(scores) / len(scores) for cfg, scores in cfg_map.items()
        }

    # Header
    col_w = max(12, *(len(c) for c in configs))
    hdr = f"{'Task':<20}"
    for c in configs:
        hdr += f" {c:>{col_w}}"
    hdr += f" {'Best':>{col_w}}"
    print(hdr)
    print("-" * len(hdr))

    wins: dict[str, int] = {c: 0 for c in configs}
    for task_id in sorted(by_task):
        scores = by_task[task_id]
        line = f"{task_id:<20}"
        best_score = max(scores.values()) if scores else 0
        best_cfgs = [c for c, s in scores.items() if abs(s - best_score) < 0.5]
        for c in configs:
            s = scores.get(c, 0.0)
            line += f" {s:>{col_w}.1f}"
        if len(best_cfgs) == 1:
            line += f" {best_cfgs[0]:>{col_w}}"
            wins[best_cfgs[0]] += 1
        else:
            line += f" {'tie':>{col_w}}"
        print(line)

    print("-" * len(hdr))
    print("Wins: " + "  ".join(f"{c}={wins[c]}" for c in configs))


# ---------------------------------------------------------------------------
# Difficulty breakdown
# ---------------------------------------------------------------------------

# Tasks ending in -004/-005 are the new hard tasks; -003 and synthesis are also hard.
_HARD_TASKS = {
    "coding-004", "coding-005",
    "reasoning-003", "reasoning-004", "reasoning-005",
    "synthesis-001", "synthesis-002", "synthesis-003", "synthesis-004", "synthesis-005",
}


def _difficulty(task_id: str) -> str:
    return "hard" if task_id in _HARD_TASKS else "medium"


def print_by_difficulty(rows: list[dict[str, Any]]) -> None:
    """Show how each config performs on medium vs hard tasks."""
    _header("BY DIFFICULTY x CONFIG")
    configs = sorted({r["config_label"] for r in rows})

    fmt = "{:<10} {:<25} {:>5} {:>5} {:>6} {:>7} {:>9}"
    print(fmt.format("Difficulty", "Config", "Runs", "Pass", "Rate", "AvgScr", "Cost$"))
    print("-" * W)
    for diff in ("medium", "hard"):
        for cfg in configs:
            subset = [
                r for r in rows
                if _difficulty(r["task_id"]) == diff and r["config_label"] == cfg
            ]
            if not subset:
                continue
            a = _agg(subset)
            print(fmt.format(
                diff, cfg, a["runs"], a["pass"], f"{a['rate']:.0%}",
                f"{a['avg_score']:.1f}", f"{a['total_cost']:.4f}",
            ))


# ---------------------------------------------------------------------------
# Bootstrap confidence intervals
# ---------------------------------------------------------------------------


def _bootstrap_ci(
    values: list[float], n_resamples: int = 10_000, ci: float = 0.95,
) -> tuple[float, float, float]:
    """Bootstrap mean with confidence interval.

    Returns (mean, ci_low, ci_high).
    """
    if not values:
        return 0.0, 0.0, 0.0

    rng = random.Random(42)
    n = len(values)
    means: list[float] = []
    for _ in range(n_resamples):
        sample = [rng.choice(values) for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()

    alpha = (1 - ci) / 2
    lo_idx = int(alpha * n_resamples)
    hi_idx = int((1 - alpha) * n_resamples) - 1
    return sum(values) / n, means[lo_idx], means[hi_idx]


def print_bootstrap_cis(rows: list[dict[str, Any]]) -> None:
    """Bootstrap 95% CIs for mean eval_score per config."""
    groups = _group_by(rows, "config_label")
    n_per = len(next(iter(groups.values()), []))
    _header(f"BOOTSTRAP 95% CONFIDENCE INTERVALS (N={n_per} per config)")

    fmt = "{:<30} {:>7} {:>7} {:>7} {:>5}"
    print(fmt.format("Config", "Mean", "CI Low", "CI High", "N"))
    print("-" * 60)
    for label in sorted(groups):
        scores = [r.get("eval_score", 0.0) for r in groups[label]]
        mean, lo, hi = _bootstrap_ci(scores)
        print(fmt.format(label, f"{mean:.2f}", f"{lo:.2f}", f"{hi:.2f}", len(scores)))


# ---------------------------------------------------------------------------
# Quality per dollar
# ---------------------------------------------------------------------------


def print_quality_per_dollar(rows: list[dict[str, Any]]) -> None:
    """Quality per dollar: avg_score / total_cost."""
    _header("QUALITY PER DOLLAR")
    groups = _group_by(rows, "config_label")

    fmt = "{:<30} {:>7} {:>9} {:>12}"
    print(fmt.format("Config", "AvgScr", "Cost$", "Score/$"))
    print("-" * 60)
    for label in sorted(groups):
        a = _agg(groups[label])
        cost = a["total_cost"]
        qpd = a["avg_score"] / cost if cost > 0 else float("inf")
        print(fmt.format(
            label, f"{a['avg_score']:.2f}", f"{cost:.4f}", f"{qpd:.1f}",
        ))


# ---------------------------------------------------------------------------
# Market-specific analysis: calibration
# ---------------------------------------------------------------------------


def print_calibration(rows: list[dict[str, Any]]) -> None:
    """Calibration analysis: bid confidence vs realized eval score (market only)."""
    market_rows = [r for r in rows if r.get("topology_type") == "market"]
    if not market_rows:
        return

    _header("CALIBRATION ANALYSIS (market bids vs realized scores)")

    # Collect per-worker calibration data
    worker_data: dict[str, list[tuple[float, float]]] = {}
    for r in market_rows:
        bids = r.get("market_bids", [])
        winner = r.get("market_winner", "")
        score = r.get("eval_score", 0.0)

        for bid in bids:
            wid = bid.get("worker_id", "")
            p_success = bid.get("p_success", 0.5)
            if wid == winner:
                worker_data.setdefault(wid, []).append(
                    (p_success, score / 10.0)
                )

    if not worker_data:
        print("  No bid data available in this results file.")
        print("  Rerun the benchmark with the current code to populate calibration analysis.")
        return

    fmt = "{:<20} {:>5} {:>12} {:>12} {:>12}"
    print(fmt.format("Worker", "Tasks", "Avg Predict", "Avg Realized", "Calib Error"))
    print("-" * 65)
    for wid in sorted(worker_data):
        pairs = worker_data[wid]
        n = len(pairs)
        avg_pred = sum(p for p, _ in pairs) / n
        avg_real = sum(r for _, r in pairs) / n
        calib_err = abs(avg_pred - avg_real)
        print(fmt.format(wid, n, f"{avg_pred:.3f}", f"{avg_real:.3f}", f"{calib_err:.3f}"))

    # Per-task detail
    print()
    detail_fmt = "{:<20} {:<20} {:>10} {:>10} {:>8}"
    print(detail_fmt.format("Task", "Worker", "Predicted", "Realized", "Delta"))
    print("-" * 70)
    for r in market_rows:
        bids = r.get("market_bids", [])
        winner = r.get("market_winner", "")
        score = r.get("eval_score", 0.0)
        for bid in bids:
            wid = bid.get("worker_id", "")
            p_success = bid.get("p_success", 0.5)
            if wid == winner:
                delta = p_success - score / 10.0
                print(detail_fmt.format(
                    r["task_id"], wid,
                    f"{p_success:.3f}", f"{score / 10.0:.3f}", f"{delta:+.3f}",
                ))


# ---------------------------------------------------------------------------
# Market-specific: reputation trajectory
# ---------------------------------------------------------------------------


def print_reputation_trajectory(rows: list[dict[str, Any]]) -> None:
    """Show final market reputations and cross-reference with eval scores."""
    market_rows = [r for r in rows if r.get("topology_type") == "market"]
    if not market_rows:
        return

    _header("REPUTATION TRAJECTORY (market)")

    # Get final reputation from last market row
    last_row = market_rows[-1]
    reputations = last_row.get("market_reputation", {})
    if not reputations:
        print("  No reputation data available.")
        return

    # Compute per-worker average eval score (for tasks they won)
    worker_scores: dict[str, list[float]] = {}
    for r in market_rows:
        winner = r.get("market_winner", "")
        score = r.get("eval_score", 0.0)
        if winner:
            worker_scores.setdefault(winner, []).append(score)

    fmt = "{:<20} {:>10} {:>8} {:>10}"
    print(fmt.format("Worker", "Final Rep", "Wins", "Avg Score"))
    print("-" * 52)
    for wid in sorted(reputations):
        rep = reputations[wid]
        scores = worker_scores.get(wid, [])
        avg_score = sum(scores) / len(scores) if scores else 0.0
        print(fmt.format(wid, f"{rep:.3f}", len(scores), f"{avg_score:.1f}"))


# ---------------------------------------------------------------------------
# Shadow / routing accuracy
# ---------------------------------------------------------------------------


def print_routing_accuracy(rows: list[dict[str, Any]]) -> None:
    """Analyse routing accuracy on shadow tasks."""
    market_rows = [r for r in rows if r.get("topology_type") == "market"]
    shadow_rows = [r for r in market_rows if r.get("shadow_answers")]
    if not shadow_rows:
        return

    _header("ROUTING ACCURACY (shadow tasks)")

    correct_routes = 0
    total_shadow = len(shadow_rows)

    for r in shadow_rows:
        shadow = r["shadow_answers"]
        winner = r.get("market_winner", "")
        task_id = r["task_id"]

        # Find oracle (best scoring model)
        best_model = ""
        best_score = -1.0
        winner_score = 0.0

        print(f"\n  Task: {task_id} (market winner: {winner})")
        detail_fmt = "    {:<20} {:>8} {:>8}"
        print(detail_fmt.format("Model", "Score", "Winner?"))
        print("    " + "-" * 40)

        for entry in shadow:
            model = entry.get("model", "")
            score = entry.get("eval_score", 0.0)
            is_winner = entry.get("is_winner", False)
            print(detail_fmt.format(model, f"{score:.1f}", "***" if is_winner else ""))
            if score > best_score:
                best_score = score
                best_model = model
            if is_winner:
                winner_score = score

        oracle_label = best_model if best_model else "?"
        print(f"    Oracle pick: {oracle_label} ({best_score:.1f})")
        if abs(winner_score - best_score) < 0.5:
            correct_routes += 1
            print("    Routing: CORRECT (market matched oracle)")
        else:
            regret = best_score - winner_score
            print(f"    Routing: SUBOPTIMAL (regret = {regret:.1f})")

    print(f"\n  Overall: {correct_routes}/{total_shadow} shadow tasks routed to best model")

    # Parallel-3-pick baseline
    print()
    print("  Parallel-3-pick baseline (judge picks best of all 3 answers):")
    for r in shadow_rows:
        shadow = r["shadow_answers"]
        scores = [e.get("eval_score", 0.0) for e in shadow]
        best_of_3 = max(scores) if scores else 0.0
        winner_entry = [e for e in shadow if e.get("is_winner")]
        market_score = winner_entry[0].get("eval_score", 0.0) if winner_entry else 0.0
        print(
            f"    {r['task_id']}: parallel-3-pick={best_of_3:.1f}  "
            f"market={market_score:.1f}  "
            f"delta={best_of_3 - market_score:+.1f}"
        )


# ---------------------------------------------------------------------------
# Verdict (updated for 4+ conditions)
# ---------------------------------------------------------------------------


def print_verdict(rows: list[dict[str, Any]]) -> None:
    """Final summary verdict across all conditions."""
    _header("VERDICT")
    groups = _group_by(rows, "config_label")

    stats: dict[str, dict[str, Any]] = {}
    for label, label_rows in groups.items():
        stats[label] = _agg(label_rows)

    for label in sorted(stats):
        a = stats[label]
        cost = a["total_cost"]
        qpd = a["avg_score"] / cost if cost > 0 else float("inf")
        print(
            f"  {label:<30}  "
            f"pass={a['pass']}/{a['runs']} ({a['rate']:.0%})  "
            f"avg_score={a['avg_score']:.1f}  "
            f"cost=${cost:.4f}  "
            f"score/$={qpd:.1f}"
        )

    # Determine winner on eval_score
    by_score = sorted(stats.items(), key=lambda x: x[1]["avg_score"], reverse=True)
    best_label, best_s = by_score[0]
    runner_label, runner_s = by_score[1] if len(by_score) > 1 else (None, None)

    print()
    if runner_s and abs(best_s["avg_score"] - runner_s["avg_score"]) < 0.5:
        print("  Result: Too close to call on quality alone.")
        # Break tie on cost
        by_cost = sorted(stats.items(), key=lambda x: x[1]["total_cost"])
        cheapest = by_cost[0][0]
        print(f"  Cost edge: {cheapest} (${by_cost[0][1]['total_cost']:.4f})")
    else:
        delta = best_s["avg_score"] - (runner_s["avg_score"] if runner_s else 0)
        print(f"  Winner on quality: {best_label} (+{delta:.1f} avg score)")

    # Best value (highest score/dollar)
    by_value = sorted(
        stats.items(),
        key=lambda x: x[1]["avg_score"] / max(x[1]["total_cost"], 0.0001),
        reverse=True,
    )
    print(f"  Best value: {by_value[0][0]}")
    print("=" * W)


def export_csv(rows: list[dict[str, Any]], path: Path) -> None:
    """Export a summary CSV for further plotting."""
    groups = _group_by(rows, "config_label")
    fieldnames = [
        "config", "topology_type", "runs", "pass", "rate",
        "avg_score", "total_cost", "avg_tokens", "avg_time_ms",
    ]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for label in sorted(groups):
            a = _agg(groups[label])
            topo = groups[label][0]["topology_type"]
            writer.writerow({
                "config": label,
                "topology_type": topo,
                "runs": a["runs"],
                "pass": a["pass"],
                "rate": round(a["rate"], 3),
                "avg_score": round(a["avg_score"], 2),
                "total_cost": round(a["total_cost"], 6),
                "avg_tokens": round(a["avg_tokens"], 0),
                "avg_time_ms": round(a["avg_time_ms"], 0),
            })
    print(f"\nCSV exported to {path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyse hub-vs-spoke benchmark results")
    parser.add_argument("input", type=str, help="Path to JSONL results file")
    parser.add_argument("--csv", type=str, default=None, help="Export summary CSV")
    args = parser.parse_args()

    path = Path(args.input)
    if not path.exists():
        print(f"File not found: {path}")
        sys.exit(1)

    rows = load_results(path)
    if not rows:
        print("No results found in file.")
        sys.exit(1)

    print(f"Loaded {len(rows)} results from {path}")

    # Standard analysis
    print_by_topology(rows)
    print_by_config(rows)
    print_by_category(rows)
    print_head_to_head(rows)

    # Difficulty breakdown
    print_by_difficulty(rows)

    # New analyses
    print_bootstrap_cis(rows)
    print_quality_per_dollar(rows)

    # Market-specific
    print_calibration(rows)
    print_reputation_trajectory(rows)
    print_routing_accuracy(rows)

    # Final verdict
    print_verdict(rows)

    if args.csv:
        export_csv(rows, Path(args.csv))


if __name__ == "__main__":
    main()
