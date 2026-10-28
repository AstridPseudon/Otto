# Brief: EVIDENCE (xhard, 0.75 focused days)

**Outcome:** a result is accepted only when it has been verified. Specifically:
- `verify_dat_evidence` no longer returns `unknown` for a managed payload that has a verified manifest (`src/herzchen/domains/assessment/module.py`, around lines 80–98, where it returns `managed_payload_not_fully_verified`). A managed payload whose digests check out verifies.
- `accept_without_review` checks evidence digests the same way `accept` does (around line 951 of the same module).
- `assess` takes a runner result as candidate evidence (confirm this; add it if missing).
- A scope for a check-accepted task allows no review. A verified result can be accepted through that scope.

**Why it matters:** only verified results should be accepted. Today `unknown` is handled too leniently on one path, and `accept_without_review` skips the digest check that `accept` does (PLAN.md D4, §16; tasklist row EVIDENCE).

**Your lab:** `~/Developer/otto-claude-host/labs/EVIDENCE`, on branch `lab/EVIDENCE`, from `canon/main` at `198883c`. Work only here.

**Layer:** Herzchen model (PLAN.md D14). New code goes in `src/herzchen/domains/assessment/`. Nothing in `src/otto/`. The test: would another product that deploys agents need verification? Then it belongs in Herzchen. `tests/test_herzchen_boundary.py` must stay green.

**Files you own:**
- `src/herzchen/domains/assessment/` (verification, `accept_without_review`, `assess`'s evidence handling);
- your new tests (e.g. `tests/test_evidence_verification.py`).

**Do not touch:**
- `src/herzchen/fleet/` and `src/herzchen/adapters/` (other tasks are in them);
- `src/otto/portfolio/execution_host.py` and `install/controller/shared_operating_service.py` (POOL and STAGE);
- other tasks' files; `production/`; any Store, `~/.otto` or `~/.codex`; Codex's projects, vision and Native5;
- the running Otto service and `ottoctl` (never pass `ottoctl` `--help`).

**Build on what exists:** `verify_dat_evidence` (`module.py:80`), `accept` (around `:951`), `completion_blockers` and `completion_gate` (around `:909` and `:1046`), and the DAT content handler (`herzchen/content`) that resolves managed payloads.

**Your check.** Make it green and keep everything else green:
- `managed_result_verifies`, `unknown_never_accepted`, `no_review_scope_accepts_verified_result` (your new tests);
- show each new test failing on `canon/main` first, then passing;
- also ASTRA0: runner evidence through the real no-review acceptance path is accepted; a tampered payload is refused, and completion doesn't advance;
- every test file that imports a module you changed, each run on its own, twice.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_evidence_verification.py`

Tests run with no env prefix: pytest's `pythonpath` is set in `pyproject.toml`.

**Callers, including production:** if you change a signature, find every caller, including `install/controller/`.

**Existing tests:** don't change what an existing test asserts to make your change pass. If an expectation really must change, keep that change in its own commit and give the reason in your report. It lands only after an Opus decision (D19).

**Regression at the level the friction appears:** a managed payload with a tampered byte must be refused, and an `unknown` result must never reach acceptance.

**Deletion budget:** the lenient `unknown` branch on the managed path is replaced by the verification. Name what you delete.

**XHARD only: you lead, Haiku executes** (PLAN.md D10). Delegate almost all execution to the `haiku-worker` sub-agent (Agent tool, `subagent_type: "haiku-worker"`, Haiku 5.5 high): reading code, writing tests, making edits, running checks.
- Keep for yourself what needs judgment: the design and how the invariant holds, each sub-brief, reviewing each result (`git diff`, the test tail) against the invariant, and the final commit and report.
- Fix a line or two yourself if that's quicker; anything larger goes to a sub-agent.
- Each sub-brief is self-contained, because a sub-agent sees nothing else: the goal, the exact files and functions, what not to touch, the command to run, and what to report back.
- Run sub-agents in parallel only when their files don't overlap. If one fails twice on the same step, sharpen the brief or split the step.
- In your report, list each sub-agent: what it did, and whether you corrected it.

**XHARD invariant:** only verified results are accepted; a result binds exactly the evidence it was verified against.
**The plausible mistake to avoid:** treating `unknown` as a pass, or accepting a payload whose digest was not checked.

**Working rules:** commit work in progress to `lab/EVIDENCE` as you go; never run `git stash`, and never check out another commit in the lab. Commit only files you own, never `.brief.md`. Don't run `ottoctl`.

**When done:** commit to `lab/EVIDENCE` and don't push. Report the commit, the check runs (red, then green), what you deleted, each sub-agent and whether you corrected it, and anything you couldn't finish.
