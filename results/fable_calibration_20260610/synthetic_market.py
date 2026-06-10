"""Synthetic 'Fable-included market' counterfactuals.

No bid-level data exists for the original hard_run, and the frontier CLI run
has one rep, so these are splices, not auction replays: each task routes
either to the base market (its measured result) or to Fable (its measured
one-shot result), and each side is charged its measured execution cost, plus
Fable's bidding overhead.

Bases:
  original  results/hard_run.jsonl agent-economy rows (3 reps, averaged)
  frontier  results/frontier_cli_market_20260610_corrected.jsonl (1 rep:
            Opus 4.7-thinking via Cursor CLI, GPT-5.5 via Codex, GPT-5-mini)

Routing variants per base:
  bid-routed p<0.75 / p<0.85  task goes to Fable when Fable's own bid is low
  no-fill backstop            Fable takes only tasks the base market left
                              unfilled (frontier base only)
  outcome-routed              Fable takes every task the base market failed;
                              uses outcome history a single session would not
                              have, so it is a ceiling for reputation routing

Costs use the repo's execution-cost convention (winner tokens only), matching
the published hard_run numbers. The frontier session additionally spent ~$6 on
bid calls across all workers; see README caveat.
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

# 15 forecast calls, ~1k input + ~200 output tokens each at $10/$50 per Mtok.
BID_OVERHEAD = 15 * (1000 / 1e6 * 10 + 200 / 1e6 * 50)


def fable_task_cost(tid: str) -> float:
    ans = (OUT / f"answer_{tid}.md").read_text(encoding="utf-8")
    prompt = (OUT / f"solve_{tid}.txt").read_text(encoding="utf-8")
    return (len(prompt) / 4) / 1e6 * 10 + (len(ans) / 4) / 1e6 * 50


def load_bases() -> dict[str, dict[str, dict]]:
    rows = [json.loads(l) for l in (HVS / "results/hard_run.jsonl").open()]
    by_task = defaultdict(list)
    for r in rows:
        if r["config_label"] == "agent-economy":
            by_task[r["task_id"]].append(r)
    original = {
        tid: {
            "score": mean(x["eval_score"] for x in rs),
            "pass": mean(float(x["eval_match"]) for x in rs),
            "cost": mean(x["total_cost_usd"] for x in rs),
            "no_fill": False,
        }
        for tid, rs in by_task.items()
    }
    frows = [
        json.loads(l)
        for l in (HVS / "results/frontier_cli_market_20260610_corrected.jsonl").open()
    ]
    frontier = {
        r["task_id"]: {
            "score": float(r["eval_score"]),
            "pass": float(r["eval_match"]),
            "cost": float(r["total_cost_usd"]),
            "no_fill": r["market_winner"] == "unknown",
        }
        for r in frows
    }
    return {"original": original, "frontier": frontier}


def main() -> None:
    grades = {r["task_id"]: r for r in map(json.loads, (OUT / "grades.jsonl").open())}
    fable = {
        tid: {
            "score": grades[tid]["eval_score"],
            "pass": float(grades[tid]["outcome"]),
            "cost": fable_task_cost(tid),
        }
        for tid in FABLE_P
    }
    bases = load_bases()

    def splice(base: dict[str, dict], to_fable: set[str]) -> dict:
        pick = lambda t: fable[t] if t in to_fable else base[t]
        score = mean(pick(t)["score"] for t in FABLE_P)
        cost = sum(pick(t)["cost"] for t in FABLE_P) + BID_OVERHEAD
        return {
            "fable_tasks": sorted(to_fable),
            "avg_score": round(score, 2),
            "pass_rate": round(mean(pick(t)["pass"] for t in FABLE_P), 3),
            "cost_per_rep": round(cost, 2),
            "score_per_usd": round(score / cost, 1),
        }

    report: dict[str, dict] = {"references": {}, "variants": {}}
    for name, base in bases.items():
        report["references"][f"{name} market (measured)"] = {
            "avg_score": round(mean(b["score"] for b in base.values()), 2),
            "pass_rate": round(mean(b["pass"] for b in base.values()), 3),
            "cost_per_rep": round(sum(b["cost"] for b in base.values()), 2),
        }
        variants = {
            "bid-routed p<0.75": {t for t, p in FABLE_P.items() if p < 0.75},
            "bid-routed p<0.85": {t for t, p in FABLE_P.items() if p < 0.85},
            "outcome-routed": {t for t in FABLE_P if base[t]["pass"] < 1.0},
        }
        if any(b["no_fill"] for b in base.values()):
            variants["no-fill backstop"] = {t for t in FABLE_P if base[t]["no_fill"]}
        report["variants"][name] = {
            vname: splice(base, ts) for vname, ts in variants.items()
        }

    report["references"]["solo Fable 5 (measured)"] = {
        "avg_score": round(mean(f["score"] for f in fable.values()), 2),
        "pass_rate": round(mean(f["pass"] for f in fable.values()), 3),
        "cost_per_rep": round(sum(f["cost"] for f in fable.values()), 2),
    }
    for v in report["references"].values():
        v["score_per_usd"] = round(v["avg_score"] / v["cost_per_rep"], 1)

    (OUT / "synthetic_market_summary.json").write_text(json.dumps(report, indent=2))

    for k, v in report["references"].items():
        print(f"{k:34s} score={v['avg_score']} pass={v['pass_rate']:.0%} "
              f"cost=${v['cost_per_rep']} score/$={v['score_per_usd']}")
    for base_name, vs in report["variants"].items():
        for vname, v in vs.items():
            print(f"{base_name}+fable {vname:20s} score={v['avg_score']} "
                  f"pass={v['pass_rate']:.0%} cost=${v['cost_per_rep']} "
                  f"score/$={v['score_per_usd']} fable={v['fable_tasks']}")


if __name__ == "__main__":
    main()
