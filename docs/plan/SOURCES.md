# Sources: where the code and references are

**The new tool's code lives on `main` of `AstridPseudon/Otto`**, restarted fresh on 30 Oct; this plan is in its `docs/plan/`.

## Included in the handover zip
| Path in the zip | What it is |
|---|---|
| `plan/` | This package: the spec, the plan, the projects, the decisions and the history. |
| `reference/otto-20261028-compact.zip` | **Old Otto's complete transfer archive.** It includes the integrated source, the portfolio, pinned skills, and `otto.bundle` with the full history of all 26 preserved branches. To restore: unzip it, then run `python3 otto-20261028/restore.py /new/path/otto-received` (the destination must not exist). That rebuilds the repo plus 23 lab and project worktrees. Read `otto-20261028/START-HERE.md`; its `branches.json` lists every ref. |
| `reference/plan-repo-refs.txt` | Every branch of the planning repo, with its commit, at packaging time. |
| `SHA256SUMS` | Checksums for everything in the zip. |

**What's already preserved, and what X0a still does:**
- **Already preserved:** old Otto's 26 refs, on GitHub (`transfer/20261028/*`) and in `otto.bundle`.
- **Already preserved:** the planning repo's 8 branches, on GitHub (listed in `plan-repo-refs.txt`).
- **X0a still does:** verify both, add tags, rehearse one restore, and take a bundle of the planning repo.

## In old Otto (branch **`deprecated`** of `AstridPseudon/Otto`, the `transfer/20261028/*` branches, or a restore)
| What we reuse | Where |
|---|---|
| Integrated code | `a70b3f2` (branches `deprecated` and `transfer/20261028/canon/main`) |
| Installed baseline | `bbd9b6d` (`transfer/20261028/canon/installed`) |
| Draft-sync fix | `b834793` (`transfer/20261028/fix/portfolio-draft-sync`) |
| **The Megado pack source** | `403182e` (`transfer/20261028/proj/packs`), path `src/otto/packs/megado/` |
| Folder validators | `src/otto/portfolio/project_folder.py` (`validate_files`, filesystem checks); `src/herzchen/content/model.py::document_path` |
| The landing sequence | `src/herzchen/fleet/landing.py`: rebase, check the exact commit, refuse if the target moved, fast-forward |
| Behaviour cases | `tests/test_landing.py`, `tests/test_work_readiness.py`, `src/otto/portfolio/tests/test_document_sessions.py`, plus the LANDPROOF, PROOFDOC, DISTURB and REALSTAGE3 labs |
| Every preserved ref | `branches.json` in the archive |

## oh-my-pi (public)
- **Repo:** `https://github.com/can1357/oh-my-pi`. The npm package is `@oh-my-pi/pi-coding-agent`, which needs **Bun ≥ 1.4.4**.
- **Reviewed at:** `18.14.0`, commit `95db18e`. **S0 pins the latest release** and records it in `projects/s0-findings.md`.
- **Docs to read:** `docs/rpc.md`, `cli-reference.md`, `settings.md`, `models.md`, `skills.md`, `task-agent-discovery.md`.
- **Code to reuse:**
  - the Python client, `sdk/python/omp-rpc` (alpha, Python ≥ 3.11);
  - a loopback test provider to adapt, `packages/coding-agent/test/rpc-wire/fake-openai-server.ts`.

## Astrid (private: `banodoco/astrid-agent`; ask the owner for access)
Reviewed at `origin/main` `aadd0ff`. These are reused as a **pattern only** (a new pin, new hashes):
- `astrid/installer/omp/recipe.json`, `astrid/installer/tools.py`: the pinned, checksummed omp install;
- `astrid/omp_agent.py`: login-readiness through RPC `get_login_providers`, never reading tokens.

## The planning repo
GitHub `AstridPseudon/repo` (formerly `HannahSubmarine/repo`), folder `astrid-install/retro/`, branch `claude/gallant-brown-ulwhyx`. **Do not use its `tools/land.sh`:** it uses `--no-ff`, runs no check, and removes worktrees.

## Not available to you
Links in `evidence/` that point into `/tmp/...scratchpad/...` were the reviewers' local clones of the sources above. Use the sources above instead.
