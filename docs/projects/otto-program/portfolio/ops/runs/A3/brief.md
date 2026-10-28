# Brief: A3 (normal, 0.5 focused days)

**Outcome:** `otto show`, `otto open` and `otto status` work from the one `otto` entry point. `show` reads a project or task. `open` wraps Herzchen's authoring sessions (open, autosave, finish, release) and the project folder, with no new checkout path. `status` extends the portfolio status with the lab count and slot kinds. Claude and Codex lanes get identical output for `show`. A stale check-in is refused. The full row is `A3` in `~/Developer/otto-program/projects/program/tasklist.md` (line 40). Read that row first. Its acceptance evidence is the contract.

**Why it matters:** the program's managers and orchestrator read project and task state through these verbs. Today they have no single, consistent read of a project.

**Your lab:** `~/Developer/otto-claude-host/labs/A3`, on branch `lab/A3`, from `canon/main` at `4b3d9d7`. Work only here.

**Layer:** Otto product (PLAN.md D14, §11). The verbs, the entry point and the status view are Otto's. `tests/test_herzchen_boundary.py` must stay green. If an authoring-session call needs a change in Herzchen, keep it minimal and say so in your report.

**Files you own:**
- `src/otto/portfolio/cli.py`: the `show`, `open` and `status` wiring (A2 added `save` here, and it's landed, so this file is yours for this task);
- `src/otto/portfolio/status.py` (`portfolio_status`, around line 134): the lab count and the slot kinds;
- a new module for `show` and `open` (for example `src/otto/portfolio/show.py`);
- the new test file `tests/test_otto_show_status.py`.

**Build on what exists:**
- `src/herzchen/authoring/sessions.py` (open, autosave, finish, release; lines about 709, 1050, 1212, 1621);
- `src/otto/portfolio/document_editor_host.py` and `src/otto/portfolio/project_folder.py`;
- `observability_views` stays the history view: do not change it.

**Decisions made for you:**
- `run` and `heavy` subcommands are not built here. The runner (RUNNER) isn't on canon yet, so `otto run` has nothing to call. Leave both out, and say so in your report.
- The row's "the tool mints request keys" is part of the manager tools (MGR), not this task. Leave it out.

**Do not touch:**
- other tasks' files;
- `~/.otto`, `~/.codex`, `~/Documents/Codex`, `production/`, and any Store;
- the live owner. Do not run `ottoctl`, and never pass it `--help`;
- Codex's projects, vision and Native5;
- anything outside this lab.

**Your check.** Make it green and keep everything else green:
- `tests/test_otto_show_status.py` covers: `show` output is identical for the Claude and Codex lanes; `open` through the authoring session, then `finish` and `release`; `status` lists the lab count and the slot kinds; a stale check-in is refused and changes nothing;
- run tests with no env prefix: `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider <file>`;
- regression tests must fail on `canon/main` first; show that run too;
- run only the test files you changed or added. The landing gate sweeps every test file that imports a module you changed, twice (D19);
- run heavy commands as `~/Developer/otto-claude-host/bin/otto-heavy --weight 1 --purpose "A3 check" -- <cmd>`.

**Command forms.** Your Bash allowlist matches command prefixes only. Use `git -C <lab> …` (one git command per call), not `cd <lab> && …`. Use the tilde path `~/Developer/otto-claude-host/bin/otto-heavy` exactly. Don't use `env VAR=…`, `mktemp`, `/tmp` or `tar`. Keep scratch inside the lab and never commit it.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_otto_show_status.py`

**Callers, including production:** if you change a signature, a constructor argument or a default, find every caller and update it. That includes `install/controller/`, where production startup lives (D17).

**Existing tests:** do not change what an existing test asserts to make your change pass. If an expectation really must change, keep it in its own commit and give the reason in your report. It then needs an Opus decision (D19).

**Regression at the level the friction appears:** a stale check-in refused with nothing changed.

**Deletion budget:** name what your change replaces, or say "nothing: new verbs".

**Working rules:** commit work in progress to `lab/A3` as you go. Never run `git stash`, and never check out another commit in the lab. Commit only files you own, never `.brief.md`. **Never wait:** no Monitor, no sleep loops and no background job you wait on. Run tests in the foreground. If a question blocks you, decide it within this brief and say so in your report, or end your report with the question. Nobody answers mid-run.

**When done:** commit to `lab/A3` and don't push. Report the commit, the check runs (red, then green), what you deleted, and anything you couldn't finish.
