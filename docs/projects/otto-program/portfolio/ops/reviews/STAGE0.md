# STAGE0 review (opus): stage 0 "Boots"

## 1. Verdict

**PASS WITH FIXES.** Staging starts and stops cleanly through the product entry point, on canon's own code, and stays inside its own folder. Three things need fixing before the next landing or the stage 1 review:

- **The gate tests the wrong commit:** its staging step runs the pre-merge `canon/main`, not the commit being landed.
- **The perch never ran status or kill:** stage 0's own live run lists them. Under §16's rule that "a stage passes only on scenarios that ran", this run proves start and stop only.
- **Two assertions pass with nothing to check:** `timeline-events` and `pool-units-within-limit`.

## 2. Findings

**F1. The landing gate's staging step runs `canon/main` as it was before the merge, and no landing has run that step yet.**
- **Evidence:**
  - `land.sh:265-266` passes `OTTO_COMMIT="$SHA"` to `staging.sh restart` and `perch.sh all --fake`. Nothing reads `OTTO_COMMIT`: a grep of `ops/bootstrap/` and `tests/` finds it only in those two lines.
  - Both scripts read `OTTO_STAGING_REF` and default to `refs/heads/canon/main` (`staging.sh:16`, `perch.sh:20`).
  - The staging step (d) runs before the merge (f, `land.sh:279`), so at that point `canon/main` is still BASE.
  - Every `land.log` under `ops/runs/*/` says `staging: skipped (STAGE/PERCH not landed)`, up to TOOLING9 at 04:39:02Z.
- **Why it matters:** this is POOL's failure again. A commit that crashes at startup passes D19 item 3, lands, and then fails the next task's gate, which gets the blame.
- **Fix (Haiku):** `land.sh` passes `OTTO_STAGING_REF="$SHA"` to both calls and drops `OTTO_COMMIT`. Perch asserts `staging-sha-is-tested-commit`: the sha in `staging.json` equals the resolved `OTTO_STAGING_REF`.
  - **Check:** land a throwaway branch whose `service run` raises at import. The gate refuses it with `staging.sh restart failed`, and BASE's staging still passes.

**F2. Status, kill and restart-after-kill never run in the perch, and the perch reads raw status that would call a killed Otto "serving".**
- **Evidence:**
  - Stage 0 in `canary/project.json:6-17` holds only `canary-add-sub` and `canary-refused`. The perch runs only `restart` (`perch.sh:65`) and `down` (`perch.sh:169`).
  - `staging.sh` has no status verb (`staging.sh:214-219`).
  - The report doesn't list these as skipped, though §16 requires a skip to say so.
  - `sample` takes `state` straight from `home/run/service.json` (`perch_report.py:91,98-99`). After a SIGKILL that file still says `"state": "serving"`. Only `read_status` (`service.py:107-125`) turns it into `stale`, by checking the holder pid with `os.kill(pid, 0)` and the heartbeat age (at most 5 s).
  - The product's status logic is sound. It just isn't what the perch reads.
- **Why it matters:** "status tells the truth" and "a restart after a kill recovers" are stage 0's own criteria, and no perch data supports either.
- **Fix (Haiku), in two parts:**
  - Add `staging.sh status`, which runs `ottoctl service status` through the existing wrapper.
  - Add a stage 0 scenario `staging-lifecycle` with these assertions:
    - **`status-while-up`:** outcome `running`; `holder.pid` equals the pid in `staging.json`; that pid is in a census taken mid-run; generation equals `home/run/generation`; `store.authority` equals the one in `installation.json`.
    - **`status-after-kill`:** after `kill -KILL -<pgid>`, outcome is `stale` and `holder_alive` is false.
    - **`restart-after-kill`:** `up` succeeds; status is `running` with generation +1; `sqlite3 -readonly … 'PRAGMA integrity_check'` prints `ok`; row counts are unchanged.
    - **`status-after-stop`:** after `down`, outcome is `closed` and no process holds the Store (`lsof` on `staging.store` is empty).
  - The sampler records the interpreted outcome from `staging.sh status`, not the raw `state`.

**F3. A refused start isn't recorded, and nothing tests one.**
- **Evidence:**
  - The product does name its reason: a held writer lock prints `owner_service_running` and returns exit 3 (`cli.py:986-990`); `HostConfigError` also returns 3 (`cli.py:991-993`); anything else returns 1 (`cli.py:994-997`). No record file is written.
  - `staging.sh up` throws that away. `wait_ready` checks only `kill -0` (`staging.sh:126`), the entry's exit status is never collected, and the message is just `did not report ready; see $LOG` (`staging.sh:171`).
  - The perch's seeded `staging` fault is a missing ref (`perch.sh:63`), so it fails before Otto runs. `test_staging_startup.py` has no test of a product refusal.
  - The exit-78 refusal record belongs to the supervisor path, which COMPOSE places.
