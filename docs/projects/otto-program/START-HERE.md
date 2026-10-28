# Otto program — transfer, 28 October 2026

Start with [the purpose](PROJECT-ESSENCE.md), [what the fixes protect](FIXES-ESSENCE.md), and [current state](CURRENT-STATE.md). Original plans, tasklists, briefs, decisions and selected check evidence are in `portfolio/`.

## The exact state

The portfolio source is commit `3ae2036e341f13d6526abd42d9c12d710cec7c62`. The integrated code is `a70b3f2685c6d373c064e495fd803179e723b704`. Integration rounds 1–4 landed; 16 lab branches and seven follow-up project branches retain unfinished work. `branches.json` maps all 26 preservation refs to exact commits and GitHub links, including the installed baseline and draft-sync fix.

Repository: https://github.com/AstridPseudon/Otto

Control package: branch `handover/otto-program-20261028`, directory `docs/projects/otto-program`. Its base is the program's `main` commit above, intentionally not GitHub's symbolic default (`delivery/otto-herzchen-v11.2` at discovery). Preservation refs use `transfer/20261028/…`. They are snapshots, not accepted landings. Do not merge them as a batch.

## Receive safely

The ZIP contains readable integrated/follow-up source, the portfolio, pinned skill copies, and `otto.bundle` with complete reachable history for all transfer branches. `python3 restore.py /new/path/otto-received` checks hashes and restores a working repository plus the lab/project worktrees. The destination must not exist. It never starts an owner, worker, manager, or installation.

Online alternative:

```sh
git clone --branch handover/otto-program-20261028 https://github.com/AstridPseudon/Otto.git otto-handover
cd otto-handover
```

Read the control package directly there. For work, check out `transfer/20261028/canon/main` in a separate worktree, then reconstruct selected lab/project refs from `branches.json`.

## Resume boundary

This transfer does not resume the paused program or authorize CUTOVER, deployment, main-branch merges, deletion of old state, or new review spend. Read the last Orchestrator section of `portfolio/ops/requests.md` first. STAGE2CLIENT's failed check is first in the resume queue. Old `status.md`, manager handoff, and proposed stages in `run.json` lag actual history; preserve them as records, not fresh truth.

Existing run configurations, stages and budgets remain unchanged. Program caps are 15 Opus and 5 Astra calls; reconcile recorded usage before any call. This packaging task used Luna helpers as requested; Terra was available for hard questions but not needed. That does not silently replace the historical product-run bindings.

## Prerequisites and limits

Code declares Python >=3.9 with setuptools >=61 and no runtime dependencies; existing operation scripts use Python 3.11, Git and host CLIs. A disposable venv can install the source with `python -m pip install ./otto`, but installing the Python entrypoints is not a working owner-service enrollment. Fresh owner setup, agent authentication, model availability and OS/process facilities must be verified on the receiving machine before execution. Do not reuse old session/PID/socket/identity locators as live bindings.

The archive contains no account credentials, live Otto database, agent session stores, virtualenvs or caches. It preserves selected task/check evidence, not every raw transcript or generated staging tree. `selection.json` lists every selected and omitted portfolio path. `.DS_Store` and `.nothing` dirt was left untouched on the original machine. No product tests were rerun: this validates transfer integrity, not implementation correctness.

Pinned Otto/Megado/handover guidance is in `skills/`, hashed in `skills-provenance.json`; direct reading works without installation. Optional no-overwrite copy: `cp -R skills/otto /a/new/nonexistent/skill-path` (first confirm that destination does not exist). These local editions have no verified matching published upstream SHA; the exact vendored bytes are authoritative for this transfer.

Some source history already published on main contains synthetic probe transcripts/canaries and old absolute controller paths. No shared history was rewritten; these are historical fixtures, not account credentials. New handover prose replaces the original home prefix. Original private portfolio copies retain paths for provenance; scripts and recorded paths require relocation review before execution.
