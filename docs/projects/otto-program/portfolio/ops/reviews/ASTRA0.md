**1. Verdict: FAIL — unsafe to start unattended as written; TOOLING3’s gate contract and several operating instructions need correction first.**

**2. Findings, most severe first**

Paths below are relative to `otto-program`; bootstrap script references are in `~/Developer/otto-claude-host/otto`.

1. **The documented owner preflight launches an owner.**  
   [RUNBOOK.md:91](${TRANSFER_ROOT}/portfolio/RUNBOOK.md:91) says run `launch_owner.py --preflight`, then launch. [launch_owner.py:6](${TRANSFER_ROOT}/portfolio/ops/launch_owner.py:6) immediately reads the launch intent; line 13 launches it. There is no argument parser, preflight branch, or existing-owner check. Following the recovery instruction can launch twice.  
   **Fix:** implement a genuinely read-only `--preflight`, reject unknown arguments, and make the launch path refuse an existing owner under a single-instance lock. Correct RUNBOOK §5 to give the two exact commands.

2. **TOOLING3 does not yet have an unambiguous transaction to implement.**  
   [RUNBOOK.md:68](${TRANSFER_ROOT}/portfolio/RUNBOOK.md:68) requires staging on the “merged commit”; the merge happens later, at line 72. `perch.sh` is specified to restart staging on `canon/main` ([tasklist.md:50](${TRANSFER_ROOT}/portfolio/projects/program/tasklist.md:50)), which would still be the old commit. Other landers are explicitly allowed. Existing [land.sh:67](${TRANSFER_ROOT}/source/otto/ops/bootstrap/land.sh:67) checks the base once, then merges without a shared lock.  
   **Fix:** expand RUNBOOK §1.2/§4: construct candidate merge **M**, run checks and staging against **M**, publish exactly **M** only if the expected base still matches, then push and clean up. Require cooperating landers to share serialization. Specify the candidate argument for staging/perch, importer-test discovery, D19 pause/resume behavior, command deadlines, and `land.log` contents including tested/published SHAs and individual results. Missing implementation is expected; these missing semantics are not.

3. **GREEN is explicitly still red, but landing it disables the baseline exception.**  
   [tasklist.md:48](${TRANSFER_ROOT}/portfolio/projects/program/tasklist.md:48) records 27/29 files green, with `test_d03_status_reads` and `test_hostctl_serve` unresolved. [RUNBOOK.md:27](${TRANSFER_ROOT}/portfolio/RUNBOOK.md:27) nevertheless says GREEN needs no fixes, while line 66 permits baseline comparison only *until GREEN lands*. The current [handoff:12](${TRANSFER_ROOT}/portfolio/ops/manager-handoff.md:12) acknowledges both remaining failures and promises continued comparison.  
   **Why it matters:** the next affected landing either stalls on known failures or silently invents an exemption.  
   **Fix:** finish GREEN before declaring the baseline empty, or explicitly split out the two residual failures and retain their exact per-commit baselines until those fixes land.

4. **The first six launches cannot be followed literally without resolving commands and precedence.**  
   A reasonable intended trace is **HOSTKIT resume, POOL resume, STAGE, A1, PERCH, CUSTODY**; a valid first-three-landing trace is **GREEN, HOSTKIT, POOL**, subject to checks and completion order. Independent tasks need no artificial landing order. The actual trip points are:

   - The manager runs in `otto-program` ([launch_manager.py:13](${TRANSFER_ROOT}/portfolio/ops/launch_manager.py:13)), but its commands use relative `ops/bootstrap/...` paths ([manager brief:46](${TRANSFER_ROOT}/portfolio/ops/manager-bootstrap-brief.md:46)). Those scripts exist in the **Otto checkout**, not this folder. Changing cwd to Otto also breaks relative `--message ops/fixes/...`.
   - The latest inbox section assigns the three initial landings to the **orchestrator** ([requests.md:110](${TRANSFER_ROOT}/portfolio/ops/requests.md:110)); the brief assigns them to the **manager** (line 15), and says inbox instructions take precedence (line 30).
   - Template-conforming briefs contain `**Your check.**` ([brief-template.md:24](${TRANSFER_ROOT}/portfolio/ops/brief-template.md:24)); [land.sh:42](${TRANSFER_ROOT}/source/otto/ops/bootstrap/land.sh:42) requires `Check command:` or `--check`.
   - The handoff already claims TOOLING3 landed ([handoff:5](${TRANSFER_ROOT}/portfolio/ops/manager-handoff.md:5)); the inspected `canon/main` remained `9739a294…`.
   - RUNBOOK permits three workers after measurement; the manager’s “Never” section prohibits exceeding two.

   **Fix:** use absolute bootstrap and message paths; add the parser-compatible check field to the template; issue one current resume instruction superseding the historical inbox; generate landed claims from git; keep the worker limit consistently two unless explicitly revised. The existing worker IDs, branches, lab briefs, interpreter and `otto-heavy` paths were verified—no replacement sessions are needed.

