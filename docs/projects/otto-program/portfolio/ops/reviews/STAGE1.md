1. **Verdict: PASS WITH FIXES.** Nothing about stage 1 is unsafe: no save can run anything, and a stale save is refused under a real lock. But it isn't a pass as run. The perch's stage 1 checks read the save's own JSON reply, never the Store, and the data shows two of the stage's claims don't hold: an old revision can't be read back, and the typed record doesn't carry what PLAN D2 asks for. F1–F3 should land and `perch.sh 1` be re-run before the stage 2 review.

2. **Findings**

**F1. A revision is a label, not a snapshot. The old revision can't be read, and asking for it quietly returns the current content.**
- **Evidence:**
  - The Store keeps one row per record and overwrites it in place: `UPDATE identities SET current_revision = ?, version = ?, payload_json = ?` (`src/herzchen/kernel/store.py:1850-1885`). No table holds past revisions (`schema.py:29-137`).
  - Lookups ignore the revision. `get_identity` selects by authority, kind and id only (`store.py:1435-1441`), and `WorkGraph._resolve(ResourceRef)` goes through it (`domains/work/module.py:823-825`). So asking for `task@rev-1` returns rev-2's content under the rev-1 name.
  - The events don't hold the content either. The staging Store's four events have no title or instructions anywhere in them (`instr(effects_json,'Plan A')` = 0 for all four).
  - The edit's history entry says nothing changed: `changed_fields: []` for a title change (event 4).
  - **The record links are out of date.** At project rev-3, the project's `tasks` list and `batch_history` still name the task at `rev-1`, while the task itself is at `rev-2`. The save's reply also says `rev-1` (`save-edit.json`).
    - Cause: the refs are taken before the task is written (`batches.py:579-587`, `:642`) and never updated after it is (`:688-698`). The reply reuses the same refs (`:225`, `herzchen_binding.py:2359`).
- **Why it matters:**
  - §16 stage 1 says "edits make revisions", and the PERCH1 row says "the old one still readable".
  - Without the base's content, the stale-save diff can only compare the file with the current state (F4).
  - ADMIT (stage 2) pins exact revisions whose content isn't kept.
  - Stage 6's "r4's save previews exactly its changes" needs the base too.
- **Fix:**
  - **(a) Haiku:** `batches.py` writes the project's task refs, `batch_history` mappings and the reply's `task_refs` after the task writes, so they name the new revisions.
    - Check: after one edit, `project@rev-3.tasks[0].revision` and the reply's `task_refs.A.revision` are both `rev-2`.
  - **(b) Sonnet (xhard; lands in `herzchen/kernel` and `herzchen/domains/work`):** keep every work-record revision's content, immutable and keyed by ref and revision. `get(ref@rev)` returns that revision's content and never the current one; a revision that wasn't kept is refused. The sheet's history entry lists title, instructions, acceptance and `otto.plan` changes.
    - Check: after an edit, `get(task@rev-1).title == "Plan A"` and `get(task@rev-2).title == "Plan A two"`.
  - **Perch assertion `old-revision-readable`:** after the edit, reading the create's task ref returns the create's content field by field. It is red until (b) lands, and since it's in stage 1's scope, the stage fails until then.

**F2. Most stage 1 PASSes don't check what their names say.**
- **`tasks-are-typed-records`** reads only `save-create.json` `task_refs` and checks that `authority`, `kind` and `id` aren't blank (`ops/bootstrap/perch_report.py:538-552`).
  - It never reads the Store or the task's fields.
  - The test fixture passes with `"kind": "wrk.assignment"` (`tests/test_perch_stage1.py`, commit `c09ad3e`). So the fixed assertion would pass any ref of any kind. Changing `type` to `kind` was right, but what remains is an empty check.
- **`edit-makes-revision`** checks only that the edit's revision string differs from the create's (`:566-575`). It never reads the old revision.
- **`nothing-runs`** checks two things:
  - the `dispatch`/`launch` flags, which the handler hard-codes to `False` (`herzchen_binding.py:2352`, `:2360`);
  - the harness's own `events.tsv`/`pool.tsv`, which are empty at stage 1 because the stage has no tasks (`canary/project.json:13`).
  - It never reads the Store or the process census.
