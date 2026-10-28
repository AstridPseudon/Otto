# Goal: EFFECTS: one effect ledger in Herzchen

Every external effect (an agent turn, a render, a paid API call) has one identity in Herzchen's kernel and runs at most once. An unknown outcome is held and settled by one reconciliation procedure. The per-case custody modules are gone.

It waits for `PROGRAM#edition-1`.

**Deletion budget:** the per-case capture and recovery modules this replaces: manager capture reconciliation, the successor remains, the execution_resume variants, and the parts of worker_custody and owner_runtime that duplicate the ledger.

Pending: nothing runs without the user's go. Rules: `portfolio/PLAN.md` §15.
