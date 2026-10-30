## 1. Model and limits

**There are two related editing paths.** `open <step>` edits one canonical document using the editor host; `open folder <step>` checks out a project’s `project.json` plus all its `project.files` documents. The folder path is the closer match for a spec-folder workflow. [cli.py:107–141](../otto/otto/src/otto/portfolio/cli.py:107)

A **document** has a stable identity and metadata: role, visibility, access mode, maintainer, optional authoring scope, import mode, and writable flag. A **revision** is immutable JSON-safe content attached to that identity, with author, optional parent revision, and a SHA-256 digest of canonical JSON content. [model.py:93–129](../otto/otto/src/herzchen/content/model.py:93) [model.py:157–188](../otto/otto/src/herzchen/content/model.py:157)

For project folders, the store links each relative path to a document through a `project.files` association. Checkout reads those associations and current revisions, then records the document ref, revision ref, digest, and association ref as the base for each path. The folder path requires target-owned, writable documents and current, unique memberships. [project_folder.py:167–196](../otto/otto/src/otto/portfolio/project_folder.py:167)

**Checkout** reserves an owner-side authoring session and materializes the files. In the folder CLI, `start` requires a destination directory that does not already exist; it writes `project.json` and the document files there and returns a session ID. [cli.py:1388–1398](../otto/otto/src/otto/portfolio/cli.py:1388) [project_folder.py:198–218](../otto/otto/src/otto/portfolio/project_folder.py:198)

**Check-in/save** has two meanings:

- Folder `finish` compares the local folder with a fresh export, submits only changed files as explicit `add`/`edit` actions, and checks in the semantic `project.json` fields. The CLI currently refuses removed files; the owner API’s lower-level action model also supports `move` and `unlink`. [cli.py:1399–1414](../otto/otto/src/otto/portfolio/cli.py:1399) [project_folder.py:322–361](../otto/otto/src/otto/portfolio/project_folder.py:322)
- Single-document `autosave` stores an editor-buffer draft snapshot; it does **not** publish a document revision. `finish` publishes through the document authoring handler. [show.py:8–14](../otto/otto/src/otto/portfolio/show.py:8) [authoring.py:648–665](../otto/otto/src/herzchen/content/authoring.py:648)

**Staleness and conflict:** Folder check-in verifies the retained session/actor, current EDT custody, and project/task bases before effects. A stale project/task base returns `conflict` / `stale_base`; document appends also use the frozen base revision as their expected revision, so a race after the pre-check is rejected by the append. [project_folder.py:271–302](../otto/otto/src/otto/portfolio/project_folder.py:271) [project_folder.py:433–453](../otto/otto/src/otto/portfolio/project_folder.py:433) The single-document CLI checks the current revision against the handle’s base before finishing; when stale, it returns `conflict` / `stale_base`, says no revision advanced, and keeps the session open. [show.py:66–85](../otto/otto/src/otto/portfolio/show.py:66) Herzchen also checks that the supplied expected base matches the checkout base. [sessions.py:1295–1300](../otto/otto/src/herzchen/authoring/sessions.py:1295)

**`otto_newer`:** that label does not appear in the inspected canonical source. **Inference:** it describes an older three-way sync result, not the current folder check-in status; current code reports `conflict` / `stale_base`, while retained SLIM docs describe historical `sync-docs` as using three-way digest checks to avoid overwriting Otto-side edits. [one-otto-friction.md:37](../otto/projects/slim/docs/one-otto-friction.md:37) [OTTO-ONE.md:383](../otto/projects/slim/OTTO-ONE.md:383)

**Bytes, hashes, metadata, bounds:** Folder documents must be UTF-8 text, at most 10 MiB each. One import/check-in operation is bounded at 1,000 files and 256 MiB; the whole checked-out tree has sanity limits of 100,000 files and 2 GiB. There is no explicit maximum path depth in `document_path`; it rejects unsafe components such as empty, `.` and `..`. [project_folder.py:17–32](../otto/otto/src/otto/portfolio/project_folder.py:17) [project_folder.py:47–78](../otto/otto/src/otto/portfolio/project_folder.py:47) Reads cap a revision-history page at 100 revisions. [documents.py:18–19](../otto/otto/src/otto/portfolio/documents.py:18) Snapshot manifests retain per-file relative path, byte size, and SHA-256; snapshots contain exact file bytes. [snapshots.py:61–97](../otto/otto/src/herzchen/authoring/snapshots.py:61) [snapshots.py:100–137](../otto/otto/src/herzchen/authoring/snapshots.py:100)

## 2. Commands and example flow

For a folder checkout:

```sh
otto open folder start --project-ref "$PROJECT" --actor manager \
  --request-key open-1 --directory ./projects/luna
# edit ./projects/luna/brief.md and project.json
otto open folder finish --project-ref "$PROJECT" --actor manager \
  --request-key finish-1 --session-id "$SESSION" --directory ./projects/luna
otto show project --project-ref "$PROJECT" --actor manager
```

`open folder start` checks out and writes the projection; `finish` exports a baseline, computes changed-file actions, and checks in through the project API. `show project` reads the project and task rows; it is read-only. [cli.py:126–141](../otto/otto/src/otto/portfolio/cli.py:126) [cli.py:1388–1414](../otto/otto/src/otto/portfolio/cli.py:1388) [show.py:32–63](../otto/otto/src/otto/portfolio/show.py:32)

