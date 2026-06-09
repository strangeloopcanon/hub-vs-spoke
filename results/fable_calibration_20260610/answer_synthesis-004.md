# EHR Platform Architecture Evaluation

**Context:** 12 hospitals, 4,000 physicians, HIPAA-regulated, 40 → 120 developers over 2 years. The core tension: real-time cross-department patient views (favouring centralised, strongly consistent data) versus per-hospital workflow customisation (favouring isolation and independent change).

---

## 1. Architecture-by-architecture analysis

### (a) Monolithic application, single shared database

**Data consistency and cross-domain queries.** This is the monolith's strongest card. "All medications for patient X across all departments" is a single SQL join over normalised tables in one ACID database. Consistency is strict and free: a medication ordered in the ED is instantly visible in the ICU view because there is exactly one copy of the truth. No eventual consistency, no read-model lag, no distributed query federation. For clinical safety queries (allergy checks, drug–drug interactions across departments) this is genuinely valuable — the failure mode of "the allergy was recorded but hadn't propagated yet" simply cannot occur.

**HIPAA compliance and audit.** Centralisation simplifies audit. One database means one place to implement the HIPAA Security Rule's audit controls (§164.312(b)): a single append-only audit log of all PHI access, one encryption-at-rest configuration, one access-control model, one place to answer "who viewed patient X's record in the last 6 years?" Accounting of disclosures and minimum-necessary enforcement are implemented once. The risk is the inverse: the database is a single high-value breach target, and a single over-broad role grant exposes everything. Auditors generally like monoliths; security architects worry about them.

**Deployment and rollback risk across 12 hospitals.** This is where the monolith bleeds. Every deployment is a whole-system deployment to all 12 hospitals simultaneously (or a painful per-hospital fork — see below). A regression in the radiology module can take down medication ordering. Rollback is all-or-nothing, and schema migrations on a single shared database under 24/7 clinical load are high-ceremony events (expand–contract migrations, long-running backfills on tables with billions of rows). Release cadence inevitably slows to a crawl as the change surface grows: with 120 developers committing to one deployable, the integration queue and regression-test burden become the bottleneck, and releases drift toward big, risky, quarterly events — exactly what you don't want for a clinical system.

**Team scaling (40 → 120).** Poor. A single codebase with no enforced internal boundaries degrades roughly quadratically with team size: merge conflicts, unclear ownership, "spooky action at a distance" through shared tables. The classic failure is teams integrating through the database — the scheduling team reads the pharmacy team's tables directly, and now no table can ever change. At 40 developers this is survivable with discipline; at 120 it is not.

**Failure blast radius.** Maximal. One bad deploy, one connection-pool exhaustion, one runaway query, one database failover hiccup affects all 12 hospitals and every clinical function at once. You can mitigate with read replicas, bulkheaded thread pools, and circuit breakers, but the architecture fights you. For a system where downtime means clinicians reverting to paper, "everything fails together" is a serious patient-safety concern.

**The tension.** Real-time cross-department views: handled superbly. Per-hospital customisation: handled badly. The realistic options are (i) configuration flags and conditionals scattered through shared code (`if hospital == "St. Mary's"` — this metastasises into untestable combinatorial complexity), or (ii) per-hospital forks/branches, which is a maintenance death spiral (12 divergent codebases, security patches applied 12 times). The monolith resolves the tension by sacrificing customisation.

---

### (b) Microservices, per-service databases, API gateway

**Data consistency and cross-domain queries.** This is the microservices architecture's weakest card, and for an EHR it is a near-disqualifying weakness if handled naively. "All medications for patient X" now spans the pharmacy service, the ED service, the surgery service, the discharge-meds service… Your options are:

- *API composition / fan-out at the gateway or a BFF*: latency is the max of N calls, availability is the product of N availabilities, and a partial failure gives you a **silently incomplete medication list** — a patient-safety hazard, not a UX bug.
- *CQRS read model / materialised patient view* fed by an event stream (e.g. Kafka): this is the standard answer, but it is **eventually consistent**. You must now state and defend an SLO like "medications appear in the consolidated view within 2 seconds, p99," monitor replication lag as a safety metric, and design the UI to show data freshness. Clinicians must be trained that the consolidated view can lag the departmental system that wrote the order seconds ago.
- *Sagas* for cross-service writes (order medication → check allergies → notify pharmacy) replace ACID transactions with compensation logic that is hard to write and harder to test.

None of this is impossible — large EHR-adjacent systems do it — but it converts a `JOIN` into a distributed-systems engineering programme, and every clinical workflow that crosses a service boundary pays the tax.

**HIPAA compliance and audit.** Audit trail requirements become a distributed tracing problem. "Who accessed patient X's PHI?" must be answered across 30+ services and 30+ databases. You need: a mandatory shared audit library or sidecar emitting to a centralised, immutable audit store; propagated correlation IDs and *end-user* identity (not just service identity) through every hop — OAuth2 token exchange / on-behalf-of flows so the pharmacy service knows Dr. Smith, not "api-gateway", made the request; per-service encryption, key management, and BAA-relevant vendor surface area. Each service is a separately auditable system. The compliance burden doesn't grow linearly with service count, but it grows. The upside: genuine data segregation is easier (least privilege per service, smaller breach blast radius per database), and you can isolate especially sensitive domains (psych notes, HIV status, substance-abuse records under 42 CFR Part 2) behind dedicated services with stricter controls.