5. **The hourly checklist asks for telemetry that its named artifacts cannot supply.**  
   [checkin-checklist.md:17](${TRANSFER_ROOT}/portfolio/ops/checkin-checklist.md:17) asks for active workers’ turns, spend, repeated commands and delegation share. [run-task.sh:78](${TRANSFER_ROOT}/source/otto/ops/bootstrap/run-task.sh:78) writes a final JSON result, not a stream. The inspected initial HOSTKIT and POOL JSON files are zero bytes. POOLX’s `modelUsage` contains tokens/cost; `subagent_stats` contains agent lifecycle counts. Neither contains the **42 lead / 180 helper tool calls** reported in [comparison.md:13](${TRANSFER_ROOT}/portfolio/ops/experiments/POOLX/comparison.md:13).

   Playing the four checklist roles:

   | Helper | What is available | What is missing or misleading |
   |---|---|---|
   | Manager | Session record and structured result events in `manager.log` | Current spend is not established by a completed-result total alone |
   | Workers | PID, model, start, deadline, budget, lab; completed results | Live turns/spend, repeated-command history, tool-call share |
   | Landings | First-parent git history | `land.log` is a TOOLING3 deliverable; its evidence format remains unspecified |
   | Health | Named status file, disk command, requests and premium-call lines | Owner status requires freshness as well as PID checks; pending landings have no explicit record |

   **Fix:** preserve worker event streams and per-attempt terminal results, or narrow the checklist to observable facts. Delete the tool-call percentage requirement unless its telemetry is captured. Specify owner status fields (`state`, `heartbeat_at`, `holder.pid`) and a freshness threshold.

6. **The bootstrap can lose supervision while work survives, and landing commands have no bound.**  
   [run-task.sh:85](${TRANSFER_ROOT}/source/otto/ops/bootstrap/run-task.sh:85) watches only the Claude leader PID. If it exits with descendants still running, the watchdog ends. At timeout it signals a numeric process group without checking birth identity. [workers.py:47](${TRANSFER_ROOT}/source/otto/ops/bootstrap/workers.py:47) likewise treats PID existence as worker identity. Meanwhile [land.sh:61](${TRANSFER_ROOT}/source/otto/ops/bootstrap/land.sh:61) runs an unbounded check; manager disk polling cannot continue while that command hangs.  
   **Fix:** make the bootstrap supervisor retain responsibility for descendants after leader exit, record process birth identity, and bound landing/check/staging operations with cleanup and terminal status. Add this to TOOLING3’s acceptance scenario: leader exits or is killed while a child check remains. The later CUSTODY task does not protect the bootstrap automatically.

7. **Stages can open without the capability they promise, then skip it.**  
   Stage 3 promises `ask` ([PLAN.md:403](${TRANSFER_ROOT}/portfolio/PLAN.md:403)), but TOOLS supplies only `task`, `check`, `done`; ASK is separate ([tasklist.md:28](${TRANSFER_ROOT}/portfolio/projects/program/tasklist.md:28)). Stage 4’s conflict scenario does not specify whether detection suffices or recovery is required; REWORK is not a prerequisite. PERCH allows unavailable scenarios to be skipped ([PLAN.md:395](${TRANSFER_ROOT}/portfolio/PLAN.md:395)). Stage 6 requires two real program tasks, but neither reserves them nor transfers their ownership from the bootstrap manager.  
   **Fix:** keep question/answer certification in stage 5, explicitly define stage 4 as conflict detection or add REWORK, require preceding stages to pass, and prohibit an in-scope skip from producing a stage pass. Reserve two named stage-6 tasks and transfer them to staging before the bootstrap launches them.

