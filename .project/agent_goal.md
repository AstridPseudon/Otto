# Goal: SLIM: the Otto diet, one way to do each thing

`otto/portfolio` and the controller hold only what the end state uses, with exactly one implementation of each mechanism and the smallest agent-facing surface.

It waits for `PROGRAM#edition-1`.

**Deletion budget:** ≥ 25% of `src/otto/portfolio` lines (≈ 45k today, measured at SL0), every W0- or incident-specific controller script, and every module without a caller.

Pending: nothing runs without the user's go. Rules: `portfolio/PLAN.md` §15.
