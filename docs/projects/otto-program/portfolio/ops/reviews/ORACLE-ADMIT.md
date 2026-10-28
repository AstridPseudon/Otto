# Decision: who admits a task revision, and through what path

## 1. Decision

The operator gets a principal of their own, separate from the owner service actor and from every host principal. `register` records that operator principal as the project's user, so no agent is ever the user.

The only path to admission is a dedicated owner-lane `admit` command. The owner service writes as the operator only after it has run a user-presence check itself (macOS LocalAuthentication). No request can name the actor it writes as.

## 2. Why

**The brief's premise is backwards.** The work domain defines the project's user as its creator: `herzchen/domains/work/admission.py:122-134`. `register` creates the project and checks in its tasks as the host principal (`hostctl/register.py:228,238,330`; `portfolio/herzchen_binding.py:465` sets creator to the acting actor). So `claude-code-orchestrator` *is* the user. The operator's `admit` fails for a different reason: it acts as the owner service's actor, not as the creator (`portfolio/admit.py:25`, `owner_bootstrap.py:652`, `hostctl/owner.py:174-176`).

**An agent can already admit its own work.** Every edit by the project's user is admitted by being made: `module.py:723-735`, and the CLI help says "your own edits need no admit" at `portfolio/cli.py:147`. Dispatch accepts that stamp (`assignments.py:1026`; `test_admit.py:113` `test_user_edit_admitted_by_authoring`). Two things follow:
- Tasks the host checks in at registration are admitted by authoring. I traced this through `register.py:353` and `herzchen_binding.py:1698`; no test pins it.
- `save --actor X` writes as whatever X the request names. On the lanes the actor check is skipped, because `cmd_portfolio` calls `portfolio_cli.main` without `bound_actor` (`hostctl/cli.py:328`; the check at `portfolio/cli.py:1079-1083` runs only when `bound_actor` is set; then `cli.py:1208` and `herzchen_binding.py:2336`). So anyone who can write a lane can save as the creator and get the authoring stamp. F6's refusal of `admit` (`service.py:375-378`) doesn't close this.

**Option 2 (re-allow `admit` on the owner lane) doesn't hold.** The lane code says it "is not a defence against a hostile process of the same account (no lane in this account can be)" (`lanes.py:12-14`). Request files are checked only for owner, mode and symlinks (`lanes.py:40-48,71-78`). The sandbox keeps Codex managers and workers out, but not the Claude orchestrator or Claude workers. The Claude side runs under `dontAsk` path rules, not a sandbox (`fleet/hosts/claude.py:33-38`, `agents/claude_adapter.py:316`). This brief itself keeps me away from `ottoctl` and `~/.otto-clients` by instruction, not by enforcement. The owner lane also already carries `admit-host`, which mints new principals (`service.py:399-428`).

**D5 won't fix it either.** D5 identifies a peer by whether its process descends from one Otto launched (PLAN.md:83). The operator's shell and the Claude orchestrator both fail that test, so D5 can't tell them apart.

**Option 3 is the only one that holds on one account.** It needs something an agent can't produce, and the owner must check it, not the client. Without it, Option 1 just moves the hole to whoever can write as the operator.

**Costs:**
- One human touch per admission, so the AGENT-UX row 8 bottleneck comes back until the allowance lands. Granting an allowance also needs presence.
- macOS only. Tests need an injected prover, and the real PERCH stage-2 run needs a person at the machine.
- §15.4's "the user's own edits are approved by being made" now holds only for edits written through a presence-checked path. A plain owner-lane `save` lands unadmitted.
- Projects already registered keep the host as creator. They must be re-registered.

## 3. The task row: OPERATOR-ADMIT (xhard)

**Outcome:** The operator principal is the user of every project Otto creates. A revision is admitted only by the owner, writing as the operator after its own presence check. No lane request chooses the actor it writes as.

**Files:**
- `hostctl/config.py` and `hostctl/cli.py`: `install --operator`. Install refuses an operator name equal to the owner actor or to any host principal.
- `hostctl/cli.py:328`: pass `bound_actor` set to the lane principal.
- `hostctl/register.py` and `portfolio/herzchen_binding.py:465,1073,1565`, plus `owner_bootstrap.py:459` and `herzchen/domains/work/orchestration.py:455` if they create projects: creator is the operator. The host stays the curator and the acting actor. `allowed_creator_ids` gates the orchestration caller, not provenance (`orchestration.py:198-206`), so it is unaffected.
- `hostctl/service.py`: a dedicated `admit` owner command, kept out of `OWNER_PORTFOLIO_COMMANDS`.
- New `hostctl/presence.py`: the prover, injectable for tests.
- `portfolio/admit.py`: an explicit actor parameter.
- Tests: `tests/test_owner_lane.py`, `tests/test_admit.py`, new `tests/test_operator_admission.py`.

**Acceptance:**
1. After `register`, the project's creator is the operator. Tasks the host checks in carry no admission stamp, and dispatch refuses them.
2. Owner-lane `admit` with the prover approving: the task is admitted, `admitted_by` is the operator, and dispatch proceeds.
3. The prover declines, is absent, or times out: the admit is refused and the Store is byte-identical.
4. Agent attempts, each refused with nothing written:
   - `portfolio admit` on the host lane;
   - `save --actor <operator>` or `--actor <a project's creator>` on any lane (`bound_actor_mismatch`);
   - a request file dropped straight into the owner lane with a forged presence field, since presence is never read from the request;
   - an admit through a manager lane or the worker facade.
5. `complete-task` is still refused on the owner lane (`test_owner_lane.py:51`).
6. Each admission writes one log line: task, revision, review, prover result, outcome.
7. A probe on the real Mac: an agent session sends an admit with nobody present, and it is refused at timeout.

**Invariant:** Only the operator principal is a project's user. The owner writes as it only after a presence check the owner runs itself. A lane request never names its write actor.

**Plausible mistakes:**
- Putting the presence check in the `ottoctl` client, or reading it from a request field. An agent then writes the lane file directly and skips it.
- Adding `admit` to `OWNER_PORTFOLIO_COMMANDS`, so it runs through the generic path as the owner actor.
- Fixing the creator but leaving `--actor` unbound, so a `save` as the operator self-admits by authoring.

## 4. What stays open until D5

- **Lane forgery.** Lane binding is still file permissions. A same-account process can write a request as any host and forge that host's drafts (`lanes.py:12-14`). Admission is safe from this once presence lands; D5's peer identity closes the forgery itself.
- **Presence stays after D5.** D5 can't tell the operator from a non-Otto-launched agent, so the presence check is permanent, not a stopgap.
- **Unproven assumption.** That an agent can't satisfy a LocalAuthentication prompt (Touch ID or password) is not shown by anything in this repo. Acceptance 7 has to probe it before the row lands.