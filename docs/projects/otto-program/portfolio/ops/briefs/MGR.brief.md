# Brief: MGR (normal, 1.5 focused days)

**Outcome:** Make project managers clean, project-scoped event-driven principals. Store one short host-neutral base manager brief in Otto and compose it at activation with project-specific brief and manager notes; expose the effective composition. Give each manager a project-scoped identity and add `whoami`, `status`, `show`, `save` (within allowance), `answer`, `route` (reroute or retry), and `report` to the existing MCP facade, with request keys minted by the tool. Create the manager session at activation and resume it only for judgment events (worker ask, second failed landing, out-of-allowance change, or landed milestone); it never polls. Reuse the existing continuity/replacement, identity, project routing, handoff, and DueRecord advisor wake paths; hold a failed acquisition without auto-retry and remove the hourly `sense_check` poll. Escalations use Megado's oracle request format.

**Why it matters:** Each project needs a manager that can exercise judgment within its own authority and continue from a concise handoff when a session is replaced. Event-driven wakes avoid routine polling while preserving a human escalation path.

**Your lab:** `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/MGR`, on branch `lab/MGR`, from `canon/main` at `5a99f2f183264f903df84cff6f1df54b971f33df`. Work only here.

**Layer:** Otto product. New code belongs under `src/otto/`; keep the MCP and host wiring in Otto and reuse shared portfolio services.

**Files you own:** `src/otto/hostctl/manager_client.py`; `src/otto/portfolio/operating_brief.py`, `role_context.py`, `manager_replacement.py`, `manager_continuity.py`, `identity_context.py`, `project_services.py`, `manager_handoff.py`, `advisor_delivery.py`, and `manager_journey_service.py`; `src/otto/portfolio/tests/test_manager_consumption.py`; `tests/test_manager_guide.py`, `test_manager_journey_service.py`, `test_manager_continuity.py`, `test_manager_handoff.py`, `test_manager_consumption_adoption.py`, `test_manager_advisor_followup_command.py`, and `test_manager_service_continuation.py`. If another directly required file is missing from this list, stop and ask with its path and reason.

**Do not touch:**
- other tasks' files;
- `production/` (the Astrid film's folder; it means nothing for code);
- any Store, `~/.otto` or `~/.codex`;
- Codex's projects, vision and Native5;
- anything outside this lab.

**Build on what exists:** The existing BASE and mandate brief pipeline (`operating_brief.py`, `role_context.py`); `_host_role_guidance` for host selection; `manager_replacement` and `manager_continuity` for the single replacement path; `identity_context` for identity; `project_services` for routing; `manager_handoff` for fresh-session read-in; and the existing advisor DueRecord wake. Remove the hard-coded Codex guidance and hourly `sense_check` path called out by the task row, retaining the existing host-neutral behavior.

**Your check.** Add or update regression coverage for project isolation, composed effective context, event-only manager wakes, and project/role identity. Keep existing expectations intact unless an expectation genuinely changes; report any changed assertion separately for D19 review. Run the focused tests below with no environment prefix; `pyproject.toml` sets pytest's `pythonpath`. Run heavy commands as `otto-heavy --weight 1 --purpose "MGR" -- <cmd>`. Long runs must finish; use a long timeout such as `timeout_ms: 1800000`.

**Check command:** `otto-heavy --weight 1 --purpose "MGR" -- /opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider src/otto/portfolio/tests/test_manager_consumption.py tests/test_manager_guide.py tests/test_manager_journey_service.py tests/test_manager_continuity.py tests/test_manager_handoff.py tests/test_manager_consumption_adoption.py tests/test_manager_advisor_followup_command.py tests/test_manager_service_continuation.py`

**Callers, including production:** If you change a signature, constructor argument or default, find every caller and update it, including production startup where applicable.

**Existing tests:** Don't change what an existing test asserts to make your change pass. If an expectation must change, list each changed assertion with its reason; it lands only after an Opus decision (D19).

**Regression at the level the friction appears:** Verify the complete manager journey from project activation through identity/context/tools, event-triggered judgment, continuity replacement, and escalation; prove another project's manager cannot act on this project.

**Working rules:** Never run `git stash`, check out another commit, run `ottoctl`, or pass it `--help`. Never wait with a monitor, sleep loop, or background job. If a question blocks you, decide it within this brief or end your report with the question.
- **On Codex** (Luna or Sol, the program's host since 16 Oct): you can't commit, because Codex's sandbox keeps `.git` read-only. Leave your work in the lab and `run-task.sh` commits it when you exit; don't work around the sandbox. A test that fails with `sandbox_apply: Operation not permitted` needs a sandbox of its own; list it in your report. **Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.**

**When done:** Leave the work for the launcher to commit. Report the commit, checks, behavior removed, and anything unfinished. Stop and ask if the brief contradicts the code.
