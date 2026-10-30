# Is there a 90:10 path to the end state?

You are **Astra**. Read-only. You may start Luna sub-agents (`spawn_agent`, model `gpt-6-luna`) for anything open, and verify load-bearing facts yourself.

**The question:** the full plan is 137 engineer-days (`retro/09-otto-breakdown.md`, with tables in `retro/evidence/otto-breakdown/astra-breakdown.md`). Is there a path that delivers about 90% of the end state's value for a small fraction of that effort, **while still fulfilling the end state**? The orchestrator will judge your answer against the end state, not against effort alone. A cheaper path that quietly drops part of the end state doesn't count; say plainly what any option loses.

## The end state (from `retro/07-first-principles-review.md`; every point must be met, or its loss stated)
1. An owner **mandate**: outcome, acceptance through the real user path, scope and effects, budget, reserved decisions.
2. **Managers dispatch;** the system **wakes** the responsible manager on events. No automatic dispatch.
3. **Declared turn exits,** checked: nudge the agent, then its supervisor. Observation mode first.
4. **A liveness monitor:** never-started runs, dead sessions, overdue declared waits.
5. **Tools record their own receipts,** with base and execution identity; status and handoffs are derived from them.
6. **One launch boundary** for every role: model policy, spend and capacity.
7. **One message interface** with wake-up, reply and resolution; owner decisions authenticated.
8. **A cheap supervisor sweep;** only exceptions go to the orchestrator.
9. **Capable workers:** shell or a capable `check`, `ask`, turns sized to the task, resume with the log.
10. **Verification:** real-user-path acceptance; implemented, verified and accepted-with-gaps kept separate; batch integration, then qualification; reviews with a stopping rule.
11. **A small instruction core plus judgement guidance,** tested by replaying incidents.
12. **Measured controls.**
13. **Cloud sessions and git** as first-class.

**The goal behind it:** trustworthy progress with little owner intervention, within scope, cost and quality. The problems it must fix: idle managers, status-chasing, policy drift, stale state, wrong baselines, runaway reviews, the orchestrator doing hands-on work, and dead managers.

## Facts you can't see from the files
- **The programs ran on Claude Code cloud sessions** (orchestrator and managers), plus Codex CLI workers in the orchestrator's container. The platform already provides these primitives, which the orchestrator used daily:
  - **Session APIs:** `get_session` gives status (working, blocked, review_ready, completed, failed), cost, context size and the last model. `list_events` gives the transcript. `send_message` delivers a message to another session and **wakes it**. `create_session` and `archive_session` start and retire sessions. `interrupt_session` stops a running turn.
  - **Scheduled tasks** (cron or one-shot) wake a session with a stored prompt. That's how the hourly check ran.
  - **Claude Code hooks:** a **Stop hook** can block a turn from ending and feed a message back. In this session, a stop hook blocked a turn over unpushed commits. Hooks also exist for pre- and post-tool use.
  - **GitHub:** branches, PRs, Actions (hosted runners stayed queued on one owner repo), comments and issues. A PR-activity subscription wakes a session on CI and review events.
  - **Codex `exec`:** a non-interactive worker with a sandbox, `resume` and `-o` output; it can be wrapped by a script.
- **The thin path** (`astrid-plan-repo/tools/*.sh`, about 330 lines) ran a 3-day, 60-plus-task program with these primitives plus files on git.
- **Otto** is 118K lines of non-test source, built for one local Mac with a SQLite store. See `retro/evidence/otto-roadmap/` and `OTTO-FACTS.md`.

## The orchestrator's candidate options (critique, rank, improve, or replace)
**Option 1, process first, about 8–12 days.** Deliver the behavioural end state on the thin path using platform primitives:
- a POLICY plus a short role guide, compiled into every brief;
- a Stop hook for manager turn exits (declare, check against the queue, nudge, then `send_message` to the supervisor);
- the supervisor sweep as a scheduled task on a cheap model, reading `get_session` and `list_events` plus the queue;
- liveness from `get_session` status and dispatcher heartbeats;
- message files plus `send_message` for wake-up;
- receipts written by the dispatcher;
- a spend line checked before each launch.

It covers points 2–5, 7, 8, 11 and 13 at one-owner scale, and partly 1, 6, 9, 10 and 12.

**Option 2, Otto-lite harness, about 35–45 days.** Option 1, hardened into a small purpose-built service of roughly 3–5K lines, which replaces the shell dispatcher. It has:
- git-backed records with a single writer (the service), on cloud sessions;
- platform session APIs for liveness and wake-up;
- GitHub Actions or a self-hosted runner for qualification;
- the mandate as a record;
- reservation-based spend;
- capable Codex and Claude workers;
- the three acceptance states.

Otto's labs, runner and landing are reused as a library only where they help. The 118K-line Otto service isn't carried forward; it's a reference, or retired. It meets all 13 points **at one-owner scale**. What it gives up compared with full Otto: rigorous at-most-once effects with process custody, authenticated multi-host authority, and the hardened Mac fleet.

**Option 3, Otto-minimum, about 60–70 days.** Keep Otto as the product, but do only A, a trimmed B, and F-lite (exits, messages and receipts using Otto's existing issue loop and attention code). Defer D's full custody and effects work, PACKS and G. Otto remains local-first.

**The full plan: 137 days.**

**The orchestrator's tentative view:**
- The 90:10 for the **process** is Option 1.
- The 90:10 for the **tool** is probably Option 2: the platform already supplies liveness, wake-up, scheduling and hooks, and Otto's heaviest guarantees mainly protect against failure modes that matter little at one-owner scale.
- **But Option 2 is a strategic call:** it walks away from carrying Otto's codebase forward.
- **Uncertain:** whether one-owner scale is the real target; whether authenticated owner decisions and run-once paid effects can be "good enough" without Otto's machinery; and whether platform primitives are reliable enough to build on (cloud wake-up hasn't been proven at scale).

## What to deliver (final message)
1. **The options ranked,** including any better 90:10 you see, such as a hybrid or a different cut. For each: effort (engineer-days), **which end-state points it meets fully, partly or not at all, and why**, the main risks, and what it costs later if you need the full guarantees.
2. **The single best 90:10 recommendation,** as a concrete scope: what's in, what's out, the task list at roughly 3-day granularity with difficulty 1–10, and the total days.
3. **The guarantees that are genuinely non-negotiable** even at one-owner scale, and the cheapest way to keep each one.
4. **What would make you change the recommendation** (the evidence or the scale that tips it).

Be concrete and terse. Don't drop end-state points silently.
