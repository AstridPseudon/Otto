Your run was stopped for low disk, not for a fault in your work. The disk is clear now.

Current state of `labs/POOL`:
- The lab is on branch `lab/POOL` (it was detached). Your commit `f57688d` "POOL: one capacity pool for turns and heavy work (D3)" is on it. Continue from there.
- That commit is based on `c3880e0` (HOLD). canon has moved on to `16825ca`, but the only changes since are in `ops/bootstrap/`, so they don't touch your code. Do not rebase; the manager rebases at landing.
- The lab was clean when you were stopped. Check `git status` and `git log --oneline -3` first.

Do this:
1. Check that your commit's changes are what you expect (`git show --stat f57688d`). Continue your brief from there. Do not restart the work.
2. Commit work in progress as you go, to `lab/POOL`, instead of stashing. Never run `git stash`. Commit only files you own; never `.brief.md`, `.worker.json` or `.worker.err`.
3. Never check out another commit in the lab. Comparing against canon is the manager's job at landing.
4. Known gap from HOLD, in your scope: `record_process_group` and `reconcile_dead_holds` are not wired into `owner_runtime`, and `_eligible` still counts every fence entry. Close it as part of the capacity pool, or say in your report why it stays open.
5. Do not run `ottoctl`, and never pass `--help` to it. Do not push.

Report the commits, your check runs (red, then green), and anything you could not finish. Keep the report short.