- **The read-back has never run.** In all four stage 1 runs (`ops/perch/1/*/raw/read-back.json`) it is `{"outcome": "unavailable"}`.
  - Cause: `perch.sh:172` puts `--portfolio P` before `read`, and only `save` strips that flag (`src/otto/hostctl/portfolio.py:80-90`). So `otto.portfolio.cli` takes `claude-code-portfolio` as the command (`raw/save-errors.txt`).
  - No assertion reads `read-back.json`, so "show" from §16's stage 1 row never ran.
- **`store-matches-stage`'s "1 tasks" is the root assignment** that `admit-host` created (`timeline.json`: `assignment-dbe32c…`, `work.assignment.created`), not the saved task. The saved `work.task` isn't counted.
- **One task is too few.** The canary is one task with no criteria, route, size, repo or deps (`canary/project.json:17-29`). It can't show deps, typed metadata or a multi-task edit.
- **Fix (Haiku, PERCH1FIX; lands in `ops/bootstrap/` and `tests/test_perch_stage1.py`):**
  - **The canary:** at least 3 tasks, with B depending on A; `otto.plan` route, size and repo/branch on each; a `criteria` list.
  - **The edit:** changes A's title, B's `otto.plan.size`, and adds a dep C→B.
  - **The read-back:** goes through a working read (after F7), or reads the Store snapshot directly.
  - **New or changed assertions:**
    - `read-back-matches-save`: every file task is exactly one `work.task` record with the file's alias, title, instructions, acceptance, deps (as refs to the right tasks) and `otto.plan`, value for value. An unavailable read-back fails it.
    - `tasks-are-typed-records`: read from the Store snapshot. The kind is `work.task`, and no other row and no owner-lane file holds the title.
    - `nothing-runs`: the Store holds no `wrk.assignment` beyond the root and no dispatch, assignment or lab event after the first save. A census taken between the saves shows no worker process.
    - `store-matches-stage`: counts `work.project` and `work.task` records as well as assignments.
  - Each seeded fault should corrupt the Store snapshot, not only the reply JSON.

**F3. The "typed record" doesn't match PLAN D2 on criteria or lines.**
- **Criteria:** a save's `criteria` go into one JSON list inside the project's `work.template` namespace (`src/herzchen/domains/work/sheet.py:607`).
  - That list isn't linked to any task, isn't an assessment criterion, and is left out of the stale diff.
  - D2 says "Checks are criteria in the assessment's scope … one representation". Task `acceptance` is free text (`batches.py:841-843`).
- **Lines:** `otto.plan` models `lines` as a positive integer, plus a single `repo` and `branch` (`src/otto/portfolio/plan_metadata.py:17`, `:38-43`). §1 says "one branch per repo it touches", and the TYPE row says "lines (repo → branch)".
- **No removal:** namespaces only merge (`module.py:123-134`), so no save can remove an `otto.plan` key.
- **Fix:**
  - (a) Haiku: `lines` becomes `{repo: branch}`, validated, with a way to remove a key. Check: the existing TYPE round-trip tests, extended to a two-repo task.
  - (b) Sonnet, or fold into LAND, whose criteria checks need this: a save's criteria become assessment criteria in each task's scope, and show reads them back.
  - Either way, the orchestrator records which row owns (b).

**F4. The stale-save refusal is honest but only partly actionable.**
- **Sound:**
  - The check runs inside one `BEGIN IMMEDIATE` transaction (`batches.py:147`, `:174-178`; `store.py:669`), so two saves from the same base can't both land.
  - The refusal writes nothing (rows unchanged, no receipt), and it names `base_revision` and `current_project_ref`.