8. **CUTOVER freezes the directory that subsequent reviews still write into.**  
   [tasklist.md:59](${TRANSFER_ROOT}/portfolio/projects/program/tasklist.md:59) freezes this folder as a read-only archive. Stage 7, stage 8, FINAL and continued check-ins still write here: [launch_review.sh:19](${TRANSFER_ROOT}/portfolio/ops/launch_review.sh:19), line 80, and [checkin-checklist.md:49](${TRANSFER_ROOT}/portfolio/ops/checkin-checklist.md:49).  
   **Fix:** before CUTOVER, separate the immutable plan archive from the writable operations directory and update every launcher/checklist reference. Alternatively, explicitly exclude `ops/` from the archive freeze until FINAL.

9. **Manager recovery preserves the context it is supposed to replace.**  
   [manager brief:70](${TRANSFER_ROOT}/portfolio/ops/manager-bootstrap-brief.md:70) ends an overlong context expecting a fresh manager. [checkin-checklist.md:41](${TRANSFER_ROOT}/portfolio/ops/checkin-checklist.md:41) instead always resumes the same session. [resume_manager.py:9](${TRANSFER_ROOT}/portfolio/ops/resume_manager.py:9) repeatedly prepends instructions to the stored goal; the current [session record:8](${TRANSFER_ROOT}/portfolio/ops/manager-session.json:8) still contains the superseded waves-0–2/three-review goal.  
   **Fix:** distinguish interruption recovery from context replacement. Both launchers should read one current goal definition; replacement must create a fresh session from the handoff. Refuse launch/resume while the recorded manager is still alive, and verify startup before reporting success.

10. **Budget accounting is not the promised enforcement.**  
    [run-task.sh:48](${TRANSFER_ROOT}/source/otto/ops/bootstrap/run-task.sh:48) recomputes allowance and deadline for every invocation; no cumulative task limit is checked. Review launchers count calls before reserving them ([launch_review.sh:22](${TRANSFER_ROOT}/portfolio/ops/launch_review.sh:22), line 40), allowing concurrent same-kind calls to race. They enforce total Opus calls, not the five-call discretionary reserve. Failed launches lack a terminal failure record; an empty Opus result can still produce `review-done` (lines 43–49, 80).  
    **Fix:** define attempt versus task allowances explicitly; enforce remaining task allowances where intended. Atomically reserve review ID and budget class, preserve the scheduled-stage allocation, and record success/failure/timeout with a nonempty validated answer.

11. **D14’s placement requirement is still optional or contradictory in several rows.**  
    [PLAN.md:92](${TRANSFER_ROOT}/portfolio/PLAN.md:92) requires destination packages, but [brief-template.md:3](${TRANSFER_ROOT}/portfolio/ops/brief-template.md:3) makes everything except outcome/files/check optional—including Layer. Specific exposure remains:

    - **ASK**, [tasklist.md:29](${TRANSFER_ROOT}/portfolio/projects/program/tasklist.md:29): points into Otto issue/help code without separating neutral waits/session resumption from product routing.
    - **CHANGE**, line 34: model stream, but no destination for revision/allowance enforcement.
    - **LANES**, line 70: fleet stream, while PLAN §11 lists it under Otto product; neutral transport versus product client wiring is unresolved.
    - **R1d/CACHE**, lines 23/72: fleet mechanisms without named destination packages.
    - **TYPE/EVIDENCE/ADMIT/PERCH**, lines 37/26/32/50: name Herzchen concepts but omit exact destination packages.

    **Fix:** make Layer mandatory; give those rows a destination and a sentence separating reusable mechanism from Otto policy. Also remove DISPATCH’s contradictory “Otto: pick … take a turn unit, then launch” wording at line 33—the same row assigns that mechanism to fleet.

