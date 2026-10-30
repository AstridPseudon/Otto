# Project: state

**Manager:** M1 State. **Size:** about 12 engineer-days. **Runs at the same time as** the other three v1 projects (`../README.md`).

**Scope.** The schema and store, transactional spec folders, tasks and attempts, spec → tasks decisions, the CLI, and status.

**Status:** keep `STATUS.md` in this folder current (`../../POLICY.md`).

**Interfaces it owns or consumes:** store transitions and transactions; task and attempt identities; spec snapshots; `--json` query results. All shapes are frozen in the L0 contract (`../contract.md`, written in L0). A change goes through one contract diff, reviewed by its producer and its consumers.

**Needs:** L0. Spec and task work after C1. The final reconciliation (C5) and status (C6) need runtime events (R3, R4, R6).

**Done when:**
- every task in `TASKS.md` passes its check: automated checks in the installed-wheel CI (credential-free), and live checks (VS, fresh machines, the pilot) logged with evidence in `STATUS.md`;
- Spec §B6 1, 3, 9 and 10; the C3 invariant (all or nothing).

**Source of truth.** The tasks are copied from `../../14-plan.md`, and behaviour is in `../../13-spec.md`. If anything disagrees, follow the authority order in `../../START-HERE.md` and raise it; don't pick one silently.

**Repo and owned paths:** the new repo from B0. This project's paths are in `../README.md`. Briefs follow `../../POLICY.md`.