- **Gaps:**
  - (a) No `next_action`, which D13 asks of refusals a task touches.
  - (b) The diff skips `dependencies`, `metadata_namespace` and `criteria` (`src/otto/portfolio/save.py:19`, `:150-156`). A stale save that changes only deps or route/size gets `changed: []`.
  - (c) The diff compares the file with the current state, so an agent can't tell its own edits from the other writer's (because of F1).
  - (d) Two processes contending for the Store get `WriterBusyError`, which `_save_project` reports as `save_refused` (`herzchen_binding.py:2353-2356`), not as a retryable state.
- **Fix (Haiku):**
  - The refusal carries `next_action`: re-read with `show`, re-apply, and save with `project_ref.revision` set to the current one.
  - The diff includes deps, `otto.plan` and criteria, and adds `base → current` once F1(b) lands.
  - A busy Store answers `busy` with a retry hint.
  - Check: unit tests for a stale save that changes only deps or size, and the perch's `stale-save-refused` asserts `base_revision` equals the create's revision and the diff names the changed field.
- **A3's document check-in race** is separate: `document_editor_host.py:267-268` calls `finish` without `expected_base_revision`, so `sessions.py:1295-1298` compares the session's base with itself. That is A3FIX's row; it's correctly scoped.

**F5. A create isn't atomic, and re-saving an edited file without `project_ref` makes a second project.**
- **Evidence:**
  - `_save_project` runs `create_pending` in its own committed transaction (`batches.py:393`), then `apply` in another (`herzchen_binding.py:2340-2347`). Anything `apply` refuses after the create leaves an empty project.
    - One example: an unknown task key moves into `fields` (`sheet.py:600-604`), which may hit the protected-field check (`:662-663`). This is from reading the code; I didn't run it.
    - The only test covers the check before the create (`tests/test_otto_save.py:113`).
  - The project id comes from the request key (`batches.py:366`), and that key is a hash of the file's content (`save.py:113-119`). So an edited file without `project_ref` is a new project.
  - The create writes 2 events and 2 receipts (F8).
- **Fix (Haiku):**
  - Validate the whole sheet before the create, or run the create and the apply in one transaction. Check: a file a sheet refuses leaves every Store table's row count unchanged.
  - Whether to refuse a ref-less save whose title matches a pending project in the portfolio (naming that project) is the orchestrator's call.

**F6. The owner lane admits every portfolio subcommand at owner authority. PERCH1 didn't add this; the brief's premise is off.**
- **Evidence:**
  - PERCH1's `service.py` change is an error message only (`:372-373`). The `work.project.save` string never appears in `service.py`.
  - The entry that carries a save is `("portfolio", None)` (`src/otto/hostctl/service.py:362`), added in `f7bdf57d` on 11 Oct. It runs `cmd_portfolio` with `owner_authorized=True` (`:375`).
  - `cmd_portfolio` hands any argv to `otto.portfolio.cli.main` (`src/otto/hostctl/cli.py:301-317`): `admit`, `complete-task`, `respond-help`, `direction` and so on.
  - Only the client narrows it to `save` (`portfolio.py:80-90`); the owner checks nothing again.
  - **Who can call it:** any process of the same account that can write `home/owner-lane`. The lane is a private directory (`lanes.py:40-48`, `:71-84`), not a socket, and it has no peer check. `lanes.py:10-14` says it is "not a defence against a hostile process of the same account".
  - The four `("project", …)` entries have no owner-lane caller in tests or `ops/bootstrap`.
  - It is also the file lane that D5 retires.
- **Why it matters:** once ADMIT is live, an agent that can write the lane folder can admit its own revision.
- **Fix (Haiku):** the owner checks `portfolio_args[0]` against an explicit set (today `save`, plus whatever reads F7 adds). The four `project` entries are each either named with a caller or deleted.
  - Check: a test that `admit` and `complete-task` sent through the owner lane are refused with `PermissionError`.

**F7. Neither `show` nor `read` works from a cold client against a running owner.**
- **Evidence:**
  - `read` fails on `--portfolio` (F2).
  - `show` goes through `HostSession`, which opens the Store file directly unless it runs inside the owner's process (`src/otto/hostctl/owner.py:157-171`). So a second process would open the owner's Store. I didn't run it live.