- **Why it matters:** "or says exactly why not" holds for the CLI, but not for staging or the gate, where a refused start reads as a generic failure.
- **Fix (Haiku):** `up` reaps the entry (`wait "$pid"`) when it dies before ready and writes `run/staging.refused.json` with `exit_code`, the entry's last JSON line and the time. It prints the code and the `error.code`.
  - **Test `refused_start_names_its_reason`:** `up`, delete the pidfile, `up` again. The second `up` fails, and the refusal record has `exit_code: 3` and `error.code: owner_service_running`.

**F4. `timeline-events` passes vacuously on the Store side, and `pool-units-within-limit` measures perch, not Otto.**
- **Evidence:**
  - The required events come from perch's own `events.tsv` and the worker jsonl files (`perch_report.py:213-219`).
  - The Store check loops over `timeline["tasks"]` (`:221-223`), which is `[]` here (`timeline.json`: `store_events 0, tasks []`). The PASS says "no Store gaps" over zero tasks.
  - The pool peak comes from perch's own `+1/-1` marks and `ps` counts of `fake_worker.py` (`:90`, `:242-252`). Perch starts the workers itself and waits for each one in turn (`perch.sh:91-94`), so without a seeded fault the peak can't exceed 1.
- **Why it matters:** both PASS lines read as Otto checks, but at stage 0 they only check the harness.
- **Fix (Haiku):**
  - In `project.json`, each stage states its expected Store contents: stage 0 `{"store_events": 0, "store_tasks": 0}`.
  - A new assertion `store-matches-stage` fails if the Store differs either way. At stage 2 and later, a stage that expects tasks fails when the Store has none.
  - Rename the pool assertion `harness-pool-within-limit` until stage 2, when it must read Otto's own pool (the `limits` units) instead.

**F5. "Nothing left over" checks processes and canary labs, but not staging's own files.**
- **Evidence (the live staging root, read-only):**
  - Left after `down`: `home/run/service-stop` (53 B, `{"requested_at": "2026-10-16T04:40:17.932479+00:00"}`), `home/run/service.json` (`state: closed`), `home/run/generation`, `store/staging.store.fnd-owner.lock` (0 B), and an empty `perch-canary/`. No sockets.
  - The stop marker is never unlinked on close (`service.py:199-210`). It's cleared at the next start, once the writer lock is held (`service.py:177-178`).
  - `snapshot` looks only at the canary's canon and labs (`perch_report.py:105-118`).
  - The no-leak census never contained the staging Otto: the census before (`perch.sh:138`) is taken before the restart and the census after (`perch.sh:172`) after the down. Both list only pids 5553 and 11834, gate heavy jobs unrelated to staging. So there is no live evidence that the stage-root filter matches the real staging process. The seeded `leak` test covers only `fake_worker`.
- **Why it matters:** the first project socket (`home/run/c-<hash>.sock`, `serve.py:45-49`) or a held lock left after a stop would go unseen.
- **Fix (Haiku): a perch assertion `staging-at-rest-clean`.** After `down`:
  - `home/run` holds only `service.json` (state `closed`), `generation` and `service-stop`;
  - there is no `*.sock` under the stage root outside `tree/`;
  - `lsof` on the Store and its lock file is empty;
  - `perch-canary/` is empty.
  - Also, a census taken mid-run must contain the pid from `staging.json`.

**F6. Gate perch reports are deleted with the lab.**
- **Evidence:**
  - The gate runs the lab's own `perch.sh` (`land.sh:262-266`), and `PERCH_OUT` defaults to `$HERE/../perch`, which is `$LAB/ops/perch` (`perch.sh:19`, `common.sh:8`).
  - `ops/perch/` is gitignored (`.gitignore:7`).
  - `otto-lab.sh remove` runs `git worktree remove --force "$LAB"` (`otto-lab.sh:35`).
  - Only perch's stdout survives, in `$G/staging.log`.
- **Why it matters:** D20 wants "one report per staging run". Every landing's report would be lost.
- **Fix (Haiku):** `land.sh` passes `PERCH_OUT="$OTTO_REPO/ops/perch"`, or the gate run folder.
  - **Check:** after a landing, `ops/perch/<stage>/<stamp>/report.md` exists in the main checkout.

**F7. The Store's size at rest isn't recorded as such, and the baseline will drift.**
- **Measured (read-only):** `staging.store` is 139,264 B, which is 34 pages × 4,096 with `freelist_count` 0. It has 11 rows in `store_metadata`, 16 in `identities`, 16 in `record_references`, and 0 in `events`, `event_sequences`, `command_receipts` and `project_history`. There is no WAL file. The lock file is 0 B.
- **Why it drifts:** the report shows growth of `0 -> 139264` only because this was the first staging run (generation 1). `restart` never wipes, so later runs start from whatever earlier canaries left.
- **Fix (Haiku):** the perch records a `store-at-rest` row after `down`: bytes, page count, freelist and row counts per table. At stage 0 it asserts 0 events and at most 256 KiB, and later stages report their growth against this row. Stage 0 also runs on a wiped Store (`staging.sh wipe` before `up`), so "start an empty instance" holds every time.

