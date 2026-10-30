# Tasks: attach (about 3 days)

| ID | Task | Tier | Days | Depends on | Done when |
|---|---|---|---:|---|---|
| A1 | **Seat binding:** `attach` and `whoami`; resolve the seat; stop the supervised holder and confirm its exit; `--force` and stale bindings; the binding transaction; `.otto/agent` | X-hard | 1 | — | Takeover, force, stale-window and crash-mid-attach tests pass |
| A2 | **Handover packet:** `.otto/handover.md` from the role file, skills, mandate or brief, and current work | Normal | 0.5 | A1 | The packet is complete for each of the four seats |
| A3 | **Pull inbox:** `otto inbox`, `otto ack`; reminders queued for external seats; the idle check skips them | Normal | 0.5 | A1 | Messages and reminders wait, and are acknowledged once |
| A4 | **Detach:** the handover note, the binding end, and a fresh supervised session with pending delivery | X-hard | 0.5 | A1, A2 | Detach restarts the seat, and pending messages arrive once |
| A5 | **Acceptance and a real run:** §1–6 in CI; the manager attaches a real Claude Code window as a manager for a small project, then detaches | Normal | 0.5 | A1–A4 | CI is green, and the real run is logged |
