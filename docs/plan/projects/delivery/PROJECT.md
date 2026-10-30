# Project: delivery

**Manager:** M4 Delivery and integration. **Size:** about 13.5 engineer-days. **Runs at the same time as** the other three v1 projects (`../README.md`).

**Scope.** Three lanes in parallel (**Git landing**, **the acceptance harness and journey test**, **install, OS units and docs**), then the pilot and its fixes. M4 also runs landing into `main` for every project.

**Status:** keep `STATUS.md` in this folder current (`../../POLICY.md`).

**Interfaces it owns or consumes:** the repo, worktree and check-command contract; task commit records; the installed CLI; the fake RPC process, crash hooks and the loopback provider. All shapes are frozen in the L0 contract (`../contract.md`, written in L0). A change goes through one contract diff, reviewed by its producer and its consumers.

**Needs:** Install after S0; the Git adapter and harness after L0. Landing is qualified after C4, the service units after C2 and R1; the pilot needs everything.

**Done when:**
- every task in `TASKS.md` passes its check: automated checks in the installed-wheel CI (credential-free), and live checks (VS, fresh machines, the pilot) logged with evidence in `STATUS.md`;
- **For base qualification:** spec §B6 2; the full harness green; the journey test; fresh-machine checks (D1, D1b).
- **Afterwards, for the pilot (milestone 2):** D5 and the D6 re-run.

**Source of truth.** The tasks are copied from `../../14-plan.md`, and behaviour is in `../../13-spec.md`. If anything disagrees, follow the authority order in `../../START-HERE.md` and raise it; don't pick one silently.

**Repo and owned paths:** the new repo from B0. This project's paths are in `../README.md`. Briefs follow `../../POLICY.md`.