- **Fix (Haiku):** `show`/`read` go to the owner lane the same way `save` does.
  - Check: `ottoctl portfolio --portfolio P show project --project-ref …` from `env -i` returns the saved tasks while staging is up. This is also the perch's read-back.

**F8. The Store-growth figure is wrong, and some growth isn't needed.**
- **The report's "per save 163840 bytes" is meaningless.** It is the whole run's byte growth from the first sample, taken before the Store existed, divided by the number of task-timeline events (`perch_report.py:858-864`).
- **The real numbers** (`raw/store-*.json`):

  | Save | Bytes | Rows added |
  |---|---|---|
  | create | +20480 (5 pages) | +10: receipts 2, events 2, identities 2, refs 4 |
  | edit | +4096 | +4: receipt 1, event 1, refs 2 |
  | stale | +0 | 0 |

- **Growth that isn't needed:**
  - The create is two transactions with two events.
  - `batch_history` gains one entry per save inside the project record, which is rewritten whole on every save.
  - Each sheet event is about 4 KB for one task, mostly the history summary's repeated `unknown` field lists (event 4: 4190 bytes, a 22-name list four times).
  - Meanwhile the content a revision needs isn't kept (F1).
- **`project_history` stays empty** (0 rows, checkpoint 0). The product entry point never sets up the history projection; the only caller is `install/controller/operating_service.py:55`.
- **Fix:**
  - (a) Haiku perch fix: `store-growth-per-save` reports bytes and rows per save from the snapshots, and bounds the bytes for a one-task edit (e.g. ≤ 8 KiB).
  - (b) Haiku: `ottoctl service run` sets up the history projection. Perch assertion `project-history-follows-events`: at rest, `history_checkpoint` equals the last append position and `project_history` has rows.
  - (c) Normal task: limit `batch_history`, or move it to events.

