# DONESETTLE resume 1

The landing gate refused the current patch under D14: its brief says Herzchen fleet, but it adds 8 lines under `src/otto` and none under `src/herzchen` (`ops/runs/DONESETTLE/land.log`). The outcome is reusable fleet settlement ordering. Refactor the landed-done settlement behavior so the reusable owner/facade boundary logic lives under `src/herzchen/fleet/`; keep only Otto-specific wiring in `src/otto/hostctl/product_service.py`. Add/update tests in `tests/test_fleet_custody.py` to prove settlement finishes before the owner operation signals its waiter and queued calls on settled records are refused. Preserve the existing active-record gate and the original landed condition/exception behavior; do not weaken assertions. If the existing Herzchen API cannot support this without changing the outcome or crossing a boundary, stop and report the precise blocker rather than placing reusable logic in Otto.

Keep the task's focused check command from `.brief.md` and run it through completion. Report files changed, canon red/lab green evidence, and `git diff --check`.

Do not touch `production/`, Stores, `~/.otto`, `~/.codex`, Codex project configuration, or files outside this lab. No other worker owns DONESETTLE files. Work only in the existing DONESETTLE lab; do not commit or push.
