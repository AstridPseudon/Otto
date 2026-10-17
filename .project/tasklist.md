# Tasklist: EFFECTS: one effect ledger in Herzchen

Routes are normal or xhard (Megado). Deps are task ids in this project. Sizes are focused days (4.75 in all, 2 XHARD).

| id | route | est (d) | deps | outcome | acceptance evidence | xhard justification | stream | status |
|---|---|---|---|---|---|---|---|---|
| EF1 | xhard | 1.5 | — | **The ledger, on kernel/operations.py:** planned → started → settled, or unknown. Starting is at most once per identity, and unknown is held. | `no_double_start_across_crash`, `unknown_is_held_not_retried` | Invariant: an effect never starts twice for one identity, including after a crash between start and record. Mistake: recording after starting. Surfaces: a paid turn or render runs twice. | effects | not started |
| EF2 | xhard | 1.0 | EF1 | **One reconciliation procedure for unknown effects:** a bounded evidence check, then settle, or hold with a human-visible request. | `process_gone_effect_unknown_reconciles_once` | Invariant: unknown never becomes success without evidence. Mistake: treating "process gone" as "done". Surfaces: lost work reported as finished. | effects | not started |
| EF3 | normal | 1.0 | EF2 | **Agent turns move onto the ledger.** owner_runtime and worker_custody use it, and the per-case modules are deleted (ledger). | suites green; modules removed recorded | — | effects | not started |
| EF4 | normal | 0.75 | EF1 | **Runner jobs move onto the ledger,** so checks and renders share the model with agent turns. | a runner job is a ledger effect; restart reconciliation is shared | — | effects | not started |
| EF5 | normal | 0.5 | EF3 | **Agent UX: `otto effects`.** It shows what's unknown and what to do. Refusals name the effect and its next action. | a cold agent resolves a seeded unknown effect from the view alone | — | effects | not started |
