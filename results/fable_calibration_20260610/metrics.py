"""Join Fable's forecasts with graded outcomes; compute Brier/ECE via
agent-economy's summarize_calibration; compare against hard_run baselines."""
# ruff: noqa: E402
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean

HVS_ROOT = Path("/Users/rohit/Documents/Workspace/Coding/hub_vs_spoke")
AE_ROOT = Path("/Users/rohit/Documents/Workspace/Coding/agent-economy")
sys.path.insert(0, str(AE_ROOT))

from agent_economy.research.calibration_metrics import summarize_calibration

OUT_DIR = Path(__file__).resolve().parent

FORECASTS = {
    "coding-001": (0.96, 1200),
    "coding-002": (0.97, 900),
    "coding-003": (0.92, 2200),
    "coding-004": (0.97, 1500),
    "coding-005": (0.70, 2600),
    "reasoning-001": (0.96, 700),
    "reasoning-002": (0.96, 700),
    "reasoning-003": (0.88, 1600),
    "reasoning-004": (0.65, 6000),
    "reasoning-005": (0.60, 3500),
    "synthesis-001": (0.85, 5000),
    "synthesis-002": (0.85, 2600),
    "synthesis-003": (0.85, 1400),
    "synthesis-004": (0.78, 5000),
    "synthesis-005": (0.85, 2600),
}


def main() -> None:
    grades = {
        r["task_id"]: r
        for r in (json.loads(line) for line in (OUT_DIR / "grades.jsonl").open())
    }
    records = []
    for tid, (p, tok) in FORECASTS.items():
        g = grades[tid]
        records.append(
            {
                "benchmark": "hub_vs_spoke",
                "task_id": tid,
                "model_ref": "cursor:fable-5",
                "strategy": "direct",
                "p_success": p,
                "estimated_tokens_total": tok,
                "outcome": g["outcome"],
                "eval_score": g["eval_score"],
                "input_tokens": 0,
                "output_tokens": 0,
            }
        )
    with (OUT_DIR / "fable_calibration_results.jsonl").open("w") as f:
        for r in sorted(records, key=lambda x: x["task_id"]):
            f.write(json.dumps(r) + "\n")

    summary = summarize_calibration(records)
    (OUT_DIR / "metrics_summary.json").write_text(json.dumps(summary, indent=2))

    # Baseline per-task pass rates from the original hard run.
    base = [json.loads(line) for line in (HVS_ROOT / "results/hard_run.jsonl").open()]
    by_cond_task: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for r in base:
        by_cond_task[r["config_label"]][r["task_id"]].append(int(r["eval_match"]))

    print(f"{'task':16s} {'fable p':>7s} {'score':>5s} {'out':>3s}", end="")
    conds = sorted(by_cond_task)
    for c in conds:
        print(f" {c[:14]:>14s}", end="")
    print()
    for r in sorted(records, key=lambda x: x["task_id"]):
        print(
            f"{r['task_id']:16s} {r['p_success']:>7.2f} "
            f"{r['eval_score']:>5.1f} {r['outcome']:>3d}",
            end="",
        )
        for c in conds:
            vals = by_cond_task[c][r["task_id"]]
            print(f" {mean(vals):>14.0%}", end="")
        print()

    overall = summary["overall"]
    print()
    print(f"n = {overall['count']}")
    print(f"Fable pass rate:    {overall['accuracy']:.3f}")
    print(f"Fable mean p:       {mean(r['p_success'] for r in records):.3f}")
    print(f"Fable Brier:        {overall['brier']:.4f}")
    print(f"Fable ECE:          {overall['ece']:.4f}")
    base_rate = overall["accuracy"]
    # Brier skill vs always-guessing-own-base-rate
    ref = base_rate * (1 - base_rate)
    print(f"Brier skill vs base-rate forecaster: {1 - overall['brier'] / ref:+.3f}")
    no_artifact = [r for r in records if r["task_id"] != "reasoning-001"]
    s2 = summarize_calibration(no_artifact)["overall"]
    print(f"Excl. reasoning-001 latex artifact: brier={s2['brier']:.4f} ece={s2['ece']:.4f}")
    print()
    for c in conds:
        all_vals = [v for t in by_cond_task[c].values() for v in t]
        print(f"baseline {c:20s} pass rate: {mean(all_vals):.3f}")


if __name__ == "__main__":
    main()
