# Review brief: STAGE2B (opus), stage 2 "Dispatches", re-review after the first review's FAIL

You are an independent reviewer for the Otto program (`~/Developer/otto-program`). **Opus:** you check whether it works, judged on the live data and the code. A claim without evidence is not a finding, and a check you didn't run is not a pass.

**Stay read-only.** Never edit, create or delete files, commit, push, stash or check out. Never run `ottoctl` or pass `--help` to any Otto command. Never open the live Store or list `~/Documents/Codex` or `~/.codex`. Don't start a staging Otto.

## Hand the legwork to helpers
Use the Agent tool with `subagent_type: "haiku-worker"`, as many in parallel as the work splits into (one per prior finding is a good split). Each brief is self-contained. Check any claim a helper makes in the source before you rely on it.

## What happened since the first review
The first review (`ops/reviews/STAGE2.md`, 17 Oct 16:39Z) FAILED stage 2 with nine findings. Rows fixed them and more stage runs found further product defects, all landed on canon since: LABCAPTURE, ORPHANWORKER, COMPLETECITE, KILLFENCE, LIMITFD, MANUALDISPATCH, PACKPARITY, FAILCLOSED, PROJECTPIN, READYPIN, OWNERCOMPLETION, CTLRACE, FACADEFD, SESSIONFD (if landed), PERCH2C, and others (`git -C ~/Developer/otto-claude-host/otto log --first-parent --format='%h %s' 5b4a770..canon/main`). The Codex manager ran stage 2 on canon alone: `ops/runs/STAGE2C1/land.out` (passed on 825843c), report `ops/perch-reports/2/20261017T232313Z/report.md` and its `raw/`. The testing design the program now follows is `PLAN.md` §17.

## Questions
1. **Each of the first review's nine findings:** closed, partly closed, or open, with the evidence (the landing, the code at `file:line` on canon, and the run's raw data).
2. **Do the stage-2 checks now fail when their claims are false?** Read `ops/bootstrap/perch_report.py`'s stage-2 checks and their doctored-input tests in `tests/test_perch.py`. Name any that still pass by construction.
3. **Harness honesty (§17.5):** does any stage-2 harness piece still patch a product method or impose a time limit? (Untimed polling on the owner's own state is allowed.)
4. **Is anything the stage claims not shown by this run's evidence?** Only admitted, ready tasks start, in dependency order; pool and manager reserve hold; an unadmitted revision is refused and a metadata-only write isn't; a killed worker frees its slot and its fence is settled by the manager; nothing leaks.
5. **Should stage 2 now gate every landing** (`ops/stages-gated`), and is its runtime acceptable for that (`ops/runs/*/land.out` staging timings)?

## Answer in this shape
1. **Verdict** in one line: PASS, PASS WITH FIXES, or FAIL.
2. **Prior findings 1-9:** one line each: closed/partly/open and the evidence.
3. **New findings,** most severe first, each with evidence and a fix (a row or a perch assertion that fits §17).
4. **Sound / Not checked / Helpers,** one line each.
