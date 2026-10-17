# Otto portfolios

An Otto portfolio is a set of supervised projects with shared reference
documents, entry dependencies, and one accountable orchestrator. Project
readiness is separate from project activation: registering or becoming ready
does not create live manager work or dispatch tasks.

## Set up the timeline portfolio

The r4 root is described by `portfolio-setup.json`. Its ten projects use IDs
A–J for setup and evidence commands, while their canonical project run IDs are
`timeline-platform-r4-A-integration` through
`timeline-platform-r4-J-extensions`. The manifest declares each project’s
entry milestones and the gates that accept those milestones. Project folders
are imported whole, including nested briefs, archive material, and reviews.
Root files outside `projects/` become shared portfolio documents.

Preview first, then apply through the host’s admitted portfolio:

```sh
ottoctl portfolio apply --root /path/to/timeline-platform-r4 --dry-run
ottoctl portfolio apply --root /path/to/timeline-platform-r4 \
  --import-history /path/to/timeline-platform-r3
```

From the service home’s owner lane, select the admitted portfolio explicitly:

```sh
ottoctl --home "$SERVICE_HOME" portfolio apply \
  --portfolio claude-code-portfolio \
  --root /path/to/timeline-platform-r4 --dry-run
ottoctl --home "$SERVICE_HOME" portfolio apply \
  --portfolio claude-code-portfolio \
  --root /path/to/timeline-platform-r4 \
  --import-history /path/to/timeline-platform-r3
```

The optional history import records the closed r3 bundle as withdrawn history;
it does not enroll it as an active r4 project. A dry run reports planned
registration, document sync, gates, dependencies, and readiness without Store
writes. Repeating apply after a successful run should report `in_sync`. If a
source document conflicts with an Otto edit, apply reports the conflict and
holds before changing project or dependency state. Review the retained Otto
version and source before reconciling it.

Apply creates pending project drafts. It preserves per-role model and adapter
assignments, pending gates, finite oracle/review allowance limits, and source
documents. Scheduled checks remain paused; apply creates no Due records, role
occurrences, or dispatch. Those remain inactive until explicit activation.
The default manager-turn limit is three; excess manager turns queue and appear
in service status. `service run --max-active-manager-turns N` (N from 1 to 3)
sets the limit, and `service status` reports active and queued turns. The
service can attach one project at startup with `service run --project RUN_ID`;
otherwise it attaches a project on first manager use. Drain an idle project
with `service drain --project RUN_ID`; a later explicit, project-scoped manager
command attaches its lanes again.

The source keeps Codex model declarations as Codex adapter bindings in draft
configuration; they are not rewritten as Claude models. This host’s current
qualified runtime supports Claude managers. Activating a project that requires
an adapter with no trusted factory returns `role_adapter_unavailable` before
materialization. Codex model declarations are therefore preserved, while
Codex manager execution still needs trusted host-adapter wiring and admission.

No live/shared Store setup is performed by this guide. The source r4 tree is
read as input; apply should first be proven against a disposable Store. The
authenticated two-manager proof is
`tests/portfolio_concurrent_proof.py --run`; it is explicitly
**needs-unsandboxed** because it binds caller Unix sockets and exercises the
native process fence. Its default invocation is inert. Run the proof only in
an environment that permits those operations.

## Readiness and gates

Check the current portfolio and one project’s blockers with:

```sh
ottoctl portfolio status --json
ottoctl project dependencies --project timeline-platform-r4-B-preservation
```

The owner lane requires an explicit portfolio selection:

```sh
ottoctl --home "$SERVICE_HOME" portfolio status \
  --portfolio claude-code-portfolio --json
```

The project entry graph is:

| Project | Entry milestone prerequisites |
|---|---|
| A | Codex port prerequisite (external gate) |
| B | A#spec0 |
| C | A#spec0, A#contracts-v1 |
| D | A#spec0, B#compat |
| E | A#contracts-v1, D#identities, D#commit-service |
| F | A#spec0 |
| G | A#spec0 |
| H | A#spec0, plus the transport-choice external gate |
| I | F#compiler, F#cuts, A#golden-baseline |
| J | D#commands, G#evaluator-film |

These links determine project-level readiness and are the only
card-independent dependencies that apply installs as project graph edges.
The manifest is the source of truth.

Second, task/card dependencies remain task policy. The importer preserves
`run.json` `card_dependencies` and tasklist dependency text on each task,
including `A#milestone` and user-owned prerequisites. They do not create
project-level graph edges or project cycles; the owning project’s manager
coordinates them against the corresponding work and evidence.

Third, external prerequisites are gates within their owning project. The
manifest currently leaves Codex’s published port pending for A, the hosted
transport decision pending for H, and the ownership ruling pending for C and
E. A’s `spec0` and `contracts-v1` are distinct acceptance gates; completing
the Codex port prerequisite does not complete either one. Until external
evidence and the required entry gates are accepted, readiness reports the
corresponding blockers.

Complete an external prerequisite or ordinary milestone only after reviewing
its evidence against the manifest’s declared proof path. Supply a concise
evidence reference or acceptance note; Otto stores it with the gate completion
and does not independently judge the supplied evidence:

```sh
ottoctl portfolio prerequisite complete --project A \
  --id codex-port-published \
  --evidence 'Published astrid-union-port; FINAL-E2E stage 2 passed: <receipt>'
ottoctl portfolio gate complete --project A --gate spec0 \
  --evidence 'SPEC-0 checklist and review accepted: <evidence reference>'
ottoctl portfolio gate complete --project A --gate contracts-v1 \
  --evidence 'Contracts v1 frozen and producer/consumer review accepted: <reference>'
```

Use the same owner-lane form with `--portfolio claude-code-portfolio` when
operating from the service home. External gates are completed with
`prerequisite complete`; the command verifies that the requested ID is the
external prerequisite declared on that gate. Ordinary milestones use
`gate complete`. Gate lifecycle `completed` is the readiness signal.

Once dependencies are ready, activation remains explicit and still performs
adapter and native-runtime checks:

```sh
ottoctl project activate --project timeline-platform-r4-B-preservation
```

Activation refuses blocked work by default. A justified exception can be
recorded with `--override-readiness --reason '...'`; status continues to show
the unmet dependencies and the retained override reason. Remove a project
entry dependency with `ottoctl project depend --project RUN_ID --on
UPSTREAM_RUN_ID#GATE --remove`. Apply manages only the entry edges recorded in
its previous manifest snapshot; hand-authored edges remain separate.

## Shared documents and project lifecycle

Apply reconciles all root files outside `projects/` as shared documents. The
parser exposes these read routes:

```sh
ottoctl portfolio documents --operation list
ottoctl portfolio documents --operation read --path portfolio.md
ottoctl manager project-documents --operation list
ottoctl manager project-documents --operation read --path portfolio/portfolio.md
```

`portfolio apply --root DIR` accepts the root's shared documents and reports
conflicts without overwriting Otto edits. Newly attached projects receive
shared-document associations through portfolio apply. There is no separate
`sync-docs` command. The portfolio documents command is read-only; use apply
to reconcile files from a registered portfolio root.
Managers and workers can read shared documents through their project-bound
document view. The `portfolio/` prefix distinguishes shared files from
project-local paths. Only the current portfolio orchestrator or owner can
apply a portfolio root.

Detach retains a project while removing its supervision and shared-document
links. It refuses active or queued manager work. A dependent project is then
blocked if its entry prerequisite was detached; reapplying the portfolio can
reattach the same project without creating a duplicate.
