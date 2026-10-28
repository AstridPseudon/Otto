# Brief: LANDBATCH (xhard, 1.0 focused days)

**Outcome:** Implement `land.sh --batch A B C ...` for up to eight tasks. Merge labs into one candidate in batch order, dropping textual conflicts with a clear reason; run every task's check, one sweep over the union of changed files using GATEPAR's parallel fail-fast sweep, added-test and orphan checks, per-task D19 decisions, and stage checks once. A green batch pushes each task as its own `Land <TASK>:` merge commit and pushes once. Any red result refuses the whole batch with NEW failures attributed to batch tasks whose changed files the failing test imports. Keep single-task landing behavior unchanged. The manager will batch only rows whose check-run passed and whose D19 is settled; on refusal, drop an attributable task and re-batch, otherwise split the batch in half.

**Why it matters:** Dozens of committed rows are waiting behind repeated full gate sweeps. Batching lets one candidate receive one gate run while preserving per-task commits and all-or-nothing custody.

**Your lab:** Launcher creates `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/LANDBATCH` on branch `lab/LANDBATCH`. Build on GATEPAR's parallel sweep implementation; the manager will rebase this lab onto GATEPAR before landing if it is not already in canon. Do not edit another task's lab.

**Layer:** Otto product. This is landing infrastructure under `ops/bootstrap`.

**Files you own:** `ops/bootstrap/land.sh`, `tests/test_bootstrap_gate.py`.

**Other files:** Edit another file only if the batch behavior directly requires it; list each added file and reason in your report.

**Do not touch:** Files outside your lab; `production/`, Stores, `~/.otto`, `~/.codex`, Codex projects, vision and Native5. ROOTFILE and GATEPAR have separate labs that also change the gate files; do not read or edit those labs' working trees.

**Build on what exists:** `ops/bootstrap/land.sh` already builds the candidate and runs per-task checks, computes changed files and test sweep, judges failures against BASE, and emits per-task merge commits; GATEPAR's run/judge split at approximately lines 395-440 runs the union's sweep in parallel and judges serially. Preserve the single-task path and existing checks, BASE comparison, D19 handling, stage checks, log format, and push custody.

**Your check.** Add gate tests in `tests/test_bootstrap_gate.py`: green three-task batch creates three per-task commits; a textual-conflict task drops out while the other tasks land; one task's NEW failure refuses the entire batch and identifies its source task; single-task behavior remains unchanged. Test any failure-ownership attribution edge cases needed to establish the invariant. Run the full gate test file; demonstrate new regressions red on canon then green.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_bootstrap_gate.py`

**Regression at the level the friction appears:** A batch with mixed task outcomes proves the pushed history is either complete with one commit per accepted task, or unchanged on refusal, and each failure is attributed to its introducing task.

**Invariant:** Canon custody across several labs in one push: a locally plausible batch cannot land a task whose own failure was masked, push a partial merge, or misattribute a failure.

**Plausible mistake:** Treat the merged candidate as one anonymous lab and run only a union check; that can hide which task introduced the failure or permit a partial push.

**Deletion budget:** Reuse the existing single-task candidate and gate functions with a batch driver; do not add a second independent gate implementation.

**Working rules:** Follow all XHARD rules in `ops/brief-template.md`. Any sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`. Never commit or push from Codex; leave the changes for the launcher. Do not wait on tests; give long test commands a long timeout.
