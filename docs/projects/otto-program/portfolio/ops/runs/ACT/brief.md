# Brief: ACT (xhard, 1.5 focused days)

**Outcome:** Activating a project queues safely while another project runs, and attaches its views on activation. Activation never interrupts another project's running turn.

**Why it matters:** This covers per-project activation and self-service bring-up alongside DISPATCH. The invariant is that activating one project never disturbs another's running turn; the plausible mistake is recomposing views while a turn runs.

**Your lab:** `labs/ACT`, on branch `lab/ACT`, from `canon/main` at the launcher's current SHA. Work only here.

**Layer:** Otto product. New code goes in `src/otto/portfolio/`.

**Files you own:** `src/otto/portfolio/project_service.py`, the existing project activation and view-attachment modules called by it, and focused tests for activation queueing and view attachment. Before editing, identify the exact existing caller modules and list the exact paths in your report. Do not edit `herzchen/domains/work/` or save/batch modules; SAVEFIX is being prepared there.

**Do not touch:**
- other tasks' files;
- `production/` (the Astrid film's folder; it means nothing for code);
- any Store, `~/.otto` or `~/.codex`;
- Codex's projects, vision and Native5;
- anything outside this lab.

**Build on what exists:** the project services and activation flow; `project_service.py:346` currently refuses attachment. Reuse the existing project/view composition and queue/custody mechanisms rather than adding a second ledger.

**Your check.** Make it green and keep everything else green:
- Cover `activate_while_other_runs`, `busy_queues_once`, and `view_attached_on_activation` with focused regression tests; run the relevant test files.
- Regression tests must fail on `canon/main` first; show both runs.
- Run tests with no env prefix (the Bash allowlist refuses one): `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider <file>`; run heavy commands through `otto-heavy --weight N --purpose "ACT" -- <cmd>`.
- Do not sweep the rest: the landing gate runs every test file that imports a module you changed, twice.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests -k "activation or activate or view_attached"`

**Regression at the level the friction appears:** activate a second project while the first project's turn is running; prove it queues exactly once and attaching views does not recompose or disturb the first turn.

**XHARD only:**
- invariant: Activating one project never disturbs another's running turn.
- plausible mistake to avoid: Recomposing views while a turn runs, losing custody.

**Deletion budget:** remove or replace the current refusal at `project_service.py:346` with the queueing activation path; name the retired mechanism in your report.

**Working rules:** never run `git stash`, and never check out another commit in the lab. Don't run `ottoctl`, and never pass it `--help`. **Never wait:** no Monitor, no sleep loops and no background job you then wait on; run tests in the foreground. If a question blocks you, decide it within the brief and say so in your report, or end your report with the question. Nobody answers mid-run.
- **On Codex** (Luna or Sol, the program's host since 16 Oct): you can't commit, because Codex's sandbox keeps `.git` read-only. Leave your work in the lab and `run-task.sh` commits it when you exit; don't work around the sandbox. A test that fails with `sandbox_apply: Operation not permitted` needs a sandbox of its own, which can't nest inside yours: list it in your report, and the landing gate runs it outside. **Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.**

**XHARD only: you lead, a cheaper model executes** (PLAN.md D10). On Codex (you are Sol), use `spawn_agent` with `model: "gpt-6-luna"`.
- Keep for yourself what needs judgment: the design and how the invariant holds, each sub-brief, reviewing each result (`git diff`, the test tail) against the invariant, and the final commit and report.
- Each sub-brief is self-contained, because a sub-agent sees nothing else: the goal, the exact files and functions, what not to touch, the command to run, and what to report back.
- Run sub-agents in parallel only when their files don't overlap. If one fails twice on the same step, sharpen the brief or split the step.
- In your report, list each sub-agent: what it did, and whether you corrected it.

**When done:** leave changes for the launcher to commit and don't push. Report the commit, the check runs (red, then green), what you deleted, and anything you couldn't finish. Stop and ask if the brief contradicts the code.
