"""Build MarketBench-style direct calibration prompts and solver task files for
the 15 hub_vs_spoke benchmark tasks, for elicitation/solving by Fable 5 subagents.

Uses agent-economy's build_calibration_prompt verbatim so the elicitation format
matches the phase-1 MarketBench experiment exactly.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HVS_ROOT = Path("/Users/rohit/Documents/Workspace/Coding/hub_vs_spoke")
AE_ROOT = Path("/Users/rohit/Documents/Workspace/Coding/agent-economy")
sys.path.insert(0, str(HVS_ROOT / "src"))
sys.path.insert(0, str(AE_ROOT))

from agent_economy.research.calibration import PromptStrategy, build_calibration_prompt
import hub_vs_spoke.tasks.coding  # noqa: F401  (populates registry)
import hub_vs_spoke.tasks.reasoning  # noqa: F401
import hub_vs_spoke.tasks.synthesis  # noqa: F401
from hub_vs_spoke.tasks.base import EvalMethod, default_registry

OUT_DIR = Path(__file__).resolve().parent


def acceptance_for(task) -> list[str]:
    if task.eval_method == EvalMethod.EXACT_MATCH:
        return [
            "EXACT_MATCH: your final answer must contain the exact expected answer string"
        ]
    return [
        "LLM_JUDGE: a GPT-5.2 judge (temperature 0) scores your single answer "
        "against a hidden rubric; pass requires score >= 7/10"
    ]


def main() -> None:
    tasks = default_registry.all_tasks()
    assert len(tasks) == 15, f"expected 15 tasks, got {len(tasks)}"
    meta = []
    for t in sorted(tasks, key=lambda x: x.task_id):
        prompt = build_calibration_prompt(
            task_id=t.task_id,
            task_title=t.description or t.task_id,
            task_description=t.prompt,
            acceptance_commands=acceptance_for(t),
            strategy=PromptStrategy.DIRECT,
        )
        (OUT_DIR / f"elicit_{t.task_id}.txt").write_text(prompt, encoding="utf-8")
        (OUT_DIR / f"solve_{t.task_id}.txt").write_text(t.prompt, encoding="utf-8")
        meta.append(
            {
                "task_id": t.task_id,
                "category": str(t.category),
                "difficulty": t.difficulty,
                "eval_method": str(t.eval_method),
                "expected_answer": t.expected_answer,
                "eval_rubric": t.eval_rubric,
            }
        )
    (OUT_DIR / "tasks_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"Wrote {len(meta)} elicit/solve files to {OUT_DIR}")
    for m in meta:
        print(f"  {m['task_id']:16s} {m['category']:10s} {m['difficulty']:6s} {m['eval_method']}")


if __name__ == "__main__":
    main()
