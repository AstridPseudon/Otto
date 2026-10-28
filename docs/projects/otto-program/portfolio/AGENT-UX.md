> **Folded into PLAN.md on 14 Oct with Astra's simplifications** (see PLAN.md revision 4). Kept as the reasoning record.

# Agent UX: what stands between PLAN.md and an elegant end state (proposal, 14 Oct 2026)

**Status:** a proposal from Claude (captain). It is not yet in PLAN.md, and it waits for Astra's over-engineering check. Paths are relative to `~/Developer/otto-claude-host/otto/src/otto` unless noted. The facts come from `production/review/optimization/otto-plug/h1–h8.md` and `otto-plan/h-d, h-f`, and were spot-checked in source.

**The test of elegance.** A cold agent, Claude or Codex, is given a task. It should be able to:
1. learn what to do;
2. change code;
3. run the check;
4. iterate;
5. ask a question;
6. finish.

It should need about 4 tools, and no paperwork. Today, and in PLAN.md as written, several of these steps are blocked or ceremonial.

## Findings, ranked by agent cost

| # | What blocks it | Evidence | Proposed fix | Size; route | Where |
|---|---|---|---|---|---|
| 1 | **A worker can't run anything during its turn.**<br>• Claude leaf workers are denied process fork/exec.<br>• Codex workers run `-s read-only` in every profile, so they can't even write.<br>A worker writes code blind and learns about a failed check only after its turn. | `agents/claude_cli.py:175`; `agents/codex_cli.py:236` (`hostctl/config.py:102` declares workspace-write, but nothing applies it); PLAN.md §7 dropped "workers requesting checks" | **TOOLS:** an `otto` MCP server, reached over the D5 socket, so no exec happens inside the sandbox. It offers four tools:<br>• `task`: the brief, the check and the outputs of its dependencies;<br>• `check`: runs the task's check on the lab's current state through the runner, uncached. The result is feedback only;<br>• `ask`;<br>• `done`: with a one-line note.<br>Acceptance stays Otto's run after capture (D4). Codex workers get workspace-write confined to their lab. | 1.5 xhard (invariant: a worker's own runs never count as acceptance evidence) + 0.25 in LAB | edition 1 |
| 2 | **A failed check costs a cold start.** Workers never resume; only managers do. | `agents/claude_adapter.py:342`; h-f:33; h1:34 | **RESUME:** rework resumes the same worker session in the same lab, with the failure log as its next message (`claude --resume`, `codex exec resume`). | 0.5 normal | edition 1 |
| 3 | **Results are captured `Write` calls, not the change.**<br>• Claude: the last `Write` per file, up to 16 files × 64 KiB.<br>• Codex: command stdout, not files. | `agents/claude_adapter.py:63-106`; `agents/claude_cli.py:28`; `agents/native_result_verifier.py:15-59` | **The result is the lab's commit.** CHECK already commits the lab; the Write and stdout capture is retired. | +0.25 on CHECK | edition 1 |
| 4 | **No scheduler.**<br>• An LLM manager does mechanical dispatch: one paid turn per dispatch.<br>• Task deps are not checked on the dispatch path. | h7:5, h7:9 (`portfolio/execution_operations.py:713-722` is read-side only); `portfolio/operating_brief.py:149` | **AUTO in M4:** one dispatch function used by every path. It runs a task when it is admitted, its deps are accepted and a turn slot is free, and picks the model by route. It wakes the manager only for judgment: a second failure, an `ask`, or a change outside the allowance. Small projects need no manager LLM. | +1.0 on M4 (xhard) | edition 2 |
| 5 | **Too many surfaces.**<br>• `ottoctl` (lanes, request keys, schedule ids), `otto`, `otto-run` and `otto-heavy`.<br>• Accepting a task takes 8 operations.<br>• `manager report --request-key …` makes the agent mint idempotency keys. | opus-lean-review:28; h-f:46 | **One `otto` command** for people (open, save, show, admit, status, wait, run, heavy, upgrade), and the 4 MCP tools for agents. Tools mint request keys. `ottoctl` stays an admin surface only. | +0.25 on A3 | edition 1 |
| 6 | **Refusals don't say what to do next** (`held`, `otto_newer`, "owned validation lacks positive original wait …"). | this week's sessions | **NEXT:** every non-ok outcome carries `next:` with an exact command. A contract test covers every refusal code. New verbs follow it from day one. | 0.75 normal | edition 2 |
| 7 | **Asking and waiting are files and polling:** `codex queue` threads, reply files, the orchestrator's `stat` loops and hourly wakes. | PLAN.md L5 (wave 4); this session | **L5 moves to edition 2 and grows:**<br>• `ask` pauses the task, not the process, and the answer resumes the asker's session;<br>• `otto wait` returns when something needs the caller. | L5 0.75 → 1.0, moved from wave 4 | edition 2 |
| 8 | **Every plan edit needs a human `admit`.** The user becomes the bottleneck for corrective tasks. | PLAN.md M5; W2 tasklist M5 | **An allowance on admission:** you admit a scope once, with routes, a size cap and a budget. A manager's additions inside it are admitted automatically, and anything outside waits for you. | M5 0.5 → 1.0, now xhard (authority) | edition 2 |
| 9 | **Six documents per project:** northstar, agent_goal, run.json, plan, tasklist and status. | Megado SKILL "Run location and structure" | **A project is a brief plus tasks** (plus optional docs).<br>• Status is derived.<br>• The tasklist is the records.<br>• run.json becomes project settings.<br>The G3 rewrite and templates do this. | G3 0.25 → 0.75 | edition 2 |

**Cost:** about +5.5 focused days. v1 gains ≈ 2.75 (rows 1, 2, 3 and 5); edition 2 gains ≈ 3.5 (rows 4, 6, 7, 8 and 9); wave 4 shrinks by 0.75. The total goes from ≈ 30.5 to ≈ 36.

**What I would cut first if this is too much:**
- row 9: guidance only;
- row 8: humans keep admitting each change;
- row 6: retrofit refusals as they are touched.

Rows 1–4 are the inner loop and the dispatch path, and I would keep them.

## The end state for an agent

```
task   → brief, check, deps' outputs           (MCP tool)
check  → runs the check now in the runner, returns the log   (feedback only)
ask    → question to the manager/user; the task pauses; the answer resumes this session
done   → one line; Otto commits the lab, runs the admitted check, accepts or resumes me with the log
```

For people: `otto open/save/show/admit/status/wait`. Everything else is Otto's job.
