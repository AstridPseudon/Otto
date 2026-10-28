# Brief: CONV (normal, 0.75 focused days)

**Outcome:** A save with a task's brief documents round-trips through `show`; `otto save` no longer refuses nonempty `documents`.

**Why it matters:** A saved project must retain the task's instructions when it is exported and shown again.

**Your lab:** `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/CONV`, on branch `lab/CONV`, from `canon/main`. Work only here.

**Layer:** Otto product. This change belongs in `src/otto/portfolio/save.py`; do not move it into Herzchen.

**Files you own:**
- `src/otto/portfolio/save.py`
- `tests/test_otto_save.py`

**Do not touch:**
- other tasks' files;
- `production/` (the Astrid film's folder; it means nothing for code);
- any Store, `~/.otto` or `~/.codex`;
- Codex's projects, vision and Native5;
- anything outside this lab.

**Build on what exists:** `parse_save_file` already accepts the `documents` key but rejects nonempty values at `src/otto/portfolio/save.py:36-38`; its seed includes project, tasks, and criteria at `:76`. Extend the seed and its consumers only as needed to preserve task brief documents through the existing save/show path.

**Your check.** Make it green and keep everything else green:
- run the task's own test file with no env prefix: `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_otto_save.py`;
- regression tests must fail on `canon/main` first; show both runs;
- run the test files you changed or added; don't sweep the rest: the landing gate runs every test file that imports a module you changed, twice, and re-runs a failure beside `canon/main` before it refuses (D19);
- run heavy commands as `otto-heavy --weight N --purpose "CONV" -- <cmd>`.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_otto_save.py`

**Callers, including production:** if you change a signature, a constructor argument or a default, find every caller and update it. That includes `install/controller/`, where production startup lives: no unit test starts it, but the staging Otto does at landing (D17).

**Existing tests:** don't change what an existing test asserts to make your change pass. If an expectation really must change, keep the change in its own commit (on Codex, list each changed assertion as file:line instead) and give the reason in your report. It lands only after an Opus decision (D19).

**Regression at the level the friction appears:** save a task with a brief document, then show it and verify the document is retained.

**Deletion budget:** extend the existing save route; remove the rejection that exists solely to block nonempty `documents`.

**Working rules:** never run `git stash`, and never check out another commit in the lab. Don't run `ottoctl`, and never pass it `--help`. **Never wait:** no Monitor, no sleep loops and no background job you then wait on; run tests in the foreground. If a question blocks you, decide it within the brief and say so in your report, or end your report with the question. Nobody answers mid-run.
- **On Codex** (Luna or Sol, the program's host since 16 Oct): you can't commit, because Codex's sandbox keeps `.git` read-only. Leave your work in the lab and `run-task.sh` commits it when you exit; don't work around the sandbox. A test that fails with `sandbox_apply: Operation not permitted` needs a sandbox of its own, which can't nest inside yours: list it in your report, and the landing gate runs it outside. **Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.**
- **On Claude:** commit work in progress to `lab/<TASK>` as you go, only files you own, never `.brief.md`. **Any sub-agent you start uses `model: "haiku"`**, never Opus or Sonnet.
