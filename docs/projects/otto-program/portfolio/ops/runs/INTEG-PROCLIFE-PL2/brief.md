# Brief: INTEG-PROCLIFE-PL2 (xhard, 0.75 focused days)

**Outcome:** Preserve claim and parent accounting for unresolved nested scopes when recovery records are unavailable; integrate PL2 (`eec2b98`) without inventing a host-wide latch.

**Why it matters:** A surviving nested scope must keep the capacity reservation that protects its work even when its parent recovery record cannot be verified. Losing that accounting lets new work consume capacity still held by surviving work.

**Your lab:** created by the launcher from current `canon/main`; work only there.

**Layer:** Herzchen fleet. New reusable runner behavior belongs in `src/herzchen/fleet/`.

**Files you own:** `src/herzchen/fleet/runner/runner.py`, `tests/test_runner.py`.

**Other files:** You may edit another file directly required by this outcome, except files under “Do not touch.” List each added path and why in your report.

**Do not touch:** `ops/bootstrap/perch.sh`, `tests/test_perch.py` (DISTURB); `src/otto/agents/gateway.py`, `src/otto/agents/claude_adapter.py`, `src/otto/portfolio/execution_host.py`, `src/otto/portfolio/native_caller_ingress.py`, `src/otto/portfolio/tests/test_native_caller_ingress.py`, `src/otto/agents/tests/test_claude_binding.py` (OBSOWNER); `production/`, Stores, `~/.otto`, `~/.codex`, Codex projects/vision/Native5, or anything outside this lab.

**Build on what exists:** `Runner._parent_lease` in `src/herzchen/fleet/runner/runner.py` matches a peer to an open lease using captured custody; `Runner.submit` creates nested records with `nested_in`, zero units, and parent-child links. Preserve the existing exact-process custody checks and accounting semantics.

**Your check:** Add focused recovery regressions for unresolved nested scopes when recovery records are missing or cannot be verified. Prove each surviving child reservation remains accounted for, and that new work cannot consume its capacity; include a verified-parent control so ordinary nesting still works. Keep all existing assertions intact. First show the regression fails on canon/main, then passes on the change. Run the runner tests and `git diff --check` to completion; report the exact results. Do not run a staging owner in the worker sandbox.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_runner.py`

**Regression at the level the friction appears:** Recovery with a missing or unverifiable parent record while the nested scope survives; assert its reservation persists and no unrelated request is admitted against it.

**Invariant:** Every surviving scope retains its reservation through recovery.
**Plausible mistake:** Dropping a zero-unit child when ancestry cannot be verified.
**Surfaces:** New work consumes capacity still held by surviving work.

**Working rules:** Never stash or check out another commit. Don't run `ottoctl`; never pass it `--help`. Never wait or poll. Run tests to completion with a long timeout. The landing gate runs outside the sandbox where needed. On Codex, leave work for the launcher to commit; don't work around read-only `.git`. Any sub-agent uses `spawn_agent` with `model: "gpt-6-luna"`.

**XHARD only: lead, cheaper model executes.** Delegate almost all execution to Luna sub-agents with `spawn_agent` and `model: "gpt-6-luna"`; keep the design, invariant review, and final report for yourself. Sub-briefs must name exact files, functions, constraints, command, and expected report. Run sub-agents in parallel only when their files do not overlap. Never commit or push.