Other requested verbs are not all document sync verbs: top-level `save FILE` saves a project from a JSON save-file shape; `retire REF` retires a work record; `release` frees a parked authoring session without publishing. [cli.py:80–91](../otto/otto/src/otto/portfolio/cli.py:80) [cli.py:1215–1237](../otto/otto/src/otto/portfolio/cli.py:1215) [cli.py:1421–1434](../otto/otto/src/otto/portfolio/cli.py:1421)

For a single document, `open start` returns an owner-issued handle; `open autosave` stores a draft; `open finish` checks in; `open release` closes without publishing. A stale finish leaves the session open, so the user can release and reopen. [cli.py:107–125](../otto/otto/src/otto/portfolio/cli.py:107) [show.py:88–106](../otto/otto/src/otto/portfolio/show.py:88)

## 3. Dependencies and extraction

This is not currently a standalone SQLite module. `ProjectDocumentReader` takes ProjectSheet, DAT content, and visibility-policy readers; it explicitly does not open a Store. [documents.py:87–99](../otto/otto/src/otto/portfolio/documents.py:87) Folder writing is a `ProjectFolderOwner` bridge over owner ports, with DAT document creation/linking and EDT session state. [project_folder.py:128–165](../otto/otto/src/otto/portfolio/project_folder.py:128) [project_folder.py:271–302](../otto/otto/src/otto/portfolio/project_folder.py:271)

The owner bootstrap requires the trusted Herzchen `Store`, binds the authenticated actor to its authority, and constructs the owner facades. [owner_bootstrap.py:603–695](../otto/otto/src/otto/portfolio/owner_bootstrap.py:603) `DocumentEditorHost` also uses that owner’s store and EDT service, plus a local writer-lease authority and editor checkout directory. [document_editor_host.py:39–90](../otto/otto/src/otto/portfolio/document_editor_host.py:39) In deployed host flow, manager commands use an owner caller socket with peer-PID ancestry authentication; that is a host boundary, not necessary for local SQLite calls. [serve.py:10–18](../otto/otto/src/otto/hostctl/serve.py:10)

**Yes, the useful semantics can be extracted over plain SQLite, but not by lifting these modules intact.** A slim implementation could model documents, revisions, checkouts, and associations directly in the proposed database, use a transaction plus base-revision comparison for check-in, and retain content digests and project/path metadata. **Inference / rough estimate:** about **250–450 lines** for the basic folder and revision workflow, excluding CLI and schema; perhaps **400–700 lines total** including persistence and commands.

Relevant current source sizes: `project_folder.py` 539 lines, `documents.py` 546, `document_navigation.py` 1,103, `show.py` 106, `cli.py` 1,774, `sessions.py` 1,915, `snapshots.py` 386, `writer_lease.py` 572, and `content/authoring.py` 1,060. The three named tests are 128, 159, and 154 lines. **Inference:** implementing only the desired SQLite spec-folder flow does not require porting most of those files. Cut owner command envelopes/receipts, `ResourceRef` authority model, visibility and role/scope resolution, EDT token/fence custody, recovery inventory, writer leases, Store domain handlers, and host socket plumbing.

## 4. Deletion and sync history

Current SLIM guidance says there is **no `project sync-docs` command** and that `portfolio apply` does not sync existing project documents or root-level shared docs. The historical portfolio spec says its sync-docs examples were not retained by the current parser. [SKILL.md:29](../otto/projects/slim/policy-staging/megado/skill/SKILL.md:29) [portfolio-spec.md:7–9](../otto/projects/slim/docs/portfolio-spec.md:7)

`portfolio_apply.py` reads a declared root and project bundles for applying portfolio setup; this is onboarding/metadata reconciliation rather than ongoing document synchronization. [portfolio_apply.py:59–88](../otto/otto/src/otto/hostctl/portfolio_apply.py:59)

There is no `otto/hostctl/sync.py` in the inspected canon file set. `otto/portfolio/resource_sync.py` exists, but its docstring describes role-scoped instructional-resource validation, not project-file synchronization. [resource_sync.py:1–9](../otto/otto/src/otto/portfolio/resource_sync.py:1) **I could not verify a specific “SLIM A6 document mirror” deletion item in the requested Markdown sources.** The evidence I did find establishes that older `sync-docs` material remains in historical docs while the current parser/guidance omits that command.

## 5. Recommendation

**Rewrite small, porting semantics selectively.** Reuse the concepts of stable document identity, immutable revisions with parent and digest, path-to-document association, explicit changed-file actions, and stale-base conflict. Do not reuse the owner/session architecture: it exists to protect a multi-domain authority system that the minimal design deliberately removes. A reasonable target is **roughly 300–500 lines for the SQLite-backed document/check-out/check-in core**, plus schema/CLI integration; keep the full task/task-list behavior in the six-table design rather than importing Otto’s broader document-navigation subsystem. [12-minimal-design.md:27–45](../retro/12-minimal-design.md:27) [12-minimal-design.md:65](../retro/12-minimal-design.md:65)