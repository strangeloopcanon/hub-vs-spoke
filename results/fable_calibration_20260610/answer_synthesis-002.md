# Monorepo vs. Polyrepo for a 200-Person Engineering Organization

**Context:** 200 engineers, 15 microservices, 8 shared libraries, ~20 deploys/day.

---

## The Strongest Case FOR a Monorepo

### 1. CI/CD: One pipeline platform, atomic verification of cross-service changes

With 15 services and 8 shared libraries, the hardest CI problem is not building any single service — it's verifying changes that span services and libraries. In a monorepo, a single commit that changes a shared library *and* its consumers is tested as one unit, in one pipeline run, against the exact code that will ship together. Modern build systems (Bazel, Nx, Pants, Turborepo) make this tractable at 20 deploys/day: they compute the affected dependency graph per commit and rebuild/retest only what changed, so CI cost scales with the size of the change, not the size of the repo. You also get one place to invest in pipeline tooling — caching, flaky-test quarantine, deploy orchestration — instead of maintaining 23 slightly-divergent copies of CI config that drift apart over time. Importantly, monorepo does not mean monolithic deployment: each of the 15 services can still deploy independently; the repo unifies *verification*, not *release*.

### 2. Code sharing and dependency management: the diamond-dependency problem disappears

Eight shared libraries consumed by 15 services is exactly the configuration where polyrepo versioning hurts most. In a polyrepo world, every library change requires: publish a new version → open 15 consumer PRs (or wait for teams to upgrade "eventually") → debug the version skew when service A uses lib v2.3 and service B uses v1.8 and they disagree about a wire format. In a monorepo, everything builds at HEAD. A library author can change an API and fix all 15 consumers *in the same commit* — and CI proves the whole organization still compiles and passes tests. There is no internal artifact registry to operate, no semver negotiation for internal code, no months-long deprecation campaigns for a one-line signature change. Atomic, repo-wide refactoring (rename a function across every consumer with one reviewed change) is the single biggest practical win at this scale.

### 3. Team autonomy: autonomy through visibility and ownership, not isolation

Polyrepo advocates equate autonomy with separate repos, but repo boundaries are a crude proxy for ownership. A monorepo with CODEOWNERS files, directory-scoped review requirements, and per-directory CI gives teams the same decision rights — they own their directory, approve changes to it, and deploy on their own schedule — while removing the *bad* kind of autonomy: silent divergence. Today, when the payments team needs to understand how the auth service validates tokens, they read the code directly instead of guessing from stale docs or an outdated README in a repo they've never cloned. Cross-team contributions become normal pull requests rather than diplomatic missions. At 200 people you are still small enough that "anyone can read and propose a fix to anything" is a superpower, not a liability.

### 4. Developer onboarding: one clone, one toolchain, one mental model

A new engineer runs `git clone` once and has the entire system: every service, every library, every integration test, all searchable with a single grep/IDE index. There is one way to build, one way to run tests, one set of lint rules, one dependency lockfile policy. Compare this to onboarding into a polyrepo estate: discovering which of 23 repos matter, requesting access, learning each repo's slightly different Makefile and CI quirks, and never being fully sure they've found all the callers of the API they're about to change. Cross-service code search alone — "where is this protobuf field actually used?" — turns hours of archaeology into seconds, and that benefit accrues to senior engineers every day, not just new hires.

---

## The Strongest Case AGAINST a Monorepo (FOR Polyrepo)

### 1. CI/CD: monorepo CI at scale is an engineering project you must staff forever

The monorepo CI story depends entirely on sophisticated affected-target detection — and that means adopting and *operating* Bazel/Nx/Pants, which is a real, ongoing infrastructure investment (often a dedicated 2–4 person platform team at this scale). Get it wrong and you have the worst of all worlds: every commit triggers builds across the org, queue times balloon, a single flaky test in one team's service blocks 200 engineers' merges, and a broken main branch halts *everyone*. Polyrepo CI is boring in the best way: each service has a small, fast, independent pipeline using stock GitHub Actions/GitLab CI; failures are isolated to one team; pipeline-as-code stays simple enough that every team can own theirs. At 20 deploys/day across 15 services, fifteen independent 5-minute pipelines are operationally far simpler than one shared build graph with global merge queues.

### 2. Dependency management: building at HEAD removes a safety valve you'll miss

Versioned internal libraries are a *feature*, not just overhead. Explicit semver forces library authors to think about compatibility, lets consuming teams upgrade deliberately (pinning to v2.3 while they finish a launch, upgrading next sprint), and makes breakage attributable: the changelog says exactly what changed between versions. In a monorepo at HEAD, a library author's "fix all consumers in one commit" is also a library author *touching 15 services they don't understand*, with mechanical fixes that compile but may be semantically wrong — and the consuming teams are forced to absorb that change immediately, on the author's schedule, not theirs. Polyrepo's published-artifact model also mirrors how you already consume third-party open source, so there's one dependency discipline, not two.

