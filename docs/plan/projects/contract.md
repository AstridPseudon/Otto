# L0 contract: NOT YET WRITTEN (a checklist to fill in)

**Owner:** the orchestrator, with all four managers. **Time:** 2 days, after S0. **Done when** every item below has a concrete answer, with an example, committed stubs and types, and each manager has signed off at the bottom.

**Inputs:**
- `s0-findings.md`: S0's results and the tested pin;
- spec A2–A4, B2–B7;
- plan §4 (L0 row);
- `../17-parallel-and-journey.md` §1.

## 1. State and ownership (M1 merges all migrations)
- [ ] The tables and columns, including `agents.rank` and `role` stored separately, `role_hash`, `pack_version`, `host` and `binding_id`.
- [ ] Global rows vs project rows.
- [ ] The spec save transaction, with the "spec changed" message inside it.
- [ ] Task states and attempts (one current attempt; a stale submission refused). The submitted, checked and landed commits. **How non-code tasks are accepted:** a review or research task is done when the manager accepts its submission, with no landing.

## 2. Lifecycle and messages
- [ ] Admitted vs `prompt_result` vs settled, with example frames from S0.
- [ ] **Acknowledgement:** when a message counts as handled. **The operation key is `<message-id>/<step>`** when one message causes several changes.
- [ ] Recovery: `--resume <exact file>` plus an identity check; the interrupted prompt; the worktree kept; a supervisor that dies while its child survives.
- [ ] Stop vs cancel vs replace.

## 2b. The harness boundary: oh-my-pi behind one interface (M2)
All oh-my-pi-specific code lives in **one module**, `src/otto/runtime/harness/omp.py`. **Nothing else imports `omp-rpc` or knows omp's frames.** That keeps a different harness possible later, as an adapter rather than a rewrite.
- [ ] **The interface**, with types and an example for each call:
  - `start(launch)` → a session handle. `launch` holds the resolved model role or override, the config overlay, the skills, the instructions and the working directory;
  - `prompt(handle, text, op_key)` → admitted, or refused;
  - `events(handle)`: outcome (yield, error or abort), settled, sub-agent events;
  - `resume(session_ref)` → a handle with its identity checked, or a failure;
  - `stop(handle)`;
  - `login_status()` → which providers are signed in (for `doctor`), never reading tokens.
- [ ] **Which of omp's details leak through, deliberately:** the session file reference, the model-role names and the profile. Nothing else.
- [ ] **One fake behind the same interface,** used by the acceptance tests (the fake RPC process in D3), plus the real omp adapter tested against the installed binary.

## 3. The CLI and launch (M1 registers the commands; owners supply the handlers)
- [ ] Commands and arguments, the operation-key flag, and the `--json` fields for status, tasks, inbox and schedules.
- [ ] Identity lookup (`--as`, then `OTTO_AGENT`, then `.otto/agent`) and the binding-id check.
- [ ] How the CLI talks to the supervisor.
- [ ] `project new --from <folder>`.

## 4. The pack format (M3)
- [ ] The role file's front matter: the allowed ranks, skills and model role (defaulting to its rank's). **Front matter is the only place for skills.** `pack.toml` holds the seeds and schedules.
- [ ] The per-rank wrapper text. How the instructions are recorded (pack version plus role hash) for supervised agents and native helpers.
- [ ] Configuration precedence: the tool, then the pack, then the project, then a per-task override.

## 5. Landing and crash points (M4)
- [ ] The Git inputs (repo, worktree, base, check command), the commit evidence, refusal when the target moves, and Git/database reconciliation.
- [ ] **The named crash points** (each one a no-op hook in production):
  - the save after the commit, before the checkout update;
  - a message saved but not admitted;
  - admitted, with the bookkeeping lost;
  - the effect done, before acknowledgement;
  - a supervisor lost while its child survives;
  - Git landed, before the database records it.
- [ ] The test clock and barrier seam.

## 6. Schedule splits (to confirm)
- [ ] R4, C6, D3 and D2 are each split into preparation (against fixtures) and qualification, for the 20.5-day target.

## 7. Prerequisites the first day needs
- [ ] The package and CLI skeleton, initial CI and the temporary landing procedure: owned by M4, landed first.

## Sign-off
| Manager | Signed | Date |
|---|---|---|
| M1 State | | |
| M2 Runtime | | |
| M3 Pack and behaviour | | |
| M4 Delivery and integration | | |
