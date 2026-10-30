# Project: pack

**Manager:** M3 Pack and behaviour. **Size:** about 11 engineer-days. **Runs at the same time as** the other three v1 projects (`../README.md`).

**Scope.** The pack format and loader (roles with ranks), Megado role guides including specialists, skills, generated helper definitions, templates, schedules and the advisor, and the idle-manager rule.

**Status:** keep `STATUS.md` in this folder current (`../../POLICY.md`).

**Interfaces it owns or consumes:** the role and config resolver; pack fixtures; schedule inputs; settled notifications. All shapes are frozen in the L0 contract (`../contract.md`, written in L0). A change goes through one contract diff, reviewed by its producer and its consumers.

**Needs:** The content starts against the frozen role-file format, and the behaviour against a fake clock and events. Final qualification needs the real runtime and VS.

**Done when:**
- every task in `TASKS.md` passes its check: automated checks in the installed-wheel CI (credential-free), and live checks (VS, fresh machines, the pilot) logged with evidence in `STATUS.md`;
- Spec §B6 5, 7 and 11; a fresh agent performs the workflow from the skills.

**Source of truth.** The tasks are copied from `../../14-plan.md`, and behaviour is in `../../13-spec.md`. If anything disagrees, follow the authority order in `../../START-HERE.md` and raise it; don't pick one silently.

**Repo and owned paths:** the new repo from B0. This project's paths are in `../README.md`. Briefs follow `../../POLICY.md`.