### 3. Team autonomy: real independence over technology, tempo, and access

Separate repos give teams genuine sovereignty: choose the language or framework that fits the problem, upgrade their runtime when ready, adopt their own branching and release cadence, and tune their own tooling without negotiating with a central platform team or waiting on a global migration. Monorepos inexorably centralize: one blessed toolchain, org-wide lint and dependency policies, and a platform team that becomes a bottleneck and a political chokepoint ("you can't upgrade to the new framework version until all 15 services are ready"). Polyrepo also gives you clean access control for free — a contractor, an acquisition under integration, or a team handling regulated payment code can be scoped to exactly the repos they need; per-directory permissions in a monorepo are awkward on standard Git hosting, and your audit/compliance story is simpler when the sensitive code simply isn't in everyone's clone.

### 4. Developer onboarding: a small, bounded repo is a gentler on-ramp

A new backend engineer joining the checkout team needs to learn *one service*: a repo they can read end-to-end in a week, with a CI config that fits on one screen and a build that runs with stock tools they already know. The monorepo onboarding story hides a tax: the new hire must install and learn a nonstandard build system (Bazel targets, query language, remote-cache quirks), their IDE struggles to index a multi-gigabyte repo, `git clone` and `git status` are slow without sparse-checkout gymnastics, and the sheer surface area of 23 projects in one tree is intimidating rather than illuminating. "One repo to clone" sounds simple but actually means "one enormous, unfamiliar toolchain to master before your first commit." Repo-per-service keeps each on-ramp short and lets day-one productivity happen with `git`, `docker`, and the team's README — nothing more.

---

## Balanced Recommendation

**For this specific organization — 200 engineers, 15 services, 8 shared libraries, 20 deploys/day — I recommend the monorepo, adopted incrementally, with eyes open about its costs.**

### Why monorepo wins here

The deciding factor is the **ratio of shared libraries to services**. Eight shared libraries feeding 15 services means cross-cutting changes are routine, not exceptional — and that's precisely the workload where polyrepo's version-skew, publish-upgrade-debug cycle quietly consumes the most engineering time while remaining invisible on any single team's dashboard. At 200 people you're also large enough to afford a small platform investment but small enough that you don't yet face the extreme scaling problems (multi-hour Git operations, massive build farms) that plague monorepos at 10,000-engineer scale. The 20-deploys/day cadence is comfortably handled by affected-target CI plus per-service deployment pipelines.

Concretely: keep independent deploy pipelines per service (monorepo ≠ monodeploy), adopt an incremental build tool (Nx or Pants before reaching for full Bazel), enforce CODEOWNERS per directory, and institute a merge queue from day one. Migrate gradually — start by folding the 8 shared libraries plus 2–3 of the most interdependent services into one repo and prove the workflow before moving the rest.

### What you are honestly giving up

- **Tooling simplicity.** You are signing up for a permanent platform engineering function (realistically 2–3 engineers) to own the build system, merge queue, and repo health. If you are unwilling to staff this, **choose polyrepo instead** — an under-invested monorepo is worse than a well-run polyrepo.
- **Technology freedom.** Per-team language/framework experimentation gets harder; the org will converge on a blessed stack. That's partly a feature (less fragmentation) but it is a real loss of team-level optionality.
- **Deliberate upgrade pacing.** Teams lose the ability to pin an old library version while they finish a launch; building at HEAD means absorbing upstream changes on someone else's schedule. You'll need cultural norms (library authors fix consumers; feature flags for risky changes) to compensate.
- **Simple access control.** If you anticipate acquisitions, contractors, or regulated code requiring hard isolation, you'll be fighting your repo layout; carve such code into satellite repos as the exception.
- **Blast-radius isolation.** A broken main or a CI outage now affects everyone. The merge queue and flaky-test quarantine are not optional luxuries — they're the price of admission.

### And if you chose polyrepo instead

You'd keep boring, isolated CI and genuine team sovereignty — but you would be accepting permanent friction on every shared-library change, gradual version skew across 15 services, divergent tooling that makes internal mobility harder, and the eventual emergence of a half-built internal "meta-repo" tooling layer (scripts to clone/update/search across 23 repos) that recreates monorepo features poorly. With 8 shared libraries, that tax is paid weekly. Polyrepo is the right call for organizations with truly independent products and few shared internals; that is not the shape of this organization.

**Bottom line:** choose the monorepo because your library-to-service coupling makes atomic cross-cutting changes your dominant cost — but only if leadership commits to funding the platform team that keeps it healthy. Without that commitment, a well-disciplined polyrepo with strong library-versioning hygiene is the safer second-best.
