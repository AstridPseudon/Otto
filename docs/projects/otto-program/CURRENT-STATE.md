# Otto program handover status (read-only, 2026-10-28)

## Authoritative phase

The program is **paused by explicit user instruction**. The newest Orchestrator section in `${ORIGINAL_HOME}/Developer/otto-program/ops/requests.md` (2026-10-19T00:20:48Z) says canon/main and GitHub main are `a70b3f2`, integration rounds 1–4 landed, manager loop/D19 watcher/cron stopped, integration worktrees removed. The Oct 18 user pause supersedes the prior STAGE2CLIENT check/landing plan. Do not restart or run effects until a new instruction resumes work.

## Pending work if resumed

Follow the exact resume queue in `ops/requests.md` (2026-10-19T00:20:48Z):

1. Reconcile **STAGE2CLIENT outside check-run 1129**. Its last manager observation was in progress without `LAND RESULT`; the resume queue later records it failed. Resume its worker with `ops/runs/STAGE2CLIENT/check.out`, then run stage 2 (`perch.sh 2 --fake`) and obtain the stage-2 Opus review (queue says call 9 of 15). Stage 2 hangs on current canon until STAGE2CLIENT lands.
2. Resume integration culprits with their evidence: TESTPATCH, LANDPROOF, XFERMAP (`ops/integ/culprit-<TASK>.md`); LABPIN and OBSOWNER have earlier culprit files. Re-bisect the failures attributed together to ROLEIDS, OBSOWNER, BOOTCFG and CLIARGS.
3. After STAGE2CLIENT lands, rebase/resolve REALSTAGE3, LABPIN and DISTURB; their histories/checks involve stage 2.
4. Gate round: BOOTLAND, PROOFDOC, ROOTFILE and LANDBATCH.

The Oct 18 manager note that STAGE2CLIENT check 1129 was unresolved is stale relative to the Oct 19 resume queue's failure statement. Its earlier “land after pass” plan is superseded.

## Records and freshness

- `ops/manager-state.md` is the freshest manager summary: no live worker or landing; stay stopped; reconcile 1129 only after an authorized resume.
- `ops/manager-last.md` says the stop was followed and files updated; it is not a separate execution-status source.
- `ops/manager-handoff.md` is dated Oct 16 and describes A3FIX, REVS, CODEXHOST, individual `land.sh` operations and older limits. It is stale; `ops/integ.py` and the Oct 19 pause/resume queue supersede it.
- `ops/STATUS.log` confirms the stop and records check 1129 in progress at the last manager observation. `ops/requests.md` carries the newer resume-queue failure note.
- The local `otto-program` repo's last commits are pause cleanup (`3ae2036`) and resume-queue/integration work (`5baac2a`). Its current dirty/untracked files are `.DS_Store` and `.nothing`; leave them out of transfer.
- Latest D19 decisions include LAND for TESTPATCH and LANDPROOF. Preserve these decisions; the later integration culprit findings still require the queue actions.

## Budgets

`projects/program/run.json` declares Opus max 15 calls (9 stage reviews + 1 final + 5 reserve) and Astra max 5 calls (no reserve). Preserve caps and usage history; do not reset or amend them. The last explicit STATUS counter found is older (6/15 Opus, 2/5 Astra on Oct 17), so it is not a current total. Reconcile totals from preserved review launch/usage records after resume. `ops/manager-usage-total.json` is manager token usage, not the review budget ledger.

## Receiving start and relevant paths

At authorized resumption, read the newest Orchestrator sections in `ops/requests.md`, then reconcile manager state, `ops/STATUS.log`, worker/check outputs, and actual canon before acting. Owner source repo: `${ORIGINAL_HOME}/Developer/otto-claude-host/otto` (`canon/main` and `github/main` were `a70b3f2` at pause). Control package: `${ORIGINAL_HOME}/Developer/otto-program`; evidence in `ops/runs/`, integration evidence in `ops/integ/`, decisions in `ops/reviews/`. Program scope is in `projects/program/tasklist.md` and `run.json`, with shared `PLAN.md` and `RUNBOOK.md`. Related packages live under `otto-program/projects/`; corresponding external project working paths are under `${ORIGINAL_HOME}/Developer/otto-projects/`.

