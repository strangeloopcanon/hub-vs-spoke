# Incident Analysis: v2.3.1 Session Cache OOM Cascade

## Causal chain (root cause → site-wide outage)

1. **2:00 PM** — v2.3.1 deploys an in-memory session cache on each app server. It works as intended: session reads stop hitting the database.
2. **2:15 PM** — The cache delivers its benefit: DB query latency drops 15%. The deployment looks healthy, which masks the latent defect.
3. **2:45 PM** — The cache is **unbounded (or effectively unbounded)**: every active user session gets cached and entries are never evicted (no TTL, no LRU, no max-size cap). Memory grows monotonically with cumulative sessions seen, so usage climbs steadily as traffic flows.
4. **3:30 PM** — server-3 — the first server to exhaust its headroom (slightly less RAM, more traffic, or more cached sessions) — hits an out-of-memory error and crashes/fails health checks.
5. **3:35 PM** — The load balancer does its job and removes server-3.
6. **3:40 PM** — Its traffic redistributes; servers 1, 2, 4 each absorb ~33% more requests. More requests ⇒ more distinct sessions cached per surviving server ⇒ **memory growth accelerates on exactly the machines already nearest their limits**.
7. **4:00 PM** — server-2, now filling its cache faster than before, OOMs and is removed. The remaining two servers now take ~2× their original load, and their caches grow faster still.
8. **4:15 PM** — The remaining servers are overwhelmed (CPU/GC thrash, swap pressure, request queuing); p99 latency exceeds 10 s — a site-wide outage in effect even before the last servers die.
9. **5:00–5:30 PM** — Rollback to v2.3.0 removes the cache; memory is released as processes restart, and all servers recover.

## (a) Root cause

The new in-memory session caching layer in v2.3.1 had **no bounds or eviction policy**: it accumulated an entry for every session it saw and never released memory. This is a memory leak by design — a resource-exhaustion defect, not a load problem. (Secondary root cause: it was tested for correctness/latency, not for memory behavior under sustained production traffic.)

## (b) Why the impact was delayed ~45 minutes

The failure mode is **gradual resource exhaustion, not an immediate fault**. At deploy time the cache is empty and the system is at its best (hence the 2:15 PM latency *improvement*). Memory consumption grows roughly linearly with the cumulative number of distinct sessions cached, so it took ~45 minutes of normal traffic for the cache to consume the available heap/RAM headroom on the first server, and another ~45 minutes to reach the hard OOM threshold at 3:30 PM. The early "success" signal (better latency) actively delayed detection: the deployment was judged healthy on latency metrics while the leak was already underway.

## (c) Amplification mechanism: a load-redistribution death spiral

The cascade was driven by a classic **positive feedback loop between the load balancer and the per-server caches**:

- Every server shares the same defect and is consuming memory at a rate proportional to the traffic it serves.
- When one server OOMs, the load balancer — behaving correctly for a *transient* failure — redistributes its traffic to the survivors.
- Extra traffic means extra distinct sessions, which means **faster cache growth on servers that were already near exhaustion** (they'd been leaking for the same 90 minutes).
- Each removal therefore *shortens* the time-to-failure of the remaining servers: 4 servers → 3 (+33% load each) → 2 (+100% load each), compounding both memory growth rate and per-server request load.

This is a **correlated failure** scenario: the fleet didn't fail independently, it failed in an accelerating sequence because the mitigation for one failure (redistribution) was fuel for the next. The load balancer converted one server's memory leak into a site-wide capacity collapse — by 4:15 PM the survivors were saturated on CPU/queueing as well as memory, pushing p99 past 10 s.

## (d) The specific design flaw in the caching layer

**An unbounded, non-evicting in-process cache**: session entries were stored in each app server's own heap with

- no maximum size / memory cap,
- no TTL or expiry on session entries,
- no eviction policy (LRU/LFU) when under memory pressure,

so memory use grew without limit as a function of cumulative sessions. Two aggravating design choices made it worse:

1. **In-process, per-server storage** tied cache size directly to application memory and traffic share, so the load balancer's redistribution directly accelerated the leak on survivors. An external shared cache (e.g., Redis/Memcached) with its own memory limits would have isolated the failure domain and decoupled cache pressure from app-server health.
2. **No backpressure or graceful degradation**: when memory ran low, the server crashed with OOM instead of evicting entries or bypassing the cache and falling back to the database.

## Fixes (brief)

- Cap the cache (max entries/bytes) with LRU eviction and per-entry TTLs; treat the cache as strictly best-effort with DB fallback.
- Prefer an external session store, or at least size in-process caches against container/heap limits.
- Add memory-growth and cache-size alerting (catch the 2:45 PM trend, not the 3:30 PM crash) and soak/endurance tests that exercise sustained traffic before rollout.
- Consider load-balancer/autoscaling policies that recognize correlated resource exhaustion (e.g., don't redistribute into a fleet that is uniformly near memory limits — shed load or scale out instead).
