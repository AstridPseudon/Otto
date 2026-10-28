# Brief: SAVEFIX (normal, 1.25 focused days)

**Outcome:** Saves are atomic and lossless, and refusals explain how to recover. A failed first save leaves no project, task, event or receipt; cycle checks cover retained tasks; `otto.plan.lines` supports validated replacement and key removal; unsupported fields are named; stale refusals give `next_action` and a meaningful diff; busy Store errors offer retry guidance; batch history leaves the project record; and saved criteria become assessment criteria visible through `show`.

**Why it matters:** The save path is the boundary between project planning and the durable work-domain state. A refusal or partial save must not silently lose a user's plan.

**Your lab:** `labs/SAVEFIX`, on branch `lab/SAVEFIX`, from `canon/main`. Work only here.

**Layer:** Herzchen model. New code goes in `src/herzchen/domains/work/`. The test: would another product that deploys agents need it? Then it goes in Herzchen, and Otto passes in its own names, roles and policies; Otto keeps only the wiring. `tests/test_herzchen_boundary.py` must stay green.

**Files you own:** `src/herzchen/domains/work/batches.py`, `src/herzchen/domains/work/sheet.py`, `src/herzchen/domains/work/module.py`, `src/otto/portfolio/save.py`, `tests/test_otto_save.py`, `tests/test_hostctl_portfolio_apply.py`.

**Do not touch:**
- other tasks' files;
- `production/` (the Astrid film's folder; it means nothing for code);
- any Store, `~/.otto` or `~/.codex`;
- Codex's projects, vision and Native5;
- anything outside this lab.

**Build on what exists:** Reuse the batch save and project update path in `batches.py`, sheet validation in `sheet.py`, and Otto's save parsing in `save.py`; preserve the existing work-domain interfaces and add regression coverage to the existing save/apply tests.

**Your check.** Make it green and keep everything else green:
- Run tests with no env prefix (your Bash allowlist refuses one; `pyproject.toml` sets pytest's `pythonpath`): `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider <file>`, or through `~/Developer/otto-claude-host/bin/otto-heavy --weight N --purpose "<TASK>" -- /opt/homebrew/bin/python3.11 -m pytest …`;
- regression tests must fail on `canon/main` first; show both runs;
- run the test files you changed or added; don't sweep the rest: the landing gate runs every test file that imports a module you changed, twice, and re-runs a failure beside `canon/main` before it refuses (D19);
- run heavy commands as `otto-heavy --weight N --purpose "<TASK>" -- <cmd>`.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_otto_save.py tests/test_hostctl_portfolio_apply.py`

**Callers, including production:** if you change a signature, a constructor argument or a default, find every caller and update it. That includes `install/controller/`, where production startup lives: no unit test starts it, but the staging Otto does at landing (D17).

**Existing tests:** don't change what an existing test asserts to make your change pass. If an expectation really must change, keep the change in its own commit (on Codex, list each changed assertion as file:line instead) and give the reason in your report. It lands only after an Opus decision (D19).

**Regression at the level the friction appears:** a malformed first save, a second save that introduces a cycle through a retained task, and a stale-save refusal followed by reread and reapply.

**Deletion budget:** Move batch-history state out of the project record and remove the old per-project copy.

**Working rules:** never run `git stash`, and never check out another commit in the lab. Don't run `ottoctl`, and never pass it `--help`. **Never wait:** no Monitor, no sleep loops and no background job you then wait on; run tests in the foreground. If a question blocks you, decide it within the brief and say so in your report, or end your report with the question.
- **On Codex** (Luna or Sol, the program's host since 16 Oct): you can't commit, because Codex's sandbox keeps `.git` read-only. Leave your work in the lab and `run-task.sh` commits it when you exit; don't work around the sandbox. A test that fails with `sandbox_apply: Operation not permitted` needs a sandbox of its own, which can't nest inside yours: list it in your report, and the landing gate runs it outside. **Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.**
- **On Claude:** commit work in progress to `lab/<TASK>` as you go, only files you own, never `.brief.md`. **Any sub-agent you start uses `model: "haiku"`**, never Opus or Sonnet.

**When done:** commit to `lab/SAVEFIX` (on Codex, leave it for the launcher) and don't push. Report the commit, the check runs (red, then green), what you deleted, and anything you couldn't finish. Stop and ask (the `ask` route, or end your report with a question) if the brief contradicts the code.
