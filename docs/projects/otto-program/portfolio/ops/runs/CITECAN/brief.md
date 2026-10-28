# Brief: CITECAN (normal, 0.25 focused days)

**Outcome:** Every accepted completion input produces the canonical stored evidence-hash form. Persist the verified ref-to-digest mapping in canonical string-key form while preserving the original request payload for replay matching. The corrective reader must consume the canonical worker-result hash and compare the retained source manifest digest directly.

**Why it matters:** Equivalent accepted evidence inputs must remain usable by historical setup and corrective-task readers, and changed hashes must still refuse.

**Your lab:** The launcher creates your lab from current `canon/main` and copies this brief there. Work only in that lab.

**Layer:** Herzchen model. New canonical assignment evidence belongs in the Herzchen assignment model; Otto's corrective reader consumes that form.

**Files you own:** `src/herzchen/domains/work/assignments.py`, `src/otto/portfolio/attention_binding.py`, `src/otto/portfolio/tests/test_operating_setup.py`, `tests/test_manager_journey_command.py`.

**Other files:** You may edit any other file directly required by this outcome, except files under Do not touch. Explain additions in your report.

**Do not touch:** `production/`, any Store, `~/.otto` or `~/.codex`, Codex project configuration, or anything outside this lab. Running tasks own: BOOTLAND (`ops/bootstrap/land.sh`, `ops/bootstrap/otto-lab.sh`, `tests/test_bootstrap_gate.py`); CAPTUREEDIT (`src/otto/agents/claude_adapter.py`, `tests/test_landing.py`); EVENTPAGE (`src/herzchen/kernel/store.py`, `src/herzchen/content/packets.py`, `src/herzchen/domains/work/timeline.py`, `tests/test_eventpage.py`); LINECHECK (`src/herzchen/fleet/landing.py`, `src/otto/hostctl/product_service.py`, `tests/test_fleet_custody.py`); FAILEDFENCE landing (no worker remains; landing sweep is active).

**Build on what exists:** In `assignments.py`, keep validating each supplied digest against its exact evidence ref and canonicalize only after validation. Preserve request payload shape for idempotency. In `attention_binding.py`, use the canonical key for the retained `result_ref` and compare `source_set_digest` directly with the retained source manifest digest.

**Your check:** Add coverage for list, labelled-map and canonical-map accepted inputs across real completed tasks, plus the corrective completion reader. Keep exact evidence and corruption checks. Regressions must fail on canon first. Run the two focused files and report both results.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_manager_journey_command.py src/otto/portfolio/tests/test_operating_setup.py`

**Regression at the level the friction appears:** Complete real tasks with each accepted evidence-hash shape, then read historical setup and corrective-task coverage; all succeed with identical exact evidence, while changed hashes refuse.

**Working rules:** Never run `git stash`, check out another commit, or run `ottoctl`. Do not commit or push; leave work for the launcher to commit. Keep long tests running to completion. Any sub-agent must use `spawn_agent` with `model: "gpt-6-luna"`.

**When done:** Leave work for the launcher and report the commit, focused checks, changed files, and anything you couldn't finish. Stop and report if the brief contradicts canon or the outcome is unclear.
