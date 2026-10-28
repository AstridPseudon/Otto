1. **Verdict: FAIL.** At `c126587`, the model has a workable core, but saving can lose declared plan structure, overwrite a concurrent task edit, and admit a dependency cycle.

2. **Findings**

**F1 — A project revision does not fence the whole plan.**  
`save` supplies only the project’s base revision. Direct task revisions leave that project revision unchanged; the existing folder-authoring test explicitly demonstrates this. Consequently, a save can overwrite a newer task title while passing its stale-base check. Folder check-in already carries the missing task bases. Evidence: [save binding](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/herzchen_binding.py:2345), [existing regression scenario](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/fixtures/project_authoring.py:123), [task-base protection](${TRANSFER_ROOT}/source/otto/src/herzchen/domains/work/batches.py:295).

**Task:** give save and checkout the same revision contract. Check: read a plan, revise one task independently, then save the old plan; refuse it with the changed task identified and no writes.

**F2 — The saved shape cannot faithfully carry the declared end state.**

- `otto.plan.lines` is a positive integer, whereas TYPE requires a project-level repo→branch mapping. Separate `repo`/`branch` fields allow only one pair. Worse, `sheet_from_seed` silently drops project `metadata_namespace`, so project lines do not survive save. Evidence: [validator](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/plan_metadata.py:17), [seed mapping](${TRANSFER_ROOT}/source/otto/src/herzchen/domains/work/sheet.py:606).
- Save’s `criteria` become inert `work.template.criteria` metadata; they do not become the assessment criteria used for acceptance. Nonempty `documents` are explicitly refused. Thus “tasks with criteria and document briefs” requires another authoring route. Evidence: [criteria storage](${TRANSFER_ROOT}/source/otto/src/herzchen/domains/work/sheet.py:607), [document refusal](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/save.py:33), [actual assessment criterion creation](${TRANSFER_ROOT}/source/otto/src/herzchen/domains/assessment/module.py:287).
- All six follow-ups require `PROGRAM#edition-1`. Save accepts local task dependencies, drops project dependency fields, and strips a supplied task `kind`, turning a proposed gate into a task. The existing cross-project dependency mechanism is separate. Evidence: [save dependencies](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/save.py:63), [kind stripping](${TRANSFER_ROOT}/source/otto/src/herzchen/domains/work/sheet.py:591), [project/gate dependency port](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/dependencies.py:93).

**Task:** make the save format lossless for project lines, brief documents, assessment criteria and project prerequisites; reject unsupported fields instead of discarding them. Check these through the socket and compare canonical read-back, including two repositories and a cross-project gate. This closes A2/TYPE outcomes; it does not require another generic schema framework.

**F3 — Partial saves can introduce cycles through omitted tasks.**  
Start with `A → B`; save only `B → A`. Both cycle checks inspect submitted tasks only. Omitted A is retained, but its edge is absent from validation. Evidence: [parser’s partial graph](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/save.py:93), [retention](${TRANSFER_ROOT}/source/otto/src/herzchen/domains/work/batches.py:634), [batch cycle check](${TRANSFER_ROOT}/source/otto/src/herzchen/domains/work/batches.py:650).

**Task:** validate the resulting project graph, combining retained records with proposed changes. Check the two-save example above; the second save must fail without advancing any revision.

**F4 — A refused first save can leave an empty project behind.**  
`{"project":{"title":"X"},"tasks":[{"id":"A"}]}` passes the parser. The binding commits `create_pending` before applying the sheet; the missing task title then fails batch validation. The error response does not undo the project. Evidence: [creation before apply](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/herzchen_binding.py:2334), [required task title](${TRANSFER_ROOT}/source/otto/src/herzchen/domains/work/batches.py:875). I independently confirmed parser acceptance without opening a Store.

**Task:** make creation plus initial sheet application atomic. Check malformed task fields and invalid existing-reference inputs: no project, task, event or receipt residue.

**F5 — Every save carries an expanding copy of previous saves.**  
The project head appends every batch’s task mapping to `batch_history`, duplicates the latest entry in `last_batch`, and scans the accumulated mappings on subsequent saves. The same mappings already exist in events, which replay reads first. Evidence: [history scan](${TRANSFER_ROOT}/source/otto/src/herzchen/domains/work/batches.py:548), [nested history append](${TRANSFER_ROOT}/source/otto/src/herzchen/domains/work/batches.py:643), [event-backed replay](${TRANSFER_ROOT}/source/otto/src/herzchen/domains/work/batches.py:959).

For repeated fixed-size edits, current project payload size grows linearly with save count; cumulative scanning and serialization grow quadratically. This is separate from necessary immutable history.

