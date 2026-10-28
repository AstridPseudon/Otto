# REVS resume (posted by the manager 2026-10-16T14:34:57Z; the orchestrator's 14:34Z and 14:34Z-correction sections)

Your commits are on `lab/REVS`, now rebased onto canon `2f0a769` (OWNERLANE). The rebase was clean; do not rebase again unless a test shows a real conflict. Your report is in `ops/runs/REVS/worker.json`.

**What the orchestrator decided:**
- **Install and hostctl are open to you now.** OWNERLANE has landed. `install/` and `src/otto/hostctl/` are open for the `get`→`current` rename only. The rename is mechanical, the same as in the tests.
- **Callers, all 48:** before REVS, `get` ignored the revision, so `get` was `current` everywhere. Renaming every existing `graph.get(` caller that relies on that to `graph.current(` preserves today's behaviour exactly. Do it mechanically across `install/` and `src/otto/hostctl/`, and any others, WITHOUT judging each caller.
- **Only** the sites the row names (ADMIT's pinned revisions, and an old-revision read) use `get(ref@rev)`.
- **Close the mapping-form gap:** a pinned ref in either form (the tuple form and the mapping form) reads its own revision, or is refused. The mapping form must not read the head.
- **D19 on your 28 test lines: LAND.** The orchestrator decided it; no Opus call. Each `get`→`current` keeps what the test read before REVS. Record it in `ops/reviews/D19-REVS.md` (the manager writes that file from the orchestrator's decision).
- Your report must list every REMAINING `graph.get(` site with its reason.

**Acceptance (the row):** after an edit, `get(task@rev-1).title` is the create's title and `get(task@rev-2).title` the edit's, and the project names `rev-2`; read the plan, revise one task directly, then save the old plan: refused naming that task, no rows written; ADMIT's pinned revisions resolve to their own content.

**Check:** `tests/test_revisions.py`, `tests/test_admit.py`, `tests/test_herzchen_boundary.py`, plus the `install/` and `hostctl` tests you touched, through `otto-heavy`. Note: `test_hostctl_cli.py:285` is a known gate flake under load (REDS's row). Don't "fix" it here.

**Layer:** Herzchen kernel and work domain. The rename in `install/` and `hostctl` is Otto wiring. `tests/test_herzchen_boundary.py` must stay green.

**Never wait:** no Monitor, no sleep loops. Any sub-agent uses `model: "haiku"`. Report the commit, the red and green runs, and the remaining `graph.get(` list.
