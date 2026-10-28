# Brief: CAPTUREEDIT (xhard, 0.75 focused days)

**Outcome:** A real Claude worker that changes a file using `Edit`, or writes and then edits it, lands successfully and settles completed. Capture the final bytes and digest from the worker's own checkpoint before landing rebase, tied to successful `Write` or `Edit` calls. Continue refusing out-of-lab paths, symlinks, and files untouched by successful calls. Include the auto-merged-on-rebase case from the task row.

**Why it matters:** The artifact capture path currently recognizes only successful `Write` calls. A normal Edit-only worker can land its work and then settle unknown, leaving its lab unswept. This blocks stage 3.

**Your lab:** The launcher creates this lab from current `canon/main`; work only here.

**Layer:** Otto product, real worker artifact capture.

**Files you own:** `src/otto/agents/claude_adapter.py` and focused tests directly covering Claude worker artifact capture and settlement. Edit other files only when directly required; list them with reasons.

**Do not touch:** Files owned by running workers: FACADEFD (`src/herzchen/command_ports.py`, `src/otto/portfolio/manager_journey_service.py`, `src/otto/portfolio/owner_bootstrap.py`, `src/herzchen/domains/assessment/module.py`, `src/otto/hostctl/service.py`, their focused tests); PERCH2C (`ops/bootstrap/perch.sh`, `ops/bootstrap/perch_report.py`, `ops/bootstrap/perch_stage2_evidence.py`, `ops/bootstrap/canary/project.json`, `tests/test_perch.py`); OWNERCOMPLETION (`src/otto/portfolio/execution_host.py`, `src/otto/portfolio/manager_journey_service.py`, and its focused tests). Also do not touch `production/`, any Store, `~/.otto`, `~/.codex`, or anything outside this lab.

**Build on what exists:** `capture_artifacts` in `src/otto/agents/claude_adapter.py` and the successful tool-call/checkpoint records already produced by the worker host. Preserve the distinction between authorized tool output and arbitrary lab changes.

**Your check:** Add real-owner/fake-stream regressions for Edit-only, Write-then-Edit, and a Write changed by landing auto-merge. Verify each successful worker settles completed and leaves no lab. Retain a negative case for a changed file not touched by a successful call and for unsafe paths. Run focused capture/worker tests only; do not run staging-owner tests in the worker sandbox.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_landing.py`

**Invariant:** A landed worker's result is exactly the bytes its own authorized tool calls produced.

**Plausible mistake to avoid:** Capturing the whole lab diff or landed tree, which could include bytes the worker never produced.

**Working rules:** Follow the Codex rules in `ops/brief-template.md`: no commits or pushes; the launcher commits on exit. Keep long tests running to completion. Any sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`. As XHARD lead, delegate execution and keep design, invariant review, and final review yourself.

**When done:** Report the commit, focused checks, red then green behavior, the auto-merge case, and any limitations. Stop and report if the brief contradicts the code.
