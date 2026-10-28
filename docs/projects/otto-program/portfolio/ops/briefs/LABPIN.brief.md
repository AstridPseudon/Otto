# Brief: LABPIN (xhard, 0.75 focused days)

**Outcome:** A lab is removed only for its exact captured landing occurrence. Bind the marker to the owner occurrence, assignment generation and commit; validate capture, marker, HEAD and retained ref under one exclusive lab lock through removal, including partial-removal recovery; reuse existing landing and Due records.

**Your lab:** `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/LABPIN`, on branch `lab/LABPIN`, from `canon/main`. Work only here.

**Layer:** Herzchen fleet. New code goes in `src/herzchen/fleet/`; keep Otto-specific capture and Due wiring in Otto. `tests/test_herzchen_boundary.py` must stay green.

**Files you own:** `src/otto/hostctl/product_service.py`, `src/otto/hostctl/fleet_landing.py`, `src/herzchen/fleet/landing.py`, `src/herzchen/fleet/labs.py`, `tests/test_fleet_custody.py`, and directly required caller tests such as `tests/test_external_owner_execution.py`.

**Other files:** you may also edit any other file your outcome directly requires, except files listed under “Do not touch”. Explain each additional file in your report.

**Do not touch:**
- BOOTLAND: `ops/bootstrap/land.sh`, `ops/bootstrap/otto-lab.sh`, `tests/test_bootstrap_gate.py`;
- EVENTPAGE: `src/herzchen/kernel/store.py`, `src/herzchen/content/packets.py`, `src/herzchen/domains/work/timeline.py`, `tests/test_eventpage.py`;
- CITECAN: `src/herzchen/domains/work/assignments.py`, `src/otto/portfolio/attention_binding.py`, `src/otto/portfolio/tests/test_operating_setup.py`, `tests/test_manager_journey_command.py`;
- FAILEDFENCE landing is active; avoid its files if you discover overlap;
- `production/`, any Store, `~/.otto` or `~/.codex`, Codex configuration, or anything outside this lab.

**Build on what exists:** Read `${TRANSFER_ROOT}/portfolio/ops/prework/LABPIN.md` and follow its six-step design. Reuse the existing `wrk.result` candidate, Due records, landing marker and lab lock. Read `${TRANSFER_ROOT}/portfolio/ops/brief-template.md` for all working rules.

**Your check.** First make the new startup capture race regression fail on canon, then pass in the lab. Preserve dirty-work and Git-ref protections. Run changed tests; the full-file landing sweep runs outside the worker sandbox.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_fleet_custody.py`

**Regression at the level the friction appears:** Race a real writer landing occurrence B after startup reads only occurrence A's Due but before sweep acquires custody; the sweep must retain B until B's own capture. Include partial-removal recovery coverage and preserve existing dirty/ref tests.

**XHARD only:**
- invariant: Cleanup authority applies to one captured occurrence and one lab incarnation.
- plausible mistake: Matching only task identity or validating before acquiring the deletion lock.

**Deletion budget:** Remove the two-field marker overwrite path, pre-lock marker/HEAD checks, unconditional marker erasure in create/resume, and task-name-only cleanup predicates they replace.

**Existing tests:** Do not change existing assertions without a written D19 decision. The prework says no assertion changes are expected; update synthetic marker/Due fixtures to carry exact occurrence pins. Replace the existing `LabFleet.remove` patch in `tests/test_fleet_custody.py` with a real fault setup while preserving its assertions.

**Working rules:** Never run `git stash`, check out another commit, run `ottoctl`, or pass it `--help`. Do not commit or push; the launcher commits on exit. Run tests in the foreground to completion. On Codex, any sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`. For XHARD, lead the design and review, delegate almost all execution to Luna sub-agents, and report each sub-agent and any corrections. Never weaken tests to pass in the worker sandbox; sandbox-only failures belong in your report for the landing gate.
