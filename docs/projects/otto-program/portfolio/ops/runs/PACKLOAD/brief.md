# Brief: PACKLOAD (xhard, 1.0 focused day)

**Outcome:** Herzchen loads its own managed packs without importing Astrid. Add a native discoverer and loader for packs inside Herzchen's source tree, producing the same provenance record as Astrid: `pack_id`, `source_kind`, `source_revision`, `source_tree_sha256`, `source_manifest_sha256`, `source_inventory_identity`, `pack_root`, and `manifest_path`. Keep Astrid APIs injectable for packs outside Herzchen's tree; the default path must never import Astrid.

**Why it matters:** Herzchen is the base layer that Astrid builds on. An owner installed from canon does not have Astrid available, so importing it prevents evidence capture and blocks the stage-2 journey.

**Your lab:** created by the launcher from `canon/main` at `f1cf6354767b4d46ec933725ef5ceafeecd5152c`. Work only there.

**Layer:** Herzchen model. New code goes in `src/herzchen/packs/authoring.py`.

**Files you own:**
- `src/herzchen/packs/authoring.py`
- `tests/test_evidence_lifecycle.py`
- `tests/test_evidence_projection.py`

**Other files:** you may also edit any other file your outcome directly requires (a caller, a fixture, a CLI entry, a guard on the path), except the files under "Do not touch". List each one in your report with the reason. Don't stop to ask for a file: stop only if the outcome itself is unclear, or a file you need is under "Do not touch".

**Do not touch:**
- the files of tasks running now: none;
- `production/` (the Astrid film's folder; it means nothing for code);
- any Store, `~/.otto` or `~/.codex`;
- Codex's projects, vision and Native5;
- anything outside this lab.

**Build on what exists:** `src/herzchen/packs/authoring.py:80` defines `ManagedSourceIdentity`; `:253-278` currently resolves Astrid's public APIs and converts discovered metadata into that identity; `:295` is `read_managed_pack`. Preserve existing injection behavior and add the native path for packs under Herzchen's own source tree. Read the reference algorithms in `${ORIGINAL_HOME}/Developer/astrid-video/astrid-local/Astrid/astrid/core/pack/discovery.py` and `loader.py` (read-only).

**Your check.** Make it green and keep everything else green:
- Regression tests must fail on `canon/main` first; show both runs.
- Run the test files you changed or added.
- Test that the Evidence pack loads with no Astrid importable; when Astrid is available, compare the full provenance record field for field (skip if unavailable); tampered manifest/tree must be refused. The stage-2 `--fake` journey is an owner/staging check and cannot run in the worker sandbox; the landing gate runs it outside.
- Run tests with no env prefix (the Bash allowlist refuses one; `pyproject.toml` sets pytest's `pythonpath`): `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider <file>`.
- Run heavy commands as `otto-heavy --weight N --purpose "<TASK>" -- <cmd>`.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_evidence_lifecycle.py tests/test_evidence_projection.py`

**Callers, including production:** if you change a signature, a constructor argument or a default, find every caller and update it. That includes `install/controller/`, where production startup lives: no unit test starts it, but the staging Otto does at landing (D17).

**Existing tests:** don't change what an existing test asserts to make your change pass. If an expectation really must change, keep the change in its own commit (on Codex, list each changed assertion as file:line instead) and give the reason in your report. It lands only after an Opus decision (D19).

**Regression at the level the friction appears:** no-Astrid native Evidence pack load; parity/tamper refusal; stage-2 fake evidence capture via landing gate.

**XHARD only:**
- invariant: A pack's provenance identity is the same whichever loader reads it, and the base layer never imports the product built on it.
- plausible mistake to avoid: A loader that skips the digests and inventory checks, so a changed pack still loads.

**Deletion budget:** replace the default Astrid import path for packs inside Herzchen's own source tree with the native implementation; retain injected Astrid APIs for external packs.

**Working rules:** never run `git stash`, and never check out another commit in the lab. Don't run `ottoctl`, and never pass it `--help`. **Never wait:** no Monitor, no sleep loops and no background job you then wait on; run tests in the foreground. If a question blocks you, decide it within the brief and say so in your report, or end your report with the question.
- **On Codex** (Luna or Sol, the program's host since 16 Oct): you can't commit, because Codex's sandbox keeps `.git` read-only. Leave your work in the lab and `run-task.sh` commits it when you exit; don't work around the sandbox. **A long test runs to its end:** give the shell command a long timeout (for example `timeout_ms: 1800000`), or keep reading its session until it exits; never stop a test run because a window passed (REDS and DISPATCH stopped at "30 seconds", 16 Oct). A test that fails with `sandbox_apply: Operation not permitted` needs a sandbox of its own, which can't nest inside yours: list it in your report, and the landing gate runs it outside. **Any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.**
- **On Claude:** commit work in progress to `lab/<TASK>` as you go, only files you own, never `.brief.md`. **Any sub-agent you start uses `model: "haiku"`**, never Opus or Sonnet.

**XHARD only: you lead, a cheaper model executes** (PLAN.md D10). Delegate almost all execution: exploring and reading code, writing tests, making edits, running checks. On Codex (you are Sol), use `spawn_agent` with `model: "gpt-6-luna"`. On Claude (you are Sonnet), use the `haiku-worker` sub-agent (Agent tool, `subagent_type: "haiku-worker"`, Haiku 5.5 high).
- Keep for yourself what needs judgment: the design and how the invariant holds, each sub-brief, reviewing each result (`git diff`, the test tail) against the invariant, and the final commit and report.
- Fix a line or two yourself if that's quicker; anything larger goes to a sub-agent.
- Each sub-brief is self-contained, because a sub-agent sees nothing else: the goal, the exact files and functions, what not to touch, the command to run, and what to report back.
- Run sub-agents in parallel only when their files don't overlap. If one fails twice on the same step, sharpen the brief or split the step.
- In your report, list each sub-agent: what it did, and whether you corrected it.

**When done:** commit to `lab/<TASK>` (on Codex, leave it for the launcher) and don't push. Report the commit, the check runs (red, then green), what you deleted, and anything you couldn't finish. Stop and ask (the `ask` route, or end your report with a question) if the brief contradicts the code.
