# Brief: HOSTKIT (xhard, 1.5 focused days)

Title: One host contract: adding an agent harness is one implementation

**Outcome:** a host supplies, through one contract: how to launch a turn and resume a session; how to pass the MCP tools and a token; how to fence writes to a workspace; how to parse its output stream into events and usage; which models serve normal and xhard. Claude and Codex move behind it into `herzchen/fleet/hosts` (a new package). Unknown host kinds are refused. A fake third CLI in the tests proves a new harness needs only this. Codex has ONE binding afterwards.

**Why it matters:** the critical path runs HOSTKIT → LAB → TOOLS → ASK → MGR → REH → INSTALL. PLAN §1 and D14: adding a harness is one implementation; labs, capacity, tools and landing come for free.

**Your lab:** `~/Developer/otto-claude-host/labs/HOSTKIT`, on branch `lab/HOSTKIT`, from `canon/main` at `51fcfb9`. Work only here.

**Files you own:**
- the new package `src/herzchen/fleet/hosts/` (the contract plus the Claude and Codex implementations);
- `src/herzchen/adapters/host.py` (`CodexCliBinding`) and `src/otto/agents/herzchen_adapter.py` (line ~498 uses it), `src/otto/agents/codex_cli.py`, `src/otto/agents/claude_cli.py`, `src/otto/agents/claude_adapter.py`, `src/otto/portfolio/host_profiles.py` (the fallback at :52);
- new tests `tests/test_host_contract.py`.
Keep the moves behind the contract; don't rewrite the host behaviour.

**Do not touch:**
- `execution_host.py` (HOLD owns it right now);
- the capacity pool, heavy.py, `_eligible` (POOL);
- `production/`;
- any Store, `~/.otto` or `~/.codex`, and the running Otto service;
- `ottoctl` (do not run it, and never pass it `--help`);
- Codex's projects, vision and Native5;
- anything outside this lab.

**Build on what exists:** `agents/adapter_conformance.py` (the pure contract), `claude_cli`/`codex_cli` and `herzchen/adapters/host.py`. Read PLAN §3/HOSTKIT row and `herzchen/adapters/__init__.py` first.

**Keep one Codex binding.** Two exist today: `herzchen/adapters/host.py` (`CodexCliBinding`, used via `agents/herzchen_adapter.py:498`) and `agents/codex_cli.py`. Check which one the live service runs (grep the call paths), keep that one, and retire the other, naming it in your report.

**Your check.** Make it green and keep everything else green:
- `fake_harness_runs_full_loop`, `unknown_host_refused` and `one_codex_binding` in `tests/test_host_contract.py`; write them FIRST and show they fail on `canon/main`;
- the check command below, all green.

Check command: `~/Developer/otto-claude-host/bin/otto-heavy --weight 1 --purpose "HOSTKIT check" -- env PYTHONPATH=src:tests /opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_host_contract.py tests/test_adapter_conformance.py tests/test_host_neutral_defaults.py tests/test_codex_host_reader.py tests/test_host_bridge_transitions.py tests/test_claude_manager_admission.py tests/test_codex_artifact_capture.py`

Regression at the level the friction appears: a host with an unknown kind is refused with a clear error, not silently given Codex.

**XHARD only:**
- invariant: moving a host behind the contract changes none of its sandbox or session flags.
- the plausible mistake to avoid: one host's flags drift while the other host's tests pass. Before you move a host, record its launch flags (sandbox, session, workspace) from the current code; after the move, assert the same flags for each host in test_host_contract.py.

**Deletion budget:** the second Codex binding (name it), and the Codex fallback in host_profiles.py. Name anything else you remove.

**When done:** commit to `lab/HOSTKIT` (only the files you own; never `.brief.md`, `.worker.json` or `.worker.err`) and don't push. Report the commit, the red and green runs, the binding you kept and retired, the flags you recorded, what you deleted, and anything you couldn't finish.
