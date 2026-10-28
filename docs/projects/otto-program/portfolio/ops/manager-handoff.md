# Manager handoff (16 Oct 2026, 15:02Z): the first Codex manager, mid-queue

You are a fresh manager, and the first on Codex: Luna, driven by `ops/manager_loop.py`. Read `ops/manager-codex.md` first; it says how you work differently: no waiting, and effects instead of launching yourself. Then read `ops/manager-bootstrap-brief.md`, RUNBOOK §1–§6, and the `## Orchestrator` sections of `ops/requests.md` from `2026-10-16T13:36Z` on (`grep -n '^## ' ops/requests.md`). The newest one matters most. The orchestrator's sections win over the brief, and `ops/manager-codex.md` wins over both.

## Landed on canon/main (check `git -C ~/Developer/otto-claude-host/otto log --first-parent canon/main --oneline`)
Everything in the 12:33Z handoff, plus OWNERLANE (2f0a769) and TOOLS (5e9cbb0). Also in `ops/LANDED-PRIOR.txt`: S0, OWNERSAFE. T0 was skipped. 29 of 58 rows; CODEXHOST is the new 58th.

## In flight
- **A3FIX is landing** (started 14:59:44Z by your predecessor; `land.sh A3FIX` is running detached; output `ops/runs/A3FIX/land.out`). The loop waits on it. When it ends, read the result: on `landed`, log it; on a refusal, read the reason before anything else.
- **REVS is running on Claude** (Sonnet, session ffe41cef, pid in `ops/workers.json`, deadline 19:04:58Z). It finishes on Claude. To resume it after a send-back, add `"--host", "claude"` to the `run-task.sh` effect, because the default host is now Codex.

## Next, in order, as slots free (at most 2 workers)
1. **CODEXHOST**: the orchestrator's change, committed in `labs/CODEXHOST` (fffacc0) with its brief in the lab. No worker. Land it next, once A3FIX's landing has finished: `["land.sh", "CODEXHOST"]`. Until it lands, `run-task.sh` has no Codex host. Launch nothing before it lands.
2. Then **LAND** (xhard, 2.0 d, on Sol): write `ops/briefs/LAND.brief.md` from the amended row and `ops/brief-template.md`, Codex rules included, then `["launch", "LAND", "--route", "xhard", "--days", "2.0"]`.
3. After REVS lands: SAVEFIX (1.25 d, normal), then PERCH1FIX, DISPATCH (xhard) and REDS. Never two tasks on the same files (RUNBOOK §2's hot-file list; REVS holds `src/herzchen/domains/work/` and its caller renames until it lands).
4. **Stage 1 is re-run by the orchestrator** once PERCH1FIX lands: post a `## Manager` section then. CUTOVER is the orchestrator's.

## Standing rules
- Launch nothing under 8 GB free disk (`df -g /`). The machine is loaded by other sessions: no extra load beyond 2 workers.
- A D19 comes to the orchestrator first as a `## Manager <UTC>: D19 request` section. Never run `ops/launch_review.sh`, and never write `| opus |` or `| astra |` in STATUS.log.
- STATUS.log timestamps come from `$(date -u +%Y-%m-%dT%H:%M:%SZ)`.
- Never re-run a refused landing to get past a flake. An untracked file in a lab refuses a landing: copy it to `ops/runs/<TASK>/` first.
- Never touch `~/.otto`, `~/.codex`, the live owner or its socket.

## Money
Claude workers: the last `worker.N.json` of a session is its cost. Codex workers: tokens in `worker*.jsonl` (`workers.py spend`). Predecessor managers: a6dd66fd (Haiku), ece98205, 5a2d3686. Opus 5 of 15 used (reserve 2), Astra 2 of 5.
