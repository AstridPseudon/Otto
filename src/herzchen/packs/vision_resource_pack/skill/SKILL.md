---
name: vision
description: "Maintain a bounded connected map of product intent and architecture."
---

# Vision

Use the finite host-owned `vision` command over ordinary DAT/EDT documents.
The pack is resource-only: it supplies vocabulary, templates, presets, and
guidance; the host supplies authentication, validation, bounded projection,
CAS, and receipts.

## Elicit

Start with a concise product root, then add areas, repository descriptions,
subsystems, shared concepts, and design decisions. Ask for responsibility,
interfaces, tradeoffs, and unresolved choices. Keep aspirations separate from
observed implementation, current Direction, and authorized tasks.

## Navigate and query

Use `help` to receive the current exact resource pins. Use `query` with one of
the finite presets: `outline`, `related`, `by_repository`, `repositories_for`,
`shared_concepts`, `search`, or `audit`. The root roster is the bounded
collection; the reading parent is navigation and is not membership.

## Maintain

Use authoring or the finite reorganization operation for rename, reparent,
alias, and collection changes. Preserve stable document identities and let
EDT/DAT CAS report conflicts. Reads are authenticated and read-only. Context
defaults to latest child content; `history` and `snapshot`/checkpoint are
explicit actions. A root-only snapshot follows current children; a complete
collection snapshot retains exact observed revisions.

Pack upgrades are explicit and non-retroactive. An unavailable historical
definition is reported as unavailable; it is never silently replaced. Disabling
this guidance prevents new guided admission only and preserves content,
revisions, checkpoints, and citations.
