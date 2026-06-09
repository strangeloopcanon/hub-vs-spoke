# Data Consistency Strategy for a 50k TPS Distributed Payment System

## Framing the problem

At 50,000 transactions per second, the dominant constraints are: (1) no synchronous coordination protocol can be on the hot path if it holds locks across services, (2) money movement demands auditability and exactly-once *effects* even when delivery is at-least-once, and (3) the failure mode that matters most is partial failure mid-transaction (debit succeeded, credit didn't). With those constraints in mind:

---

## (a) Two-Phase Commit (2PC)

**Throughput under load.**
2PC requires a prepare round and a commit round, with every participant holding locks (or at least write intents) between them. Latency per transaction is at minimum two sequential round trips to all participants plus durable logging at coordinator and participants (typically 4+ fsyncs). The real killer is not the latency of one transaction but the *lock hold time*: locks are held for the full duration of the protocol, so throughput on contended rows (e.g., a popular merchant account) collapses as concurrency rises. Queueing theory bites hard: at 50k TPS, even a 10ms lock window on a hot account caps that account at ~100 TPS and creates convoys. Practical systems that do scale 2PC (e.g., Spanner) do so by combining it with Paxos-replicated participants, TrueTime, and heavy engineering — not something a startup replicates. Vanilla 2PC across heterogeneous services (payment gateway, ledger, fraud, notification) at 50k TPS is not realistic.

**Consistency guarantees and limits.**
The strongest of the three on paper: atomic commitment — all participants commit or all abort, giving serializable-style atomicity if participants use proper locking. The limits:
- 2PC is an *atomic commitment* protocol, not a consensus protocol; it is **blocking**. If the coordinator dies after participants have voted "yes," participants are stuck in-doubt, holding locks, until the coordinator recovers. Availability and consistency are traded exactly as CAP predicts.
- Heuristic decisions (a participant unilaterally commits/aborts to escape an in-doubt state) silently break atomicity — and these are common operational escape hatches in real XA deployments.
- Guarantees only hold if every participant genuinely supports XA/prepare semantics; many SaaS dependencies (card networks, banking partners) do not, so the "transaction" boundary leaks anyway.

**Failure recovery.**
Coordinator failure → in-doubt transactions blocking resources until recovery; requires durable coordinator logs and recovery protocols. Participant failure during prepare → abort (fine). Participant failure after vote → must replay from log on restart. Recovery is automatic in theory but in practice in-doubt transactions are a notorious source of manual DBA intervention (XA "stuck transaction" pages are a genre of ops runbook).

**Operational complexity.**
Deceptively low at small scale ("the database handles it"), high at this scale: XA driver quirks, heuristic outcome reconciliation, coordinator HA, lock-contention firefighting, and the inability to do rolling deploys of participants without draining in-flight transactions. Also couples all services to a shared transactional substrate, which fights service autonomy.

---

## (b) Saga pattern with compensating transactions

**Throughput under load.**
Excellent. A saga is a sequence of *local* transactions, each committing immediately; no cross-service locks, no global coordinator on the hot path. Each step is a local ACID commit plus an async message (typically via the transactional outbox pattern). Throughput scales horizontally with partitioning (e.g., Kafka partitioned by account/payment ID). 50k TPS is well within the demonstrated range of this architecture — it is essentially how large payment processors actually run.

**Consistency guarantees and limits.**
Sagas give you *eventual consistency* with **semantic atomicity**: either all steps complete, or compensations undo the completed ones. Crucial limits:
- **No isolation** (the "I" in ACID is gone). Intermediate states are visible: another process can observe an account after debit but before credit. You must counter this with semantic locks (e.g., funds in `PENDING` state), commutative operations, or version checks — these countermeasures are design work, not free.
- **Compensation ≠ rollback.** A compensating transaction is a new forward action (refund, reversal) and may itself fail, may not be perfectly inverse (fees, FX rates moved), and some actions are not compensatable (an external payout already settled) — those must be ordered last ("pivot" step).
- Requires idempotency keys everywhere, since retries are how progress is guaranteed.
Notably, this mirrors how money *actually* works: real-world finance is built on reversals and chargebacks, not distributed locks, so the model is domain-appropriate.

**Failure recovery.**
Well-defined: forward recovery (retry the failed step) or backward recovery (run compensations in reverse order). The saga's state must be durably tracked (orchestrator state machine, e.g., Temporal/ Camunda /a hand-rolled state table, or choreography via events). Recovery is automatic and non-blocking — failures of one saga don't hold locks that stall others. The hazards are stuck sagas (need timeouts + alerting), compensation failures (need dead-letter queues + manual ops UI), and orchestrator outages (mitigated because state is durable; workers just resume).

**Operational complexity.**
Moderate and *explicit*. You must build/operate: a message broker, outbox relays, an orchestrator or carefully designed choreography, idempotency storage, and reconciliation jobs. Debugging spans services, so you need correlation IDs and tracing. The complexity is real but it is visible, testable complexity — versus 2PC's complexity which hides until an outage.

---

## (c) Event sourcing with CQRS

**Throughput under load.**
Very high on the write path: appending immutable events to a log is the cheapest durable write there is, and partitioning by aggregate (account/payment) scales linearly. 50k TPS appends are comfortably achievable with Kafka/EventStore-class infrastructure. Two caveats: (1) per-aggregate throughput is limited by optimistic-concurrency on the aggregate's event stream — hot accounts again need design care (sharded balances, buckets); (2) the *read* side is asynchronous — projections lag the log, so reads are stale by replication lag (typically ms, occasionally seconds during incidents).

**Consistency guarantees and limits.**
Strong consistency *within* an aggregate (the event stream is the serialized truth, enforced by expected-version checks); eventual consistency *across* aggregates and on all CQRS read models. Limits:
- A payment touching two aggregates (payer, payee) still needs a cross-aggregate coordination mechanism — which is… a saga / process manager. Event sourcing does not by itself solve the distributed-transaction problem; it changes the substrate.
- Read-your-writes is not guaranteed on the query side without extra machinery (e.g., version-tagged reads), which confuses both users and downstream services.
- Schema/versioning of events is a long-term contract: upcasters, event version migrations, and replay correctness become permanent engineering obligations.

**Failure recovery.**
The best story of the three *forensically*: the event log is a perfect audit trail (a gift for payments compliance — it is literally double-entry-ledger-shaped), projections can be rebuilt from scratch after corruption, and temporal debugging ("what did the world look like at 14:32?") is native. But: projection rebuilds at billions of events take hours-to-days unless you maintain snapshots; bugs in event handlers can require re-emission/compensating events (you can never "fix" history, only append corrections); and exactly-once projection updates need careful checkpointing.

**Operational complexity.**
The highest of the three. You take on: event store operations, projection lifecycle management, snapshotting, event schema evolution, replay tooling, *and* (because of the cross-aggregate point above) a saga layer anyway. The team-skill requirement is the real cost — event sourcing done by a team learning it on the job is a well-documented source of multi-year regret. It pays off most precisely in domains like ledgers, where immutability and audit are requirements rather than nice-to-haves.

---

## Comparison summary

| Criterion | 2PC | Saga | ES + CQRS |
|---|---|---|---|
| Throughput at 50k TPS | Poor (lock convoys, blocking) | Excellent (local commits, partitioned) | Excellent writes; lagging reads |
| Consistency | Atomic but blocking; heuristic holes | Eventual, semantically atomic; no isolation | Strong per-aggregate; eventual elsewhere |
| Failure recovery | In-doubt/blocking; manual XA ops | Explicit retry/compensate; non-blocking | Replayable, auditable; costly rebuilds |
| Ops complexity | Hidden, painful at scale | Moderate, explicit | Highest; skill-intensive |
| Fit for payments domain | Poor (fights reality of external partners) | Strong (mirrors reversal-based finance) | Strong for the ledger specifically |

---

## Recommendation

**Adopt the saga pattern (orchestrated) as the system-wide consistency strategy, and apply event sourcing narrowly to the ledger service. Reject 2PC.**

Justification from the analysis:

1. **2PC fails the throughput requirement outright.** Its blocking nature and cross-service lock hold times cannot sustain 50k TPS with hot accounts, and its atomicity guarantee evaporates at the system boundary anyway, because card networks and banking partners will never participate in your prepare phase. You would pay full price for a guarantee you cannot actually obtain end-to-end.

2. **Sagas match both the scale and the domain.** Local commits plus partitioned async messaging demonstrably sustain this load. The lost isolation is handled with techniques the payments domain already demands for other reasons: pending/authorized/captured state machines (semantic locks), idempotency keys, and reconciliation. Compensation maps one-to-one onto financial reality (refunds, reversals, chargebacks). Use an *orchestrated* saga (explicit state machine per payment, e.g., on Temporal or equivalent) rather than pure choreography — at startup team size, the legibility of one place that knows each payment's state is worth more than the looser coupling of choreography.

3. **Event sourcing where it earns its keep, not everywhere.** The ledger — the system of record for money — should be an append-only, event-sourced double-entry ledger: regulators and auditors effectively require an immutable history, projections give you balances and reporting, and per-aggregate strong consistency protects against double-spend on an account. But imposing ES+CQRS on every service (fraud, notifications, onboarding) buys maximal operational complexity for no additional consistency, and you would still need sagas for cross-aggregate flows. Keep the blast radius of the hardest pattern small.

Concretely: payment requests enter an orchestrated saga (authorize → reserve funds [semantic lock] → capture → post to event-sourced ledger → notify), every step idempotent via transactional outbox, compensations defined per step with non-compensatable external steps ordered last, and a daily reconciliation job as the final safety net. This delivers the throughput, survives partial failure without blocking, and produces the audit trail a fintech will eventually be examined on.