12. **The next ten acceptance checks leave integration outcomes unpinned.**  
    Add these check lines to the corresponding tasklist rows and briefs. These are proposed assertions, **not tests I ran**.

    | Task; evidence | One additional check line |
    |---|---|
    | **STAGE**, tasklist:49 | Start through the production entry point at the requested SHA; assert distinct staging Store/socket paths, correct running SHA, and no live-instance writes. |
    | **A1**, tasklist:36 | Create inert tasks through the real command lane; exercise dispatch and direction-sync entrypoints; assert no launch and no direction-authored task mutation. |
    | **PERCH**, tasklist:50 | Seed a leaked process and missing timeline event in a real scenario; require the report to expose both and the stage verdict to fail, rather than testing only fabricated report rows. |
    | **CUSTODY**, tasklist:21 | Timeout a real adapter-launched fake CLI with child/grandchild processes; assert descendants are gone and an unrelated birth-fenced process is untouched. |
    | **TYPE**, tasklist:37 | Round-trip valid route/size/lines through each writer and the pre-edition reader; reject invalid metadata atomically without changing the record revision. |
    | **LAB**, tasklist:25 | Launch Claude and Codex through production adapters into distinct labs; prove each can edit its own tree and cannot edit its sibling or the line checkout. |
    | **A2**, tasklist:38 | Save from revision N after N+1 exists through the real command lane; require rejection with a diff and no project/task/document mutation. |
    | **RUNNER**, tasklist:22 | Run nested and standalone commands through the real runner endpoint under saturated capacity; assert every command is counted once, checks progress, and agent environments cannot bypass accounting. |
    | **EVIDENCE**, tasklist:26 | Feed runner-format evidence through the actual no-review acceptance path; tamper its payload and require rejection without completion advancing. |
    | **ADMIT**, tasklist:32 | Admit revision N, then author N+1; dispatch/retry/resume must never substitute N+1 for the admitted revision, including alias resolution and replay. |

**3. Sound**

- TOOLING3’s **sub-agent** specification is sufficiently concrete: the exact POOLX agent definition, model, effort and tool configuration exist at [POOLX/launch.sh:7](${TRANSFER_ROOT}/portfolio/ops/experiments/POOLX/launch.sh:7).
- HOSTKIT/POOL session IDs match recorded worker results; their labs and expected branches exist, and their owned source files are disjoint.
- POOL’s fix message explicitly covers the production constructor, ten flaky-test repetitions, placement and duplicated capacity state.
- Fresh staging rather than a live-Store clone directly addresses the measured startup blind spot.
- Existing bootstrap scripts preserve run output outside disposable labs and refuse dirty-lab removal.
- The POOL comparison reports both implementations’ defects and shows no measured speedup; it supports a cost experiment, not a general quality guarantee.

**4. Not checked**

- No scripts, tests, Otto commands, live Store access or prohibited directory listings were performed; no files were changed.
- TOOLING3, STAGE and PERCH implementation correctness remains untested by design.
- CLI flag/model availability, actual session resumability and remote GitHub state were not exercised; recorded references were checked.
- `ps` and swap inspection were denied by this sandbox. The named owner status file reported `serving`, but I could not verify process identity/liveness.
- `df -g /` reported **7 GB available**: the documented launch threshold was not met during this review.
- Documents were being prepared concurrently: the handoff claimed TOOLING3 landed while the inspected canonical head remained `9739a294…`.

**5. Delete list**

- **Retire historical inbox instructions from the active instruction path.** Keep history, but expose one current directive plus an acknowledgement cursor. This removes repeated interpretation of obsolete pause, ownership and baseline rules.
- **Delete the delegation tool-call percentage check unless instrumented.** The named JSON fields cannot calculate it; model-level cost is already available.
- **Delete duplicate worker-ledger writes by the manager.** The brief requires manual recording at line 48; `run-task.sh` already registers the complete record through `workers.py`. One writer avoids dropped fields and conflicting state.
- **Stop claiming `report.sh` generates a deletion ledger.** [report.sh:7](${TRANSFER_ROOT}/source/otto/ops/bootstrap/report.sh:7) emits landing subjects, workers and spend only. Either derive deletion data once from git or remove that promise from PLAN §15.
- **Consider narrowing mandatory twice-per-file repetition.** The measured evidence supports isolated test files and targeted repeated concurrency tests; it does not measure the benefit of doubling every affected file. One isolated pass plus explicit repeat sets would save roughly one complete affected-test sweep per landing.

**6. Helpers**

Seven Luna helpers ran; I inspected the decisive cited documents, scripts and result schemas.

- **manager_docs:** manager sequence, document conflicts, exact paths, branches, session IDs and file ownership.
- **launchers:** four launcher contracts, then next-ten-task acceptance gaps and placement.
- **bootstrap:** six bootstrap scripts, checklist artifacts and actual result-field semantics.
- **stage_dependencies:** stage triggers, missing capabilities, skip policy and dogfood ownership.
- **landing_atomicity:** candidate commit, concurrent landers, publication and gate deadlines.
- **worker_custody:** watchdog behavior, descendants, process identity and resume limits.
- **report_contract:** generated-record claims, landing-history parsing and consolidation opportunities.