# Tasklist: PACKS: data, not code

Routes are normal or xhard (Megado). Deps are task ids in this project. Sizes are focused days (2.5 in all, 0 XHARD).

| id | route | est (d) | deps | outcome | acceptance evidence | xhard justification | stream | status |
|---|---|---|---|---|---|---|---|---|
| PK1 | normal | 0.75 | — | **Pack layout and loader** for roles, profiles, templates and host data: versioned and digest-pinned, on packs/composition and pack hashes. | `role_from_pack_with_project_override`, `pack_digest_pinned` | — | packs | not started |
| PK2 | normal | 0.5 | PK1 | **Megado and the templates become one pack.** Hosts install skills from it, and the duplicate copies are deleted. | one Megado source; the copies are gone | — | packs | not started |
| PK3 | normal | 0.5 | PK1 | **Profiles and host data:** model bindings per route, review stages, the oracle budget and qualified launcher versions. A project names a profile and overrides it. | no model names hard-coded outside packs (grep) | — | packs | not started |
| PK4 | normal | 0.5 | PK1 | **Domain packs:** engineering (code tasks with pytest checks) and astrid (journey and frame checks, film-edit templates). | a new project starts from each pack | — | packs | not started |
| PK5 | normal | 0.25 | PK3 | **Agent UX:** `effective-context` shows which pack and which override gave each instruction and tool. | a cold agent explains its own instructions' sources | — | packs | not started |
