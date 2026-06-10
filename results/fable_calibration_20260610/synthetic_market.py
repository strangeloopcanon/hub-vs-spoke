"""Synthetic 'Fable-included market' counterfactual.

The original hard_run logged no bid-level data, so this is not an auction
replay. Instead: route each task by Fable's own stated confidence (its bid),
which is the allocation a price-aware clearinghouse would converge to given
Fable's premium pricing.

Variants:
  A (bid-routed):     p_fable >= 0.75 -> cheap pool (original market result),
                      else Fable executes (measured outcome).
  B (bid-routed 0.85): same with threshold 0.85.
  C (outcome-history): allocator also knows per-task market priors and sends
                      any task the market ever failed to Fable. Upper bound;
                      uses cross-rep history a single session would not have.

Outcomes/costs: market side from results/hard_run.jsonl (3 reps, averaged);
Fable side from the measured one-shot run (grades.jsonl + answer files at
$10/$50 per Mtok, chars/4 token estimate).
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from statistics import mean

HVS = Path("/Users/rohit/Documents/Workspace/Coding/hub_vs_spoke")
OUT = Path(__file__).resolve().parent

FABLE_P = {
    "coding-001": 0.96, "coding-002": 0.97, "coding-003": 0.92,
    "coding-004": 0.97, "coding-005": 0.70,
    "reasoning-001": 0.96, "reasoning-002": 0.96, "reasoning-003": 0.88,
    "reasoning-004": 0.65, "reasoning-005": 0.60,
    "synthesis-001": 0.85, "synthesis-002": 0.85, "synthesis-003": 0.85,
    "synthesis-004": 0.78, "synthesis-005": 0.85,
}


def fable_task_cost(tid: str) -> float:
    ans = (OUT / f"answer_{tid}.md").read_text(encoding="utf-8")
    prompt = (OUT / f"solve_{tid}.txt").read_text(encoding="utf-8")
    return (len(prompt) / 4) / 1e6 * 10 + (len(ans) / 4) / 1e6 * 50


def main() -> None:
    grades = {r["task_id"]: r for r in map(json.loads, (OUT / "grades.jsonl").open())}
    rows = [json.loads(l) for l in (HVS / "results/hard_run.jsonl").open()]
    mkt = defaultdict(list)
    for r in rows:
        if r["config_label"] == "agent-economy":
            mkt[r["task_id"]].append(r)

    market = {
        tid: {
            "score": mean(x["eval_score"] for x in rs),
            "pass": mean(float(x["eval_match"]) for x in rs),
            "cost": mean(x["total_cost_usd"] for x in rs),
        }
        for tid, rs in mkt.items()
    }
    fable = {
        tid: {
            "score": grades[tid]["eval_score"],
            "pass": float(grades[tid]["outcome"]),
            "cost": fable_task_cost(tid),
        }
        for tid in FABLE_P
    }
    # Fable's bidding overhead: 15 forecast calls, ~1k tokens each, mostly input.
    bid_overhead = 15 * (1000 / 1e6 * 10 + 200 / 1e6 * 50)

    def variant(name: str, to_fable: set[str]) -> dict:
        score = mean(
            (fable if t in to_fable else market)[t]["score"] for t in FABLE_P
        )
        pas = mean((fable if t in to_fable else market)[t]["pass"] for t in FABLE_P)
        cost = (
            sum((fable if t in to_fable else market)[t]["cost"] for t in FABLE_P)
            + bid_overhead
        )
        return {
            "variant": name, "fable_tasks": sorted(to_fable),
            "avg_score": round(score, 2), "pass_rate": round(pas, 3),
            "cost_per_rep": round(cost, 2), "score_per_usd": round(score / cost, 1),
        }

    variants = [
        variant("A bid-routed p<0.75", {t for t, p in FABLE_P.items() if p < 0.75}),
        variant("B bid-routed p<0.85", {t for t, p in FABLE_P.items() if p < 0.85}),
        variant(
            "C outcome-history",
            {t for t in FABLE_P if market[t]["pass"] < 1.0},
        ),
    ]

    refs = {
        "market (original)": {
            "avg_score": round(mean(m["score"] for m in market.values()), 2),
            "pass_rate": round(mean(m["pass"] for m in market.values()), 3),
            "cost_per_rep": round(sum(m["cost"] for m in market.values()), 2),
        },
        "solo Fable (measured)": {
            "avg_score": round(mean(f["score"] for f in fable.values()), 2),
            "pass_rate": round(mean(f["pass"] for f in fable.values()), 3),
            "cost_per_rep": round(sum(f["cost"] for f in fable.values()), 2),
        },
    }
    for k, v in refs.items():
        v["score_per_usd"] = round(v["avg_score"] / v["cost_per_rep"], 1)
        print(f"{k:24s} {v}")
    for v in variants:
        print(f"{v['variant']:24s} score={v['avg_score']} pass={v['pass_rate']:.0%} "
              f"cost=${v['cost_per_rep']} score/$={v['score_per_usd']} "
              f"fable_tasks={v['fable_tasks']}")

    (OUT / "synthetic_market_summary.json").write_text(
        json.dumps({"references": refs, "variants": variants}, indent=2)
    )


if __name__ == "__main__":
    main()
