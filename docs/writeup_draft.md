# Draft: Markets Beat Hierarchies, But Not Solo Experts

If you can call multiple LLMs, should you use one strong model, have one model orchestrate several others, or let several models compete for work?

That is the question behind this benchmark. I tested three orchestration strategies on the same tasks:

- `Solo`: one strong model answers directly.
- `Hub-Spoke`: one model decomposes the task, delegates work to specialists, and synthesizes the result.
- `Agent Economy`: multiple models bid for tasks, and a clearinghouse routes work using confidence and reputation.

This writeup refers to the 15-task full run saved in `results/hard_run.jsonl` and `results/hard_summary.csv`. In that run, the market matched the solo baseline on average quality, beat it on total cost, and clearly beat hub-spoke on cost. The solo baseline still held the lead on coding tasks, and hub-spoke remained the weakest overall condition. The cleanest summary is still the same: markets beat hierarchies, but they did not beat a strong solo expert.

## What Was Tested

All three strategies were evaluated on the same benchmark suite: 15 hand-written tasks spanning coding, reasoning, and synthesis.

The coding tasks focused on direct implementation and debugging work, including an interval store, a sliding-window bug fix, a refactoring exercise, an LRU cache, and async concurrency bugs.

The reasoning tasks focused on constrained problem solving: combinatorics, scheduling under constraints, causal chain analysis, a logic-grid puzzle, and a constrained magic square.

The synthesis tasks focused on judgment and explanation: distributed consistency tradeoffs, monorepo versus polyrepo arguments, explaining Raft to different audiences, EHR architecture, and a critique of the claim that microservices are always better than monoliths.

These are useful tests because they probe different kinds of intellectual work under a shared scoring setup. They are still modest in scope. They are not end-to-end product tasks, and they should be read as a focused benchmark of coordination patterns under controlled conditions.

## How It Was Run

The run used 15 tasks with 3 repetitions per strategy, for 135 scored runs.

The three strategies were:

- `Solo (Opus 4.6)`: one strong model answers each task directly.
- `Hub-Spoke`: an Opus hub decomposes the task, delegates to GPT-5.2 workers, synthesizes their outputs, gets a red-team critique, and revises.
- `Agent Economy`: GPT-5.2, Opus 4.6, and GPT-5-mini bid for each task through the `agent-economy` clearinghouse; the winner executes, and reputation evolves across the session.

Each answer was scored either by exact match or by an LLM judge using a task-specific rubric. One task, the probability problem, used deterministic exact-match grading. The rest used rubric-based evaluation. A pass means a score of at least 7 out of 10.

I also tracked token usage, estimated dollar cost, pass rate, and wall-clock time. For a small set of shadow tasks, I ran the non-winning market models as well so I could check how often the market had routed to the best available answer.

One important caveat sits underneath all of this: the benchmark compares coordination quality and cost, not real parallel speedups. The multi-agent flows are logically multi-agent, but operationally they still execute serially in this repo.

## Full-Run Results

The main table from the 15-task full run is straightforward:

| Strategy | Avg score | Pass rate | Total cost | Score per dollar |
|---|---:|---:|---:|---:|
| Agent Economy | 7.2 | 76% (34/45) | $1.34 | 5.4 |
| Solo (Opus 4.6) | 7.2 | 73% (33/45) | $1.69 | 4.2 |
| Hub-Spoke | 6.7 | 67% (30/45) | $5.33 | 1.3 |

The most important fact is that the market and the solo baseline tied on overall quality. Both averaged 7.2. That matters because a lot of multi-agent discussion assumes coordination will beat a single strong model on raw output quality. In this benchmark, it did not.

The market was still cheaper. It matched solo's quality while costing about 21% less overall. Hub-spoke went the other direction: it cost about 4x more than the market and a little over 3x more than solo, while also scoring worse.

The quality tie also needs to be stated carefully. The bootstrap confidence intervals overlap: market [6.1, 8.2], solo [6.3, 8.0], hub-spoke [5.8, 7.5]. That means the overall quality ranking is not statistically clean. The stronger signals are in category-level behavior and cost.

## Where Each Strategy Helped

The category averages from the full run are where the benchmark becomes more informative:

| Task type | Agent Economy | Solo (Opus 4.6) | Hub-Spoke |
|---|---:|---:|---:|
| Coding | 6.7 | 8.4 | 7.9 |
| Reasoning | 7.1 | 5.1 | 5.2 |
| Synthesis | 7.7 | 8.1 | 6.9 |

On coding tasks, a single strong model was best. That includes data structures, debugging, and refactoring. Solo won clearly, and hub-spoke landed in the middle.

On reasoning tasks, the market had the strongest average. A cautious read is that the bidding and retry flow helped on some tasks that punish overconfident first passes. A large share of that edge came from one exact-match probability problem that the market solved in all three repetitions while the other two conditions missed it every time.

On synthesis tasks, solo edged out the market. That suggests explanation and tradeoff analysis may still benefit from a single coherent voice more than from coordination machinery.

## What The Market Actually Learned

The market had three participants: GPT-5.2, Opus 4.6, and GPT-5-mini.

In the full run, GPT-5.2 handled 28 market tasks, Opus 4.6 handled 11, six runs ended with no filled task, and GPT-5-mini handled none. That is an important detail. The market did filter out the weakest worker, but it also failed to complete a meaningful number of runs.

That makes the result more modest than the grandest version of the "agent economy" story. This was not a rich ecosystem of specialists. It was closer to a coarse filter that removed the weakest model, leaned heavily toward GPT-5.2, and occasionally routed to Opus.

The shadow-task checks point in the same direction. On 15 shadow routing checks, the market matched the oracle choice 12 times, or 80%. One miss was a clear wrong-model pick: on `reasoning-004` rep 0, the market picked Opus 4.6 and scored 3, while GPT-5.2 would have scored 9. The other two misses were not wrong-model picks so much as task-fill failures: the shadow pool contained a 9-point answer, but the executed market path returned 0.

That is useful, but it is not magic. The market looked directionally helpful as a router, not precise enough to claim strong task-type specialization.

## Why Hub-Spoke Struggled

Hub-spoke makes many more calls. It decomposes, delegates, waits, synthesizes, critiques, and revises. That creates more opportunities for drift, verbosity, and token spend. In this benchmark, those extra steps mostly increased cost.

It is also worth being fair here. Hub-spoke was not uniformly bad on every single task. It won `coding-003`, `reasoning-002`, and `reasoning-004` in the full run. The problem is that those wins were not large or frequent enough to pay for the coordination tax.

The broader lesson is that coordination has to earn its keep. If decomposition is weak, or the task does not naturally break into parallel subproblems, then the system is just paying for a lot of internal conversation.

## Caveats

This benchmark has real limits, and they matter.

The overall quality tie between market and solo should be described as a tie, not a proof that the two systems are equivalent. The confidence intervals overlap, and the benchmark is still fairly small.

One reasoning task drives a large share of the market's reasoning edge. `reasoning-001` matters a lot to the category story.

The judge model is also a participant in the market condition. GPT-5.2 both competed and judged, which leaves room for style bias even without intentional favoritism.

The task set is varied, but still modest. This is a benchmark of prompt-based intellectual tasks under controlled scoring. It is not a benchmark of long-running tool-using agents operating inside a real production workflow.

## Working Headline

If I wanted one paragraph that stayed close to the data, I would use this:

> In a 15-task benchmark spanning coding, reasoning, and synthesis, a market-style multi-model system matched the best single-model baseline on overall quality while costing less, whereas a hub-and-spoke coordination pattern was substantially more expensive and somewhat worse. The market's strength was efficiency, not a higher quality ceiling: it helped most on constrained reasoning tasks, while a single strong model remained best on coding tasks.

And if I wanted one sentence:

> Markets beat hierarchies, but not solo experts.

## Practical Takeaways

If your workload looks mostly like coding, start with one strong model.

If your workload includes tricky reasoning where first-pass overconfidence hurts, a routing layer may be worth testing.

If you are tempted by elaborate hub-and-spoke agent systems, ask whether the task really decomposes into separable subproblems.

## Best Next Upgrade

If this turns into a public post, the strongest next upgrade would be a fresh rerun with an independent judge, a stronger third competitor, and result files that include the bid-calibration fields now expected by the analysis script.
