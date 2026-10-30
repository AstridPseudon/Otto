# Project: runtime

**Manager:** M2 Runtime. **Size:** about 12.5 engineer-days. **Runs at the same time as** the other three v1 projects (`../README.md`).

**Scope.** `otto run`: the supervisor, spawn by role and rank, durable messages, recovery, recording sub-agents, and **the vertical slice**.

**Status:** keep `STATUS.md` in this folder current (`../../POLICY.md`).

**Interfaces it owns or consumes:** the resolved launch config; admission, outcome and settled events; durable delivery and recovery operations. All shapes are frozen in the L0 contract (`../contract.md`, written in L0). A change goes through one contract diff, reviewed by its producer and its consumers.

**Needs:** Adapter work against L0 stubs; R1 is qualified once C1 lands. **R2 and R3 run as separate workers after R1.**

**Done when:**
- every task in `TASKS.md` passes its check: automated checks in the installed-wheel CI (credential-free), and live checks (VS, fresh machines, the pilot) logged with evidence in `STATUS.md`;
- Spec §B6 4, 6 and 8; the R1 and R3 invariants; VS live.

**Source of truth.** The tasks are copied from `../../14-plan.md`, and behaviour is in `../../13-spec.md`. If anything disagrees, follow the authority order in `../../START-HERE.md` and raise it; don't pick one silently.

**Repo and owned paths:** the new repo from B0. This project's paths are in `../README.md`. Briefs follow `../../POLICY.md`.
