# Brief: A4 (normal, 0.25 focused days)

**Outcome:** Views are generated from Otto's canonical records and never read back as authority; registration stops parsing task tables from generated views. Editing a generated view changes nothing, and `show` says so.

**Why it matters:** The generated run view must remain a projection of owner-backed records. Registration should use its source bundle, not a projection that can be edited independently.

**Your lab:** `labs/A4`, on branch `lab/A4`, from `canon/main`. Work only here.

**Layer:** Otto product. Keep this in `src/otto/hostctl/`; it is registration and generated-view wiring, not a reusable agent product. `tests/test_herzchen_boundary.py` must stay green.

**Files you own:**
- `src/otto/hostctl/bundle.py`
- `src/otto/hostctl/register.py`
- `src/otto/hostctl/serve.py`
- `tests/test_hostctl_bundle.py`
- `tests/test_hostctl_serve.py`

**Do not touch:**
- other tasks' files;
- `production/` (the Astrid film's folder; it means nothing for code);
- any Store, `~/.otto` or `~/.codex`;
- Codex's projects, vision and Native5;
- anything outside this lab.

**Build on what exists:** `bundle.py` parses source task tables; `register.py` calls `read_bundle` on the supplied source bundle; `serve.py` renders the run view from owner records and marks it as generated.

**Your check.** Make it green and keep everything else green:
- Run tests with no env prefix (your Bash allowlist refuses one; `pyproject.toml` sets pytest's `pythonpath`): `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider <file>`, or through `~/Developer/otto-claude-host/bin/otto-heavy --weight N --purpose "A4" -- /opt/homebrew/bin/python3.11 -m pytest …`;
- regression tests must fail on `canon/main` first; show both runs;
- run the test files you changed or added; don't sweep the rest: the landing gate runs every test file that imports a module you changed, twice, and re-runs a failure beside `canon/main` before it refuses (D19);
- run heavy commands as `otto-heavy --weight N --purpose "A4" -- <cmd>`.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_hostctl_bundle.py tests/test_hostctl_serve.py`

**Callers, including production:** if you change a signature, a constructor argument or a default, find every caller and update it. That includes `install/controller/`, where production startup lives: no unit test starts it, but the staging Otto does at landing (D17).

**Existing tests:** don't change what an existing test asserts to make your change pass. If an expectation really must change, keep the change in its own commit (on Codex, list each changed assertion as file:line instead) and give the reason in your report. It lands only after an Opus decision (D19).

**Regression at the level the friction appears:** edit a generated view and prove owner-backed `show` is unchanged and identifies the view as generated; prove registration parses task tables only from the original bundle.

**Deletion budget:** make the generated view explicitly read-only as an authority and remove any registration path that parses task tables from it.

**Working rules:** never run `git stash`, and never check out another commit in the lab. Don't run `ottoctl`, and never pass it `--help`. **Never wait:** no Monitor, no sleep loops and no background job you then wait on; run tests in the foreground. If a question blocks you, decide it within the brief and say so in your report, or end your report with the question. Nobody answers mid-run.
- **On Codex** (Luna or Sol, the program's host since 16 Oct): you can't commit, because Codex's sandbox keeps `.git` read-only. Leave your work in the lab and `run-task.sh` commits it when you exit; don't work around the sandbox. A test that fails with `sandbox_apply: Operation not permitted` needs a sandbox of its own, which can't nest inside yours: list it in your report, and the landing gate runs it outside. **Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.**
- **On Claude:** commit work in progress to `lab/<TASK>` as you go, only files you own, never `.brief.md`. **Any sub-agent you start uses `model: "haiku"`**, never Opus or Sonnet.

**When done:** commit to `lab/A4` (on Codex, leave it for the launcher to commit) and don't push. Report the commit, the check runs (red, then green), what you deleted, and anything you couldn't finish. Stop and ask if the brief contradicts the code.
