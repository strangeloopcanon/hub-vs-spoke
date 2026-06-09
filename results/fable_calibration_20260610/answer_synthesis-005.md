# Critical Analysis: "Microservices are always better than monoliths for organisations with more than 50 engineers"

This claim is wrong, and not just because of the word "always". It rests on a chain of assumptions that fail in well-documented, real-world cases. Below I take the claim apart, give concrete counterexamples in both directions, and replace the blanket rule with a usable decision framework.

## 1. Three hidden assumptions

### Assumption 1: Headcount is the binding constraint on architecture

The claim treats engineer count (50+) as the variable that determines the right architecture. It is not. What actually determines coordination cost is the structure of the work: how many teams need to ship independently, how coupled their domains are, and how often they collide in the same code. A 200-engineer organisation working on one tightly integrated product (say, a database engine or a trading system) has fundamentally different needs from a 60-engineer organisation running twelve loosely related product lines. Conway's Law cuts both ways: architecture should mirror the *communication structure you want*, not a raw headcount threshold. Using "50 engineers" as the trigger optimises for a proxy rather than the real problem, and proxies fail precisely when decisions matter most.

### Assumption 2: The costs of microservices are negligible or always worth paying

Microservices do not remove complexity; they relocate it from the codebase into the network. The claim silently assumes the organisation can absorb that relocation: distributed tracing, service discovery, retries and circuit breakers, eventual consistency, contract versioning, per-service CI/CD, on-call rotations per service, and the loss of cheap cross-cutting refactors (a rename that was one IDE operation in a monolith becomes a multi-team, multi-deploy migration). For organisations without mature platform engineering, these costs routinely exceed the coordination costs they were meant to eliminate. A distributed system is the most expensive way to build software that doesn't need to be distributed.

### Assumption 3: A monolith cannot be modular

The claim implicitly equates "monolith" with "big ball of mud" and "microservices" with "well-factored". Both equations are false. Module boundaries, enforced internal APIs, and independent team ownership are achievable inside a single deployable — this is the "modular monolith" pattern, and tooling (build-system module visibility rules, architecture tests, code ownership enforcement) makes it enforceable in practice. Conversely, microservices can be (and frequently are) a distributed ball of mud, where boundaries were drawn wrong and every user request fans out across a dozen chatty services. The deployment unit and the modularity of the design are separate axes; the claim collapses them into one.

## 2. Counterexample: a large org succeeding with a monolith — Shopify

Shopify runs one of the largest Ruby on Rails monoliths in existence, with thousands of engineers contributing to it, and processes flash-sale traffic peaks (Black Friday/Cyber Monday) that most microservice shops never see. It worked — and keeps working — for specific, identifiable reasons:

- **They invested in modularity instead of distribution.** Shopify's well-documented "componentization" effort (their internal tooling, including the Packwerk gem they open-sourced) enforces component boundaries and dependency rules *inside* the monolith. Teams get ownership and isolation without paying the network tax.
- **They scaled the data tier, not the deployment topology.** Pod-based sharding (isolating each merchant's data to a shard) gave them horizontal scale while keeping the application a single codebase.
- **Their domain is cohesive.** Commerce — orders, products, payments, inventory — is deeply interconnected. Transactions that span those concepts are far cheaper inside one process with one database transaction than across service boundaries with sagas and compensation logic.

Shopify engineers have stated publicly and repeatedly that the monolith was the right call and that they would choose it again. The lesson: with deliberate internal structure, a monolith scales to thousands of engineers — well past the claim's 50-engineer threshold. (GitHub and Stack Overflow are corroborating cases: large or high-traffic, deliberately monolithic, successful.)

## 3. Counterexample: microservices causing significant problems — Segment

Segment (the customer-data platform, ~hundreds of engineers at the time) is the canonical documented case, because they wrote it up themselves in "Goodbye Microservices" (2018). They had decomposed their data-forwarding pipeline into a microservice per destination — over 140 services, each with its own repo, queue, and deploy pipeline. The result:

- **Operational drowning.** Shared library updates had to be rolled out across 140+ repos; in practice versions drifted and services diverged. Engineers spent their time on toil — babysitting queues, deploys, and autoscaling configs — rather than product work.
- **No real independence gained.** The services were doing fundamentally the same job (transform and forward events), so the supposed benefit of independent evolution never materialised. They had paid the full distributed-systems tax for workloads that weren't meaningfully independent.
- **The fix was re-consolidation.** Segment merged the services back into a single monolithic service ("Centrifuge") and reported dramatically improved developer productivity and reliability.

A second supporting case: Amazon Prime Video's own engineering blog (2023) described moving their video-monitoring workload *from* a distributed microservices/serverless design *to* a monolith, cutting infrastructure costs by ~90%. Even inside the company most associated with service-oriented architecture, microservices lost on the merits for that workload. The pattern in both failures is the same: decomposition along the wrong boundaries, where the pieces were not independently valuable.

## 4. A decision framework instead of a blanket rule

An engineering leader should ask these five questions. Microservices deserve serious consideration only when most answers are "yes".

**Q1. Do parts of the system have genuinely divergent scaling, availability, or technology requirements?**
*Rationale:* This is the strongest technical justification. If your ML inference needs GPUs while your CRUD API needs neither, or one component needs 99.99% availability while the rest tolerates 99.9%, separate deployables let you pay for each requirement only where it exists. If everything scales together, a load-balanced monolith does the job with far less machinery.

**Q2. Can you draw service boundaries that match stable, well-understood domain seams — boundaries you'd bet won't need redrawing within two years?**
*Rationale:* Wrong boundaries are vastly more expensive across services than across modules (network calls, contract migrations, distributed transactions versus an in-process refactor). If the domain is still being discovered — true for most products before strong product-market fit — extract services later, once the seams have revealed themselves. "Monolith first" (Fowler's argument) is the empirically safer sequencing.

**Q3. Do you have — or will you genuinely fund — a platform/infrastructure team providing deployment, observability, and service tooling as a product?**
*Rationale:* Microservices shift complexity onto infrastructure. Without paved-road tooling (standardised CI/CD, tracing, service templates, on-call support), every product team rebuilds that machinery badly, and you get Segment's outcome. If the honest answer is "we'll get to it", the answer is no.

**Q4. Are teams currently blocked on each other in ways that modularising the monolith demonstrably cannot fix?**
*Rationale:* The main organisational benefit of microservices is independent deployment cadence. But merge conflicts, unclear ownership, and slow CI are usually fixable with enforced module boundaries, code ownership, and build investment — at a fraction of the cost. Extract services to solve a *measured* coordination problem that modularisation already failed to solve, not a hypothetical one.

**Q5. Can each candidate service be owned end-to-end (build, deploy, on-call) by a single team?**
*Rationale:* A service nobody fully owns, or that one team must share awkwardly with another, is a liability: it decays, its contracts rot, and incidents fall in the gaps. If your proposed decomposition yields more services than teams that can own them, you have decomposed too far. Service count should follow team topology, never lead it.

## Verdict

The claim fails on logic (headcount is a proxy, not a cause), on evidence (Shopify scales a monolith past thousands of engineers; Segment and Amazon Prime Video paid dearly for premature or excessive decomposition), and on framing (it presents a continuous, context-dependent trade-off as a binary triggered by an arbitrary number). The defensible position is this: organisational scale makes *modularity* mandatory, but distribution is only one way to buy modularity — and it is the most expensive way. Adopt microservices when specific, identified components need independent scaling, deployment, or ownership *and* you have the platform maturity to support them. Otherwise, build a well-modularised monolith and extract services when the evidence — not the headcount — demands it.