**Task:** retain mappings in events and use stable aliases or a bounded alias index for lookup. Remove accumulated history from the mutable head. Check hundreds of single-task edits: head size stays bounded, old receipts replay correctly, aliases still resolve.

**F6 — The cold-agent edit loop is unfinished, and its conflict diff conceals important changes.**  
`diff_save` excludes dependencies and typed metadata, and never compares criteria. I independently exercised it with dependency, route and criteria changes: it returned an empty change list. Evidence: [excluded fields](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/save.py:19), [diff implementation](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/save.py:122).

The public interface also lacks an installed `otto` entry point; `open` is a document-session protocol requiring JSON references, handles and explicit request keys. `show` returns a projection rather than a save-shaped checkout. Evidence: [entry points](${TRANSFER_ROOT}/source/otto/pyproject.toml:12), [CLI arguments](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/cli.py:55), [show output](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/show.py:30).

**Command/file count:** there is no complete cold-shell journey using only the requested four verbs today. At the injected command surface, create→show→status→edit/save→stale save→show→reconciled save is **7 invocations**, with **1 manually maintained JSON file**, or **2 files** to retain two writers’ copies. The agent manually transfers revision references and reconstructs editable data. Editing an existing brief adds **3 session commands**—start, autosave, finish—and one checkout content file.

**Task:** extend A3FIX with an authenticated cold-shell round trip, automatic request keys, save-compatible checkout output and complete semantic diffs. Check a dependency-only and route-only conflict. A console entry point alone will not finish this journey.

**F7 — The perch passes without proving its principal claims.**  
The recorded read-back is `{"outcome":"unavailable"}`. The assertion checks returned reference shapes, not saved task contents or criteria; the revision assertion only checks that the project revision changed. Evidence: [failed read-back](${TRANSFER_ROOT}/source/otto/ops/perch/1/20261016T113140Z/raw/read-back.json:1), [assertions](${TRANSFER_ROOT}/source/otto/ops/bootstrap/perch_report.py:538).

The actual snapshots show:

| Operation | Allocated Store bytes added | Rows added |
|---|---:|---:|
| Create | 20,480 | 11 |
| Edit | 4,096 | 4 |
| Stale refusal | 0 | 0 |

These come from the [baseline](${TRANSFER_ROOT}/source/otto/ops/perch/1/20261016T113140Z/raw/store-before-saves.json:1), [create](${TRANSFER_ROOT}/source/otto/ops/perch/1/20261016T113140Z/raw/store-after-create.json:1), [edit](${TRANSFER_ROOT}/source/otto/ops/perch/1/20261016T113140Z/raw/store-after-edit.json:1) and [stale](${TRANSFER_ROOT}/source/otto/ops/perch/1/20261016T113140Z/raw/store-after-stale.json:1) snapshots. They do not establish excessive byte growth by themselves.

The report instead prints **163,840 bytes “per save”**: it includes startup allocation and divides by task-timeline events, here an assignment event. Its growth assertion merely bounds total row additions, missing growing JSON inside existing rows. Evidence: [calculation](${TRANSFER_ROOT}/source/otto/ops/bootstrap/perch_report.py:860), [row-only assertion](${TRANSFER_ROOT}/source/otto/ops/bootstrap/perch_report.py:588).

**Perch assertions:** failed read-back fails the stage; verify task payloads, assessment criteria and old revisions; report snapshot deltas per operation; add repeated-edit payload-size measurements and the F1–F4 scenarios.

**Source-of-truth inventory.** One Store does not yet mean one representation:

| Fact | Copies found |
|---|---|
| Task membership/order | Project `tasks` list; task `parent`/`project_ref`; task `order`. [Writer](${TRANSFER_ROOT}/source/otto/src/herzchen/domains/work/batches.py:603), [combined reader](${TRANSFER_ROOT}/source/otto/src/herzchen/domains/work/sheet.py:736). |
| Task identity mapping | Task aliases, `batch_history`, `last_batch`, event mapping, retained service `task_refs`. [Service cache](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/serve.py:116). |
| Completion status | Task lifecycle, `readiness.status`, completion data and completion observation. These are written together; I found duplication, not demonstrated drift. [Writer](${TRANSFER_ROOT}/source/otto/src/herzchen/domains/work/assignments.py:733). |
| Acceptance/check text | Task `acceptance`, activation’s `fields.acceptance`, assessment criterion definition, save’s inert template criteria. [Activation copies](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/reviewed_activation.py:417). Assessment should own executable acceptance. |
| Route/repository | Parsed tasklist, `custom.megado`, new `otto.plan`. The legacy status reader still reads Megado. [Registration](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/register.py:101), [reader](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/cli.py:518). |
| Documents | Run-directory originals, DAT revisions, sync digest baselines, generated run views, checkout content and session snapshots. [Sync](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/sync.py:47), [generated view](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/serve.py:153), [editor capture](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/document_editor_host.py:228). |
| Program progress | Hand-maintained tasklist statuses versus landed git history: A1/TYPE/A2/A3 still say “not started.” [Rows](${TRANSFER_ROOT}/portfolio/projects/program/tasklist.md:37), [recorded history](${TRANSFER_ROOT}/source/otto/ops/perch/1/20261016T113140Z/report.md:103). |

