"""Grade Fable's one-shot answers with the repo's own evaluation stack:
GPT-5.2 judge (temperature 0, same rubric, pass = score >= 7) for llm_judge
tasks, DeterministicEvaluator.exact_match for exact_match tasks."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

HVS_ROOT = Path("/Users/rohit/Documents/Workspace/Coding/hub_vs_spoke")
sys.path.insert(0, str(HVS_ROOT / "src"))

from dotenv import load_dotenv

load_dotenv(HVS_ROOT / ".env")

from hub_vs_spoke.config import Settings
from hub_vs_spoke.evaluation.deterministic import DeterministicEvaluator
from hub_vs_spoke.evaluation.judge import LLMJudge
from hub_vs_spoke.providers.openai_provider import OpenAIProvider

OUT_DIR = Path(__file__).resolve().parent


async def main() -> None:
    meta = json.loads((OUT_DIR / "tasks_meta.json").read_text())
    judge = LLMJudge(provider=OpenAIProvider(model=Settings().judge_model))

    async def grade(m: dict) -> dict:
        tid = m["task_id"]
        answer = (OUT_DIR / f"answer_{tid}.md").read_text(encoding="utf-8")
        prompt = (OUT_DIR / f"solve_{tid}.txt").read_text(encoding="utf-8")
        if m["eval_method"] == "exact_match":
            res = DeterministicEvaluator.exact_match(answer, m["expected_answer"])
            score = 10.0 if res["match"] else 0.0
            outcome = int(res["match"])
            reasoning = f"exact_match expected={m['expected_answer']}"
        else:
            res = await judge.score_absolute(prompt, answer, m["eval_rubric"])
            score = float(res["score"])
            outcome = int(score >= 7)
            reasoning = res["reasoning"]
        return {
            "task_id": tid,
            "eval_method": m["eval_method"],
            "eval_score": score,
            "outcome": outcome,
            "judge_reasoning": reasoning,
            "answer_chars": len(answer),
        }

    rows = await asyncio.gather(*(grade(m) for m in meta))
    with (OUT_DIR / "grades.jsonl").open("w") as f:
        for r in sorted(rows, key=lambda x: x["task_id"]):
            f.write(json.dumps(r) + "\n")
            print(f"{r['task_id']:16s} score={r['eval_score']:>4.1f} outcome={r['outcome']}")


if __name__ == "__main__":
    asyncio.run(main())
