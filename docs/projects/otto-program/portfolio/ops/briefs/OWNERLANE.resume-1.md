# OWNERLANE resume (posted by the manager 2026-10-16T13:36:44Z; the orchestrator's 13:36Z answer)

Your report is in `ops/runs/OWNERLANE/worker.json`. Your commits `5bc7a67`, `719d044`, `c709145`, `e0c60d4` stay. Keep `e0c60d4`: `ottoctl service run` projecting history is the row's third bullet.

The orchestrator amended your row. The amended row is below; it replaces the earlier one.

**Amended OWNERLANE row (16 Oct 13:36Z):**
- The explicit set is ONE constant in `src/otto/hostctl/portfolio.py`. The client's forward list (`prepare_portfolio_request`) and the owner's check in `service.py` both read it.
- Members, each with its caller in a comment: `save`, `show`, `read` (clients, STAGE1 F7), and the operator's `status`, `documents`, `retire`, `sync-docs`, `apply`, `gate`, `prerequisite` (forwarded today by `prepare_portfolio_request`).
- `admit`, `complete-task` and every unnamed subcommand are refused with `PermissionError`.
- Peer identity on the lane is not this row's job.

**Corrections to your report:**
- The row does NOT remove `status`, `documents`, `retire` or `sync-docs`. They stay, as members of the set.
- Because `apply`, `gate` and `prerequisite` are members, `tests/test_hostctl_portfolio_apply.py` must pass 8 of 8 WITHOUT any assertion changed. No D19 is needed.

**Still to finish:**
- F7: `show` and `read` from a client go through the owner lane. `owner.py:157-171` still opens the Store directly outside the owner; close that for the client path.

**Acceptance:**
- `tests/test_hostctl_portfolio_apply.py` 8 of 8, unchanged;
- `admit` and `complete-task` through the owner lane are refused with `PermissionError`;
- `show` from `env -i` returns saved tasks while staging is up (in tests, the lane returns them);
- at rest `history_checkpoint` equals the last append position.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_owner_lane.py tests/test_hostctl_ownersafe.py tests/test_hostctl_portfolio.py tests/test_hostctl_portfolio_apply.py tests/test_herzchen_boundary.py`. Run it through `otto-heavy` as before.

Land as soon as the check is green. Report the commit, the red and green runs, and what you deleted. Never wait: no Monitor, no sleep loops. Any sub-agent uses `model: "haiku"`.