Store identities, event history, receipts and reference indexes have distinct purposes. Generated show/status/sheet projections are not additional authorities. A4/A6/CONV already address much of the legacy duplication; their checks should establish one-way views and retirement of old writers.

**Fit sketches.** These task skeletons fit today using `project.title`, task `id/title/dependencies`, and task `metadata_namespace.otto.plan.{route,size}`:

| Project | Example saved task |
|---|---|
| SLIM | `SL0`, “Baseline and deletion ledger”, normal, 0.5 |
| EFFECTS | `EF1`, “Effect ledger”, xhard, 1.5 |
| PACKS | `PK1`, “Pack layout and loader”, normal, 0.75 |
| HARNESS3 | `H31`, “Choose harness”, normal, 0.25 |
| THROUGHPUT | `TP1`, “Read runner report”, normal, 0.25 |
| ASTRIDFLEET | `AF1`, “Map Astrid agent flows”, normal, 1.0 |

These reflect the respective [project tasklists](${TRANSFER_ROOT}/portfolio/projects). All six still need the shared prerequisite, briefs and criteria from F2.

An Astrid film plan can similarly save `INPUTS → RENDER → REVIEW`, with prompts and shot lists as documents and render checks as assessment criteria; repo fields can be absent. The neutral work records fit, but the current save route cannot carry the documents and criteria faithfully.

A superseded project needs a terminal retirement plus reason and successor reference—for example, old film plan → replacement film plan. Current withdrawal only changes lifecycle. RETIRE already specifies the appropriate general solution; do not encode this as a fake completion or prose-only status. [Withdrawal](${TRANSFER_ROOT}/source/otto/src/herzchen/domains/work/batches.py:866), [RETIRE requirement](${TRANSFER_ROOT}/portfolio/projects/program/tasklist.md:42).

3. **Sound**

- The neutral work graph plus Otto-owned metadata hook is the right layer boundary; no additional framework is needed. [Hook](${TRANSFER_ROOT}/source/otto/src/herzchen/domains/work/module.py:109).
- Batch replay consults the existing receipt before stale validation. [Replay](${TRANSFER_ROOT}/source/otto/src/herzchen/domains/work/batches.py:147).
- Omitted tasks are retained, and unchanged child payloads do not receive artificial revisions. [Retention/no-op handling](${TRANSFER_ROOT}/source/otto/src/herzchen/domains/work/batches.py:634).
- The recorded stale-save scenario added no rows or allocated pages; the saved scenario launched no workers.
- Existing folder authoring already supplies machinery that save should reuse.

4. **Not checked**

No live Store, staging lifecycle operation, Otto command or mutating test was run. Findings are based on source, existing perch artifacts and an in-memory parser/mapping/diff check. Runtime race reproduction, backward-reader compatibility and exhaustive table liveness remain unverified. STAGE1.md was not read.

5. **Delete list**

- Growing project `batch_history` and redundant `last_batch` replay fallback, after preserving alias lookup through the existing canonical mechanisms.
- Integer `otto.plan.lines`; replace it with the required project mapping.
- Inert `work.template.criteria` as a second acceptance representation, once save creates canonical assessment criteria.
- Legacy task-table parsing, Megado route copies, sync baselines and document mirror writers through A4/CONV/A6.
- Project payload `gate: None`: initialized but no consumer found. `external_action: None` has only an observed-view passthrough; remove that unused placeholder too. [Defaults](${TRANSFER_ROOT}/source/otto/src/herzchen/domains/work/batches.py:924), [projection](${TRANSFER_ROOT}/source/otto/src/herzchen/domains/work/sheet.py:769).
- Hand-maintained progress cells once generated status replaces them. Keep canonical history, receipts and recoverable authoring snapshots.

6. **Helpers**

**3 `gpt-6-luna` helpers:** schema/duplication/applicability; cold-agent save/edit/conflict paths; perch growth and persistence. I checked the cited implementation and raw evidence, including correcting the helper’s interpretation of the report’s byte denominator.