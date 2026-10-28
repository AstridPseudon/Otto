# Tasklist: ASTRID-ON-FLEET: Astrid's agents on the Herzchen fleet (study first)

Routes are normal or xhard (Megado). Deps are task ids in this project. Sizes are focused days (2.5 in all, 1 XHARD).

| id | route | est (d) | deps | outcome | acceptance evidence | xhard justification | stream | status |
|---|---|---|---|---|---|---|---|---|
| AF1 | normal | 1.0 | — | **Map Astrid's agent flows** onto the fleet: tasks, labs, renders through the runner, tools; list the gaps. | the map and gap list | — | astrid-fleet | not started |
| AF2 | xhard | 1.0 | — | **Ledger convergence:** Astrid Runtime's idempotency and receipts versus EFFECTS. One model, or adapters? Evidence from both code bases. | a recommendation citing file:line on both sides | Invariant: neither side loses at-most-once. Mistake: mapping "replay" semantics that differ (Astrid's 24 h expiry versus a permanent ledger). Surfaces: a duplicate paid render after the merge. | astrid-fleet | not started |
| AF3 | normal | 0.5 | AF1, AF2 | **Proposal:** a sized project with Megado tasks, or a reasoned no. | the proposal, reviewed by Astra | — | astrid-fleet | not started |