**Deployment and rollback.** Excellent — this is what you're buying. Services deploy independently; a bad scheduling release rolls back without touching medication ordering. Canary and blue/green per service, per hospital, are natural. Rollback risk is small and local *provided* you maintain backwards-compatible APIs and event schemas (consumer-driven contract tests become mandatory infrastructure, not nice-to-have).

**Team scaling.** Excellent at 120, premature at 40. Microservices are fundamentally an organisational scaling technology (Conway's law applied deliberately): each team owns services end-to-end, deploys independently, and integrates through contracts. But 40 developers cannot responsibly own the platform substrate microservices require — Kubernetes, service mesh, event bus, distributed tracing, secrets management, contract testing, per-service on-call. A reasonable rule of thumb is that the platform team alone costs 6–10 engineers before any clinical feature ships. At 40 developers that's 20% of capacity on plumbing; at 120 it's affordable.

**Failure blast radius.** Smallest per-failure — a crashed billing service doesn't stop medication ordering — but you trade fewer total outages for more partial degradations, and partial degradation in clinical software is insidious (the chart loads but the meds panel is stale/empty). You must design explicit degraded modes: what does the patient view show when the allergy service is down? A blank panel is unacceptable; you need cached-with-timestamp displays and hard failures on safety-critical checks.

**The tension.** Customisation: handled well — per-hospital service configuration, per-hospital workflow service instances, or even hospital-specific service versions behind the gateway, all without forking the clinical core. Real-time cross-department views: handled only with significant, permanent engineering investment in event-driven read models, and "real-time" becomes "near-real-time with a monitored SLO". Microservices resolve the tension by making customisation cheap and consistency expensive — the exact inverse of the monolith.

---

### (c) Modular monolith, enforced domain boundaries

**Data consistency and cross-domain queries.** Nearly as good as the monolith. One physical database, so the cross-department medication query is still a single ACID query — but it must go through the owning module's interface (e.g. `medications_module/api.py` exposing `get_medications(patient_id) -> list[MedicationRecord]`), or through explicitly designated shared read views. The discipline that matters: **modules own their tables; no cross-module table access; cross-module reads go through typed interfaces; schema-per-module (or table-prefix-per-module) enforced by CI and database grants.** You keep transactional consistency where it's clinically critical (allergy check + order placement in one transaction via two module APIs in-process) while preserving the *option* to move a module out later.

**HIPAA compliance and audit.** Best of both. One audit log, one encryption config, one access-control plane (monolith advantages), plus module boundaries that give you clean internal least-privilege and a natural place to enforce minimum-necessary access (the UI module can only get PHI through module APIs that log access with user identity). Because all calls are in-process, end-user identity propagation is trivial — it's just a parameter, not a token-exchange protocol.

**Deployment and rollback.** Still one deployable, so deployment risk is monolith-like — this is the modular monolith's real weakness. Mitigations that work in practice: feature flags per module and **per hospital** (so a change ships dark and is enabled hospital-by-hospital), strong module-level test isolation (a change touching only the scheduling module runs scheduling's test suite plus contract tests, cutting CI time), and ring-based rollout across the 12 hospitals (1 pilot hospital → 3 → all 12) if hospitals run separate instances or tenancy cells. Rollback is still whole-binary, but flags make most rollbacks a config change rather than a redeploy.

A specifically useful pattern here: **cell-based deployment** — run the same modular monolith as (say) 3–4 cells, each serving a subset of hospitals, with per-cell databases or schemas. Blast radius drops to a cell, rollout is ringed by cell, and hospitals get instance-level configuration isolation, all without distributed-systems complexity. This deserves serious consideration for a 12-hospital topology.

**Team scaling.** Good to ~100–150 developers *if and only if boundaries are mechanically enforced* — import linting (ArchUnit, import-linter, dependency-cruiser), CODEOWNERS per module, contract tests on module APIs, and a build that fails on boundary violations. The honest failure mode: under deadline pressure, someone bypasses the interface "just this once", and five years later you have a distributed big ball of mud waiting to happen. Enforcement must be tooling, not culture. At 120 developers, build/CI time on a single artifact becomes the next constraint; invest in module-scoped test selection early.

**Failure blast radius.** Same process, so a memory leak or crash in one module can take down the whole node — worse than microservices, same as the monolith. Cells (above) and per-module bulkheads (separate thread pools, per-module circuit breakers around external calls) reduce this materially.

