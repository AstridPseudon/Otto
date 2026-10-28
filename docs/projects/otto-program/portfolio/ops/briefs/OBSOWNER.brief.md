# Brief: OBSOWNER (xhard, 0.5 focused days)

**Outcome:** A native process receives useful input only after its exact caller binding has been constructed from serialized owner state, on the owner thread. The binding must be available before adapter transport begins.

**Why it matters:** Native commands need an authenticated caller identity at ingress. If binding registration is only queued asynchronously, a child can receive input before its caller is known, causing unauthenticated commands or failed manager launches.

**Your lab:** `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/OBSOWNER`, on branch `lab/OBSOWNER`, from `canon/main` at `3d91a35`. Work only here.

**Layer:** Otto product. Keep the change in the existing owner, gateway, and native caller ingress seams; do not redesign process-scope ownership.

**Files you own:**
- `src/otto/agents/gateway.py`
- `src/otto/agents/claude_adapter.py`
- `src/otto/portfolio/execution_host.py`
- `src/otto/portfolio/native_caller_ingress.py`
- `src/otto/portfolio/tests/test_native_caller_ingress.py`
- `src/otto/agents/tests/test_claude_binding.py`

**Other files:** You may edit other files directly required by the outcome, except the files under “Do not touch.” List each such file and why in your report.

**Do not touch:**
- `ops/bootstrap/perch.sh` and `tests/test_perch.py` (DISTURB is running);
- `tests/test_native_resume_trace.py` and `tests/test_fleet_custody.py` (CMDTMPDIR is running);
- `production/`, any Store, `~/.otto`, `~/.codex`, Codex's projects, vision and Native5;
- anything outside this lab.

**Build on what exists:** Reuse the ingress binding factory in `src/otto/portfolio/native_caller_ingress.py`, the owner request path in `src/otto/portfolio/execution_host.py`, and the adapter binding flow in `src/otto/agents/claude_adapter.py`. Preserve the gateway's existing owner-binding checks.

**Your check:** Add a barrier-controlled model stand-in and concurrent worker preparation test. Assert that the real binding construction runs on the owner thread, returns exactly one binding, and finishes before the child receives input. The thread-affinity assertion must fail before the fix; do not rely on dictionary-race timing. Keep all existing assertions intact.

Run:
`/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider src/otto/portfolio/tests/test_native_caller_ingress.py src/otto/agents/tests/test_claude_binding.py`

Also run `git diff --check`.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider src/otto/portfolio/tests/test_native_caller_ingress.py src/otto/agents/tests/test_claude_binding.py`

**Regression at the level the friction appears:** Native input ordering under concurrent worker preparation, checked with a barrier-controlled model stand-in.

**Invariant:** A native process receives input only after its exact caller binding is registered from serialized owner state.

**Plausible mistake:** Queueing registration asynchronously and allowing input first.

**Surfaces:** Unauthenticated native commands or failed manager launches.

**Deletion budget:** Replace the current asynchronous or unowned binding construction path; report which mechanism was removed or replaced.

**Working rules:** Never run `git stash` or check out another commit. Never run `ottoctl`. Don't wait or poll for long-running work. Keep tests running to completion. Codex can't commit; leave the work for the launcher to commit. Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.
