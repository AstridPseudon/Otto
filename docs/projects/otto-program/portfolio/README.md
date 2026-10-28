# otto-program: the Otto program portfolio

This is the file-mode root for the Otto portfolio `otto-program`, applied with:

    ottoctl portfolio apply --root ~/Developer/otto-program --root-namespace otto-program [--dry-run]

**Contents:**
- Shared documents: `PLAN.md` (the plan: end state, decisions, layering, risks) and `AGENT-UX.md`.
- The program, `projects/program` (run id `otto-program`), edition 1 and its clean-up.
- Six follow-up projects (PLAN.md §14), each waiting on `PROGRAM#edition-1`: `slim`, `effects`, `packs`, `harness3`, `throughput`, `astrid-fleet`.

This folder is the authoring source until CUTOVER saves the plans into the new Otto (PLAN.md D18). At that point it freezes. The operating instructions are `RUNBOOK.md`; the 15 Oct evening revision (the staging Otto, the observation perch, the stages and the Opus budget) is PLAN.md §16. Before 15 Oct the history lived in `~/Developer/otto-many-agents` (to commit 7a16577).
