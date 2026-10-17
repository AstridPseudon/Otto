# PROCLIFE: process lifecycle made structurally true

Astrid's process lifecycle should be true by construction, not proven by continuous observation. Each task attempt runs in a **task scope**. Each long-lived engine, and the pack host itself, runs in a **service scope**. Every scope has an owner that holds its handle until cleanup finishes.

Cleanup kills an anchored process group, or a handle bound to one specific process, and then reports `settled` or `unresolved`. It never invents absence, and nothing latches the whole host.

The full film journey (Codex image → sprite → edit → publish → full-film review render) passes on a normally busy 8 GB Mac with no exclusive heavy slot. The same contract holds on Linux and inside containers.

Evidence: the proposal, four Luna sense-checks and Astra's verdict are in `evidence/`. The rules are in `portfolio/PLAN.md` §15.
