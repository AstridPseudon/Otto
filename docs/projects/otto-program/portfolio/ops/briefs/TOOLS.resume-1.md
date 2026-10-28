# TOOLS resume (posted by the manager 2026-10-16T13:44:05Z; the orchestrator's 13:36Z answer)

Your commits `9ca4475`, `213e2fd` and `6e5725b` stay on `lab/TOOLS`. Your report is in `ops/runs/TOOLS/worker.json`. Keep the five-tool change: it is this row's own outcome. No D19 is needed for it.

**Amended TOOLS row (16 Oct 13:36Z, the orchestrator):**
- **Probe first, on the live Claude CLI with the exact launcher flags, in a lab.** Read, Grep and Glob of a file outside the lab must be refused; a file inside must be allowed; the `otto` server must answer from the sandbox. Record the transcript in `ops/runs/TOOLS/`. (Your earlier probe used `sandbox-exec` only.)
- **Scope the goldens.** They pin `Glob` and `Grep` unscoped, while Read, Write and Edit are scoped to `{WS}/**`. Scope Grep and Glob, or keep them unscoped only if the probe shows the sandbox confines them, recorded as an assumption test.
- **Codex:** one `codex exec` MCP call under workspace-write, or say why not.
- The owner operations behind `check` and `done` (`worker-check`, `worker-done`) now belong to LAND's row. The token and the MCP config at launch belong to DISPATCH's row. Do NOT add them here.

**Acceptance:** `worker_check_never_counts_as_acceptance`, `token_scoped_to_assignment` and `fake_harness_uses_tools` green; the probe transcript in `ops/runs/TOOLS/`.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_tools.py tests/test_host_contract.py tests/test_usage_capture.py src/otto/agents/tests/test_claude_binding.py tests/test_herzchen_boundary.py`. Run it through `otto-heavy`.

**Working rules, as before:** commit to `lab/TOOLS`, never push, never stash, never check out another commit. Never wait: no Monitor, no sleep loops. Any sub-agent uses `model: "haiku"`. Report the commit, the probe result, the check runs (red, then green), and anything you couldn't finish.
