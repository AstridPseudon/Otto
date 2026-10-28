# Brief: AUTODISPATCH2 (xhard, 1.0 focused days)

**Outcome:** An automatic launch completes through `admit_execution` without a manager occurrence; an automatic failure settles with a reason or retries once on the next pump without leaving an alias stuck.

**Your lab:** `~/Developer/otto-claude-host/labs/AUTODISPATCH2`, on branch `lab/AUTODISPATCH2`, from `canon/main` at `589d184888ffbd8e25f61eb9fa7eb7a40e19ec3d`. Work only here.

**Layer:** Otto product. New code goes in `src/otto/portfolio/` or `src/otto/hostctl/` as appropriate; this is Otto's owner dispatch integration.

**Files you own:**
- `src/otto/portfolio/manager_journey_service.py`
- `src/otto/hostctl/product_service.py`
- `tests/test_manager_journey_service.py`
- `tests/test_fleet_dispatch.py`

**Other files:** You may edit any other file directly required by the outcome, except the files under Do not touch; explain each in your report.

**Do not touch:**
- Files owned by running tasks: STAGESETUP owns `src/otto/hostctl/config.py`, `src/otto/hostctl/register.py`, `src/otto/hostctl/cli.py`, `ops/bootstrap/staging.sh`, and its tests; MGR landing is in progress. Keep changes disjoint.
- `production/`, any Store, `~/.otto` or `~/.codex`, Codex's projects/vision/Native5, or anything outside this lab.

**Build on what exists:** `manager_journey_service.py:_current_manager_schedule` (around 331-364) currently requires a manager Due; `product_service.py:candidates` (around 768), `launch` (around 828), and `admit_execution` are the existing dispatch and admission path. Keep `admit_execution` as the only launch gate.

**Your check:** On staging with the fake harness and no manager turn, admitted ready A launches and lands; B launches only after A completes; unadmitted C never launches; a failed launch settles or retries, never sticks. Add focused regressions for the admission, sequencing and failure cases. Regression tests must fail on canon first and pass in the lab.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_manager_journey_service.py tests/test_fleet_dispatch.py`

**Regression at the level the friction appears:** Automatic admission, serial dispatch, and failed launch recovery on staging.

**Invariant:** Only `admit_execution` launches, once per task generation, manager or not. Avoid bypassing the gate or retrying an attempt whose effect is unknown.

**Deletion budget:** Do not add a parallel launch path; replace the manager-occurrence dependency in automatic dispatch while retaining today's check for manager-prepared Due records.

**Working rules:** Never run `git stash`; don't check out another commit in the lab; don't run `ottoctl`; never wait or poll. Run tests in the foreground. On Codex, don't commit or work around read-only `.git`; the launcher commits on exit. Give long tests a long timeout. Any sub-agent is `spawn_agent` with `model: "gpt-6-luna"`.

**XHARD:** Lead the design and invariant review; delegate most exploration, implementation and test execution to Luna (`gpt-6-luna`) sub-agents with self-contained briefs. Review each diff and test tail. If a sub-agent fails twice on a step, sharpen the brief or split the work.

**When done:** Report commit, red/green checks, replaced mechanism, and anything incomplete; leave edits in the lab for the launcher.
