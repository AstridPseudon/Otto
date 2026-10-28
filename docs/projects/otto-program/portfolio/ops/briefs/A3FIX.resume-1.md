# A3FIX resume (posted by the manager 2026-10-16T14:32:32Z; the orchestrator's 13:36Z answer)

OWNERLANE has landed (`2f0a769`). **Your lab is already rebased onto it** (the manager did the rebase; it was clean). Your commits `2fd7ae2`, `bc8c089`, `6ec56b9` now sit on `2f0a769`. Do not rebase again unless a test shows a real conflict.

**Amended A3FIX row (the orchestrator, 16 Oct 13:36Z):**
- Outside the owner, `otto` is a thin client. It forwards its argv through the owner lane, the way `ottoctl portfolio save` does. The owner runs `otto.portfolio.cli` with its own editor host.
- Nothing outside the owner builds a `DocumentEditorHost` or opens the Store (STAGE1 F7).
- `open`, `release` and `status` join OWNERLANE's set, named with this caller. Add them to `OWNER_PORTFOLIO_COMMANDS` in `src/otto/hostctl/portfolio.py` (OWNERLANE's one constant, now on canon). `status` is already a member; `open` and `release` are new. Each member names its caller in a comment.
- Your earlier `open`/`release` failures (`editor_host_unavailable`) are resolved by the thin-client route, not by wiring the host into a fresh shell. Do NOT wire the host into `install/controller/`.

**Acceptance (the row):**
- `otto open/show/status` run as `otto …` from a fresh shell, through the owner lane;
- a folder edit through `open` round-trips;
- two writers racing: the late one is refused with the base it lost to, never parked;
- a parked session is released by `otto release`;
- no Store file is opened by the client process (the test opens none outside the owner).

**Files:** the same as your brief, plus `src/otto/hostctl/portfolio.py` for the constant only, and `src/otto/hostctl/service.py` only if the owner's check needs the new names. Do not otherwise touch `src/otto/hostctl/`.

**Check:** `tests/test_otto_open_release.py`, `tests/test_otto_show_status.py`, `tests/test_document_editor_host.py`, `tests/test_owner_lane.py`, `tests/test_hostctl_portfolio_apply.py`, `tests/test_herzchen_boundary.py`, run through `otto-heavy`. The `test_completion_bridge` red is canon's, not yours; ignore it.

Never wait: no Monitor, no sleep loops. Any sub-agent uses `model: "haiku"`. Report the commit, the red and green runs, and what you deleted.