**F8. Staging is down after every perch run, but D17 says it "runs canon/main all the time".**
- **Evidence:** `perch.sh:169` stops it, and the report says so in its header. No staging process is running now, and `run/staging.json` is absent.
- **Fix:** either the perch brings staging back up after the census, or D17 is reworded to "restarted and checked at every landing". This is the orchestrator's call; the code change is a Haiku task.

**F9. "closed" is published while the Store is still held (low).**
- **Evidence:** `_publish(state="closed")` is at `service.py:210`, inside the `with HostSession(...)` block at `:174`, so the writer lock is released after status already says `closed`.
- **Why it's low:** `staging.sh down` waits for the process group to go, so staging isn't affected. COMPOSE's `closed_only_after_store_release` already covers it for `ProjectOwnerService`, and the plain `OwnerService` that staging runs today should get the same fix.

## 3. Sound

- **Real start path:** `staging.sh` starts `ottoctl service run` from `tree/src` with `--home` always set (`staging.sh:28-32`). It ran canon's own code: `staging-restart.log` says `up: pid 12097, sha 2cdbb96…, ready`.
- **No onboarding wrapper:** the staging `installation.json` has no `owner_composition`, so `cmd_service_run` builds a plain `OwnerService` (`cli.py:747-750`). Nothing in `src/` writes that key.
- **`test_staging_startup.py`:** 8 passed in 24.6 s (one run, python3.11). It uses no mocks. `restart_after_kill_recovers` sends a real `killpg(SIGKILL)` (`:148`) and starts again through the real `staging.sh up`. Its checks are thin: `serving` and generation +1 only, with no Store integrity or `stale` status check (see F2).
- **Boundary:**
  - The Store path comes from the staging `installation.json` (`labs/_staging/store/staging.store`). `--home` bypasses `OTTO_HOME` and `~/.otto` (`config.py:33-37`). The socket path is derived from the home (`serve.py:45-49`).
  - The live lane `status.json` names no paths. Its authority is `otto-project-operating-setup-20261005-owner-v1`, against staging's `otto-staging-owner-v1`, and its holder is pid 51940, which is not a staging process.
  - The variables the wrapper doesn't unset (`OTTO_HEAVY_*`, `HOME`) are read only by `ottoctl heavy` or for `~` expansion.
- **`guard_root`** refuses live, synced, canon and home roots before writing anything (`staging.sh:36-51`, tested at `:226`).
- **Stop is clean:** `down` sends the stop marker, then TERM and KILL to the process group, and fails on survivors (`staging.sh:177-198`). `staging-down.log` says `down: stopped`, not forced.
- **Seeded faults:** `test_perch.py:236` runs the real `perch.sh` once per seeded fault and expects red.
- **Kill detection in the product:** `read_status` (`service.py:98-128`) correctly reports a killed holder as `stale`, by the dead pid or by a heartbeat older than 5 s.

## 4. Not checked

- **Environment reads in `herzchen`, `otto.portfolio` and `otto.attention`**, which the service imports: not traced, so a live-pointing variable there isn't ruled out.
- **What the Store lock is** (`staging.store.fnd-owner.lock`): it lives in Herzchen and I didn't read it. A lock file left after a kill doesn't block a restart, because the kill test passes.
- **The perch itself:** not re-run. That would restart staging, which the brief forbids. `test_perch.py` wasn't run either.
- **A live kill or status run on staging:** forbidden for the same reason, so F2 rests on reading the code.

## 5. Delete list

- **`OTTO_COMMIT`** at `land.sh:265-266`: nothing reads it (replaced in F1).
- **`land.sh:265`'s `staging.sh restart`:** perch restarts staging itself (`perch.sh:65`), so the gate restarts it twice. Keep only the perch call.
- **`"ottoctl"` and `"otto.hostctl"` in `CENSUS_MARKERS`** (`perch_report.py:27`): they pull unrelated heavy-gate jobs into the census (pids 5553 and 11834). The leak check already matches on the stage root, so the census could too.

## 6. Helpers

I ran 3 Haiku helpers, all read-only:

1. Listed every test in `test_staging_startup.py` and confirmed none uses mocks, ran the file once (8 passed), and mapped `cmd_service_run`, the refusal exit codes and the files the service creates.
2. Mapped each perch assertion to its code, the census and sample sources, the raw data, the canary's stage tags and the perch tests.
3. Read the live lane's `status.json` paths, listed the staging root, measured the Store with read-only `sqlite3`, and traced how `--home`, the Store path, the socket path and environment variables resolve.

I checked their key citations myself: `service.py:98-212`, the test file, `perch_report.py:185-236`, both census files, the staging `home/run` and `store` listings, and `land.sh:259-269`.