**F9. Editing a task's title leaves `name` at the old value.** The task reads `name: "Plan A"`, `title: "Plan A two"`.
- **Cause:** `batches.py:876-879` derives `name` from `title` once, at creation, and `:841-843` updates each field on its own.
- **Effect:** `WorkRecord.name` stays out of date (`module.py:814`). `show` happens to use `title` (`inbox.py:601`).
- **Fix (Haiku):** a derived `name` follows `title` (or isn't stored). Check: a test where an edit changes only the title, and `name == title` afterwards.

**F10. PERCH1's acceptance "`perch.sh 1` passes on staging without `--fake`" isn't met. Otherwise the flag is inert for stage 1, as it should be.**
- **Evidence:**
  - `perch.sh:387` refuses every stage but 0 without the flag.
  - Beyond that, `FAKE` is never read (lines 370, 373, 387), and stage 1 has `"tasks": []`, so neither `run_task` nor `fake_worker.py` runs.
  - But `init` gets a literal `--fake` (`perch.sh:358`), so every report, stage 0's included, says "(fake worker)".
- **Fix (Haiku):** refuse only stages whose canary has tasks, and pass the real flag to `init`.
  - Check: `perch.sh 1` runs without `--fake`, and `config.fake` matches the flag.

**F11. Reds on canon: none touches stage 1's code, but the REDS row is incomplete.** Each file was run alone, once, at `c126587`:

| File | Result | First passed as pre-existing |
|---|---|---|
| `test_manager_reentrant_ipc.py` | `test_terminal_status…` fails, `KeyError 'summary'` | POOL, 16 Oct 01:39Z |
| `test_completion_project_refresh.py` | 6 fail | A1, 15 Oct 19:15Z |
| `test_events_final_corrections.py` | 1 fails | TYPE, 16 Oct 09:34Z |
| `test_project_folder_scale.py` | 2 fail | A1, 15 Oct 19:19Z |
| `test_d03_status_reads.py` | 1 fails | A2's gate, the first to run that file, so the origin is unknown |
| `test_hostctl_serve.py` | `…xhard…` fails: "xhard-route worker did not run" | HOSTKIT, 15 Oct 18:23Z |
| `test_missing_manager_capture.py` | passed 1/1 (flaky, so not proven green) | — |

- **One cause for seven of them:** the 6 `completion_project_refresh` failures and the `events_final_corrections` one all come from product code importing a module that exists only under `install/controller` (`src/otto/portfolio/manager_journey_command.py:63` → `install/controller/completion_intent_selection.py`).
- **Not on the REDS row:** the `test_hostctl_serve.py` failure, red since before stage 0.
- **Stage 1's own tests are green:** `test_otto_save` 13, `test_task_metadata` 13, `test_otto_show_status` 6, `test_pending_inert_tasks` 7, `test_admit` 12, `test_perch_stage1` 16.
- **Fix:** add `test_hostctl_serve::…xhard…` to REDS, and note that 7 of its reds share one cause.

3. **Sound**
- **Nothing runs:**
  - No code path from `_save_project` or `apply_project_sheet` dispatches, activates, opens a lab or starts a process. `activate_project`'s only caller is `reviewed_activation.py:444`.
  - The Store after the saves holds only the root assignment.
  - The census before and after was empty.
- **The stale-base check against a concurrent writer is sound:** it's inside `BEGIN IMMEDIATE`, and the stale save wrote nothing (rows unchanged, no receipt).
- **Replaying the same file** gives the same key and creates no duplicate (`test_otto_save.py:119`).
- **One copy of task content in the Store:** only `identities` holds it; events and `record_references` hold refs only.
- **The only other copy** is the owner-lane response file holding the stale diff (`home/owner-lane/response-9e8e….json`), a short-lived transport file.
- **The `otto.plan` check** refuses an unregistered namespace (`module.py:137-157`) and is registered in the owner's domains (`hostctl/owner.py:55-57`).
- **No landing since stage 0 changed an existing test without D19.** Only TOOLING10, PERCH0FIX and UNTIME modified existing test files, and each has a D19 LAND in its `land.log`.
- **PERCH0FIX's D19 fix** (`52ad6e7`, the rebased `d4f4890`) does F1 (a) and (b) and `EXPECTED_RED["staging"] = {"staging-ready"}` as asked. One small gap: the F2 wording at `tests/test_perch.py:387` still says "turns exactly its assertion kind red".
- **UNTIME's D19 fix** (`2d91fba`) is what D19-UNTIME F1 and F2 asked for: it waits for the pending-file removal, and the child writes its files atomically at both places. No assertion changed.

4. **Not checked**
- **A live `show` or `read` against a running staging Otto:** starting staging is off-limits, so F7 rests on reading the code.
- **The create-path leftover (F5):** found by reading the code; not executed.
- **Whether ADMIT's authoring stamp is applied on the sheet (save) path:** the saved task carries no admission namespace. That's stage 2's to check.
- **The repeat-run rates of the reds:** each file ran once.
- **Which landing turned `test_d03_status_reads` red:** bisecting needs a checkout, which is forbidden here.
- **The gate's runs under `ops/perch/0/`:** I read only their assertion results, all passing.

5. **Delete list**
- The four `("project", "depend" | "dependencies" | "detach" | "activate")` owner-lane entries (`service.py:362-363`), unless a caller is named (F6).
- `batch_history` inside the project record, once the per-save events carry the mapping (F8).
- The "per save (Store event)" line in the report, replaced by F8(a).

6. **Helpers: 6 (Haiku)**
- Traced the save path, the stale check and the create's atomicity, and ran `test_otto_save`.
- Audited the owner-lane allowlist, who can call it, and why `read` fails to parse.
- Queried the staging Store read-only: tables, events, records, revisions, sizes, and copies outside the Store.
- Audited the stage 1 perch assertions, the seeded faults, `c09ad3e`, `--fake`, and ran `test_perch_stage1`.
- Ran the REDS files and the stage 1 test files on canon, one at a time, and traced each red's first pre-existing landing.
- Traced name/title, the out-of-date task refs, past-revision reads, `show`, the A3 race and `project_history`.