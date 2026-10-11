# Friction log: the first non-Codex host (Claude Code), 10–11 Oct 2026

## Root cause first

We built a **second owner**: a Claude-only Store in `~/.otto-claude`, with its
own root orchestrator. Megado's project lifecycle already said what to do
when a caller lacks the owner authoring surface: hand the authoring action to
the owner. We did not. Most later work was undoing that:
- the r4 registration in `~/.otto-claude` is void;
- two Stores had to be reconciled;
- the "isolated host" commands were rebuilt as one-Otto commands.

The design that replaces it:
- ONE running owner service holds the one Store;
- hosts are its clients, as their own principals, through lanes;
- admitting a host is an owner action;
- "is the owner busy?" is a supported status read.

See [OTTO-ONE.md](../OTTO-ONE.md).

## Frictions and fixes

| # | Friction | Fix (commit) |
|---|---|---|
| 1 | A second owner and Store were created instead of handing authoring to the owner | One owner service; hosts admitted as principals; clients through lanes (`52cf6a5`) |
| 2 | The live-store join needed Claude to open Codex's Store and inspect `~/.codex`; the permission system refused both | Clients never open the Store or read other hosts' folders; `service status` (`52cf6a5`) |
| 3 | The skill and role guidance named Codex's interpreter and controller path; defaults were gpt-only | Host-neutral defaults; role guidance names the host's own command (`d336c73`, `6775375`) |
| 4 | Claude could not be a manager: its CLI creates its session at first launch | The `fresh_manager` execution mode; resume of the owner-bound session (`b8c271d`, `eae211e`) |
| 5 | A terminal-launched owner failed to authenticate its own children | Ancestry stops at the owner (`0aa435c`) |
| 6 | Every orchestrator reply to a fresh manager failed: "role conversation current assignment/project differs" | The conversation is bound by the owner's authorized delivery (`eae211e`) |
| 7 | A sandboxed manager could not reach the owner during its own turn: socket commands blocked on the command lock | Manager lanes: the file lane for commands without identity, the socket for identity (`52cf6a5`) |
| 8 | The manager could answer its own escalation over a writable lane | Replies are accepted only with an owner-issued grant kept outside every fence (`52cf6a5`) |
| 9 | The manager surface had no document read; registered documents were private to their author | `project-documents` through Otto; the visibility question is recorded for Codex (`52cf6a5`, `eae211e`) |
| 10 | Draft creation hung on the 7.6 GB live-Store clone: whole-history event decode | Subject-filtered event reads (`7e45ba7`, `5f5f8ad`) |
| 11 | A project was capped at 50 documents and 1 MiB IN TOTAL, and N reads cost O(N²) | Per-operation bounds; one listing per read batch (`8b1166b`) |
| 12 | Nested briefs, reviews and decisions were not registered | The whole run directory is registered; what can't be stored is refused (`d7905d2`) |
| 13 | After activation, run work stayed only in files | `sync-docs` records it before and after activation, with three-way safety (`673c433`) |
| 14 | A closed run (r3) had no place in Otto | `import-history`: the whole run dir, withdrawn (`0625c5c`) |
| 15 | A flaky admission: the service read a half-written request | Requests are linked into place atomically (`b9c4c3d`) |
| 16 | The launcher was pinned to 2.1.293 while 2.1.296 was installed | Host-qualified exact versions; `admit-host --qualify-version` and `host qualify-launcher` (`b8c271d`) |
| 17 | Usage did not understand Claude's stream (cache tokens, cost) | Anthropic semantics in Codex's Usage model (`f2de8a0`) |
| 18 | `manager --timeout-seconds` was rejected by the top-level parser | Manager and portfolio arguments pass through verbatim (in `52cf6a5`) |
| 19 | Megado setup: no edition stamp, no Claude template, no glossary or adopt-in-flight step, no budget scaling; product acceptance was confused with review | Fixes 1–8 in the skill (`d288e7b`) |
| 20 | Skill links pointed into the repository (`../../../../docs/...`) and broke when installed under `~/.claude/skills` | The Megado skill links its installed sibling (`otto/references/manager.md`). The Otto skill's repository links remain Codex's to change |

## Live-store custody (evidence)

- **Clone proof, 10–11 Oct.**
  - The clone tool waited 121 s for idle.
  - It held the owner flock for 0.0025 s and cloned the db (7.68 GB; no
    sidecars) with APFS `clonefile`.
  - `integrity_check` returned ok in 21 s, run on the clone only.
  - Every step was proven on the clone: install, join, register, activate,
    dry-run and a serve smoke test. All 16 Codex projects were unchanged.
  - The clone was deleted, which is logged in
    `production/ledger/housekeeping.log`.
- **Disposable NEW Stores** for the service split and the scale tests were
  deleted after recording, also logged.
- **No live write was made.** The two permission denials are quoted in
  OTTO-ONE.md.

## Suite comparison

See OTTO-ONE.md, "Suite comparison".