**The tension.** This is where the modular monolith is genuinely clever: cross-department real-time views are cheap (one database, in-process calls, ACID), and customisation is handled by **a deliberate configuration architecture inside module boundaries** — each module exposes hospital-scoped configuration (order sets, form layouts, approval chains, terminology mappings) as data, plus a constrained extension-point/plugin interface for the few hospitals that need behavioural differences. Crucially, customisation is *bounded*: hospitals customise within the workflow vocabulary the modules expose, not arbitrarily. That's a feature, not a bug — unbounded per-hospital divergence is how EHR deployments become unmaintainable. Where a hospital truly needs divergent behaviour that the extension points can't express, that's the signal to extract that domain as the first service (see phasing).

---

## 2. Comparative summary

| Dimension | (a) Monolith | (b) Microservices | (c) Modular monolith |
|---|---|---|---|
| Cross-domain patient query | Trivial, ACID | Hard: fan-out or eventually-consistent read models | Trivial, ACID, via module APIs |
| HIPAA audit | One log, simple; big breach target | Distributed; needs identity propagation + central audit store; better segregation | One log + internal least-privilege; best balance |
| Deploy/rollback (12 hospitals) | Worst: all-or-nothing | Best: independent, canaryable | Moderate; rescued by flags + cells + ringed rollout |
| 40 → 120 devs | Degrades badly | Best at 120; premature at 40 | Good to ~120–150 with enforced boundaries |
| Blast radius | Total | Smallest, but partial-degradation hazards | Process-wide; reduced by cells |
| Real-time cross-dept view | Excellent | Expensive, eventually consistent | Excellent |
| Per-hospital customisation | Bad (flags sprawl or forks) | Excellent | Good (config-as-data + extension points, bounded) |

The monolith and microservices each resolve the central tension by sacrificing one of its two sides. The modular monolith is the only option that holds both at acceptable cost *at this organisation's current size* — and, critically, it is the only option that preserves cheap exit paths in both directions.

---

## 3. Phased recommendation

**Phase 1 (months 0–18): Cell-deployed modular monolith.**
Build (c), with these non-negotiables from day one:

1. Module boundaries enforced by CI (import linting, schema-per-module DB grants, typed module APIs, CODEOWNERS).
2. Hospital-scoped configuration as data + defined extension points in every workflow module.
3. A single append-only PHI audit pipeline with end-user identity on every module API call.
4. **Domain events published to a durable log (e.g. Kafka) from day one, even with no consumers.** This is the cheapest insurance you will ever buy: it forces event-schema discipline and makes Phase 2/3 extraction feasible without archaeology.
5. Feature flags per module × hospital; ring-based rollout (pilot hospital → ring 2 → fleet).
6. 2–4 deployment cells once hospital count justifies it.

Rationale: 40 developers cannot fund a microservices platform; clinical safety demands ACID cross-department views on day one; and HIPAA audit is simplest to get right centrally. You ship value fastest with the lowest distributed-systems risk.

**Phase 2 (roughly months 12–30): Extract edge services where the triggers fire.**
Candidates that earn extraction first are the ones that are *asynchronous, spiky, or divergent*: reporting/analytics (read replica → separate service), HL7/FHIR integration engine, patient portal, notifications, billing. Clinical core (orders, meds, results, charting) stays in the monolith.

**Explicit triggers for extracting a given module** (any two of):
- Its deployment cadence is blocked: the module's team ships <50% of its ready changes per release window because of fleet-wide release risk owned by other modules.
- Its scaling profile diverges: it needs >3× the resources of the median module, or its load spikes degrade clinical-path latency SLOs.
- Per-hospital divergence exceeds the extension-point model: ≥3 hospitals need behaviour that requires changes to the module's core, not its config.
- Team-boundary friction: >2 teams are making conflicting changes inside one module per quarter despite CODEOWNERS.

**Explicit triggers for adopting the platform substrate** (prerequisite for any extraction):
- Headcount ≥ 70–80 engineers, so a 6–8 person platform team is <12% of capacity.
- The day-one event log is in production with monitored consumers (i.e., you've proven you can operate async infrastructure).
- Distributed tracing + centralised audit ingestion are live *before* the first PHI-handling service ships.

**Phase 3 (months 24+, only if triggers fire): Selective service extraction of clinical domains; consolidated patient view as an explicit product.**
If and when clinical modules themselves hit the Phase-2 triggers at 120 developers, extract them one at a time (strangler fig, module API → network API, database split last), and *only then* build the event-sourced consolidated patient read-model, with a published freshness SLO (e.g. p99 < 2s), per-panel staleness indicators in the UI, and hard-fail semantics for safety checks (an allergy check that can't reach fresh data blocks the order; it never silently passes).

**Explicit non-trigger:** do not extract a clinical-core module because "microservices are where we're heading", because a vendor demands it, or because the team is bored. Every extraction must cite which triggers fired, in writing.

**Rollback criterion for the strategy itself:** if after two extractions the consolidated patient view's freshness SLO is breached >2 consecutive months, or cross-service audit reconstruction fails a compliance drill, halt further extraction and re-absorb or fix before continuing.

The end state is not "microservices" — it is a modular clinical core with ACID patient-safety semantics, surrounded by independently deployed satellites where independence actually pays. For an EHR, that asymmetry is the point: consistency where patients can be harmed, autonomy where they can't.
