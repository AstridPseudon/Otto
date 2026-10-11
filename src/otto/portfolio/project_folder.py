"""Bounded project files over WRK sheets, EDT checkout state and DAT receipts.

Files are explicit UTF-8 inputs. No crawl, watcher, new store, activation or
transfer provenance is inferred. Each DAT operation commits separately; the
immutable intent and stable child receipts permit exact partial recovery.
"""
from __future__ import annotations

from hashlib import sha256
from typing import Any, Mapping

from herzchen.content import ContentDocument, ContentRevision, DocumentAssociation
from herzchen.content.model import CONTENT_SCHEMA_REVISION, PROJECT_FILES_NAMESPACE, document_path
from herzchen.contracts import (ReferenceBinding, ResourceRef, TransactionContext,
                               canonical_json, canonical_request_digest)

# A project's folder has no product limit. Bounds apply to ONE file and to
# ONE operation (what a single import, check-in or transfer carries); larger
# work is split across operations, each with its exact partial recovery.
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_OPERATION_FILES = 1000
MAX_OPERATION_BYTES = 256 * 1024 * 1024
# A checkout materializes every file, so a whole tree is refused only when it
# is pathological. This is a sanity bound, not a project size limit.
MAX_PROJECT_FILES = 100_000
MAX_PROJECT_BYTES = 2 * 1024 * 1024 * 1024

MAX_FILES = MAX_OPERATION_FILES
MAX_TREE_BYTES = MAX_OPERATION_BYTES
# Observed live ingress bound for the maintained authoring route. This is
# intentionally separate from the source/package validation limits above.
MEASURED_LIVE_REQUEST_BYTES = 16 * 1024


class FolderTransportError(ValueError):
    """A pre-effect rejection with its measured transport evidence attached."""

    def __init__(self, message: str, preflight: Mapping[str, Any]) -> None:
        super().__init__(message)
        self.preflight = dict(preflight)


def _identity(ref: ResourceRef) -> ResourceRef:
    return ResourceRef(ref.authority, ref.kind, ref.id)


def validate_files(files: Mapping[str, str], *, max_files: int = MAX_PROJECT_FILES,
                   max_bytes: int = MAX_PROJECT_BYTES) -> dict[str, str]:
    """Portable paths and UTF-8 text; the defaults bound a whole tree (sanity only).

    Callers validating what one operation carries pass the operation bounds.
    """
    if not isinstance(files, Mapping) or len(files) > max_files:
        raise ValueError("files must be a bounded path-to-UTF-8-text object")
    paths = {}
    total = 0
    for path, text in sorted(files.items()):
        document_path(path)
        if path.casefold() == "project.json" or path.split('/')[0].casefold() == '.otto':
            raise ValueError("document path collides with the project projection")
        if not isinstance(text, str):
            raise ValueError("folder documents must be UTF-8 text")
        size = len(text.encode('utf-8'))
        if size > MAX_FILE_BYTES:
            raise ValueError("document exceeds the text size bound")
        total += size
        parts = path.split('/')
        for index in range(1, len(parts) + 1):
            prefix = '/'.join(parts[:index])
            folded = prefix.casefold()
            previous = paths.get(folded)
            entry = (prefix, index == len(parts))
            if previous is not None and (previous != entry or entry[1]):
                raise ValueError("ambiguous or conflicting portable file paths")
            paths[folded] = entry
    if total > max_bytes:
        raise ValueError("document tree exceeds the byte bound")
    return dict(sorted(files.items()))


def folder_transport_preflight(project_json: Mapping[str, Any], files: Mapping[str, str],
                                request_id: str, *, request_limit: int = MEASURED_LIVE_REQUEST_BYTES) -> dict[str, Any]:
    """Measure supported JSON request shapes before the first effect.

    The raw import endpoint accepts a whole folder for compatibility, while
    the actual document effects are already committed one child at a time by
    ``_folder_apply``. The aggregate request may exceed the observed ingress
    bound, but every child request must fit it.
    """
    if type(request_limit) is not int or not MEASURED_LIVE_REQUEST_BYTES <= request_limit <= MAX_OPERATION_BYTES:
        raise ValueError("owner transport request limit is outside the qualified bounds")
    def size(value: Mapping[str, Any]) -> int:
        return len(canonical_json(value).encode("utf-8"))

    envelope = {"command": "project-authoring", "operation": "import-folder",
                "request_key": request_id, "project_json": dict(project_json), "files": dict(files)}
    children = []
    for index, (path, text) in enumerate(sorted(files.items())):
        child = {"operation": "dat.content.document.create",
                 "request_key": f"{request_id}:document:{index}:create",
                 "path": path, "content": text}
        child_size = size(child)
        children.append({"path": path, "bytes": child_size,
                         "fits": child_size <= request_limit})
    oversized = [item["path"] for item in children if not item["fits"]]
    envelope_size = size(envelope)
    return {
        "schema": "otto.folder-transport-preflight.v1",
        "measurement": "canonical UTF-8 JSON request envelope",
        "measured_request_bytes": envelope_size,
        "measured_request_limit": request_limit,
        "legacy_observed_request_limit": MEASURED_LIVE_REQUEST_BYTES,
        "aggregate_fits": envelope_size <= request_limit,
        "composition": "bounded-child-requests" if envelope_size > request_limit else "single-envelope",
        "children": children,
        "source_limits": {"max_files": MAX_FILES, "max_file_bytes": MAX_FILE_BYTES,
                           "max_tree_bytes": MAX_TREE_BYTES},
        "recovery": {"request_key": request_id,
                      "resume": "exact input and request key; inspect retained child receipts"},
        "oversized_children": oversized,
    }

def validate_operation_files(files: Mapping[str, str]) -> dict[str, str]:
    """What ONE import or onboarding operation may carry; split larger inputs."""
    return validate_files(files, max_files=MAX_OPERATION_FILES, max_bytes=MAX_OPERATION_BYTES)


class ProjectFolderOwner:
    """Owner bridge mixin; uses only the already composed public domain ports."""

    def _folder_context(self, operation, target, actor, key, payload, base=None, new=False):
        context = TransactionContext(actor, key, '0' * 64, expected_revision=base,
                                     expected_version=0 if new else None)
        digest = canonical_request_digest(logical_request_key=key, operation=operation,
            schema_revision=CONTENT_SCHEMA_REVISION, target=target, actor=actor,
            payload=payload, context=context)
        return TransactionContext(actor, key, digest, expected_revision=base, expected_version=0 if new else None)

    def _folder_create(self, project, actor, key, content, role='supporting'):
        # Identity comes from the operation, independently of any path/content.
        ref = ResourceRef(self.authority, 'dat.content.document',
            'folder-' + sha256((self.authority + ':' + key).encode()).hexdigest()[:28])
        document = ContentDocument(ref, role, 'private', 'write', actor.actor,
                                   authoring_scope=_identity(project))
        revision = ContentRevision(ref, 'rev-1', content, actor, initial=True)
        payload = {'document': document, 'revision': revision}
        context = self._folder_context('dat.content.document.create', ref, actor, key, payload)
        receipt = self.content.execute(self.content.build_create_document(context, document, revision))
        return ref, receipt

    def _folder_link(self, project, document, path, actor, key, *, unlink=False, base=None):
        association = DocumentAssociation(_identity(project), PROJECT_FILES_NAMESPACE, path,
                                          ReferenceBinding(_identity(document), 'current'))
        target = ResourceRef(self.authority, 'document-association', association.identity)
        payload = {'association': association, 'active': not unlink}
        operation = 'dat.content.unlink' if unlink else 'dat.content.link'
        context = self._folder_context(operation, target, actor, key, payload, base, new=not unlink and base is None)
        envelope = (self.content.build_unlink if unlink else self.content.build_link)(context, association)
        return self.content.execute(envelope)

    def _folder_tree(self, project, actor):
        from .documents import ProjectDocumentReader
        packets = self.folder_visibility
        reader = ProjectDocumentReader(sheet_reader=self.sheet, content_reader=self.content,
                                       visibility_reader=packets)
        listed = reader.list_documents(project, actor=actor)
        if listed['outcome'] != 'listed':
            raise ValueError('project documents are unavailable')
        files, bases = {}, {}
        for item in listed['documents']:
            members = [member for member in item['memberships']
                       if member['namespace'] == PROJECT_FILES_NAMESPACE
                       and member['subject_kind'] == 'project']
            if not members:
                continue
            read = reader.read_document(project, item['document_ref'], actor=actor, listed=listed)
            if read['outcome'] != 'read' or not isinstance(read['content'], str):
                raise ValueError('folder document is not available UTF-8 text')
            if (item['document'].get('import_mode') != 'owned'
                    or not item['document'].get('writable')):
                raise ValueError('folder checkout requires target-owned writable documents')
            for member in members:
                path = member['key']
                if path in files or member['binding']['mode'] != 'current':
                    raise ValueError('folder paths require unique current memberships')
                files[path] = read['content']
                bases[path] = {'document_ref': item['document_ref'],
                    'revision_ref': read['revision_ref'], 'content_digest': read['content_digest'],
                    'association_ref': member['association_ref']}
        return validate_files(files), bases

    def _folder_materialize(self, result, files):
        root = result.get('path', result.get('checkout_path'))
        if not root or not files:
            return result
        # The existing snapshot boundary authenticates regular files/root and
        # rejects symlinks/extras. Refuse any existing path before writing.
        from herzchen.authoring.snapshots import capture_tree, _root_path
        root = _root_path(root)
        capture_tree(root, result.get('registered_files', ['project.json']))
        for path, text in files.items():
            destination = root / path
            for parent in reversed(destination.parents):
                if parent == root or root in parent.parents:
                    if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
                        raise ValueError('unsafe checkout directory')
                    parent.mkdir(exist_ok=True)
            with destination.open('x', encoding='utf-8', newline='') as stream:
                stream.write(text)
        registered = ['project.json', *files]
        capture_tree(root, registered)
        return {**result, 'registered_files': registered}

    def export_project_folder(self, *, project_ref, actor, request_id):
        ref = ResourceRef.from_dict(project_ref) if isinstance(project_ref, Mapping) else project_ref
        if ref.authority != self.authority or ref.kind != 'work.project':
            raise ValueError('folder export requires an owner-local project')
        state = self._project_draft(ref, request_id, actor=actor)
        return {'outcome': 'exported', 'schema': 'otto.raw-project-folder.v1',
                'project_json': state['project_json'], 'files': state['document_files'],
                'provenance': {'mode': 'raw-folder', 'canonical_transfer': False},
                'read_only': True, 'execution': False, 'dispatch': False}

    def import_project_folder(self, *, project_json, files, actor, request_id):
        files = validate_operation_files(files)
        edit = self._json_mapping(project_json, 'project_json')
        # The normal sheet validator rejects authority and observation fields.
        # Pending import is intentionally restricted to the inert author fields.
        if set(edit) - {'title', 'outcome', 'scope', 'approach', 'acceptance', 'custom', 'protocol', 'tasks'}:
            raise ValueError('raw folder import accepts inert project author fields only')
        if edit.get('tasks'):
            raise ValueError('raw folder task adoption requires canonical transfer; author tasks after import')
        edit.pop('tasks', None)
        if not isinstance(edit.get('title'), str) or not edit['title'].strip():
            raise ValueError('raw folder import requires title')
        edit = self.sheet.validate_edit(edit)
        edit.pop('tasks', None)
        transport = folder_transport_preflight(edit, files, request_id,
            request_limit=getattr(self, "folder_transport_request_bytes", MEASURED_LIVE_REQUEST_BYTES))
        if transport['oversized_children']:
            paths = ', '.join(transport['oversized_children'])
            raise FolderTransportError(
                'document exceeds the measured live request limit of '
                f"{transport['measured_request_limit']} bytes before creation: {paths}", transport
            )
        digest = sha256(canonical_json({'project_json': edit, 'files': files}).encode()).hexdigest()
        created = self.sheet.create_pending(title=edit['title'], outcome=edit.get('outcome', ''),
            metadata={'raw_folder': {'input_sha256': digest, 'canonical_transfer': False}},
            actor=actor, logical_request_key=request_id + ':project')
        ref = created.receipt.result_ref
        # Remaining fields still use the shared sheet path, before documents.
        if set(edit) - {'title', 'outcome'}:
            applied = self.sheet.apply(ref, edit, actor=actor, base_revision=ref.revision,
                                       logical_request_key=request_id + ':sheet')
            ref = applied.receipt.result_ref
        changes = [{'operation': 'add', 'path': path, 'content': text} for path, text in files.items()]
        result = self._folder_apply(ref, {}, changes, actor, request_id,
            intent={'schema': 'otto.raw-folder-import.v1', 'project_json': edit, 'files': files},
            complete=lambda: {'outcome': 'imported', 'project_ref': ref.to_dict()})
        result['transport'] = transport
        return result

    def finish_project_folder(self, *, project_ref, session_id, project_json, document_changes,
                              actor, request_id):
        from herzchen.contracts import AuthoringCheckout
        ref = ResourceRef.from_dict(project_ref) if isinstance(project_ref, Mapping) else project_ref
        record = self.reader.get_identity(ResourceRef(self.authority, 'authoring-scope', ref.id))
        state = None if record is None else record.payload.get('project')
        if not isinstance(state, Mapping) or state.get('ref') != ref.to_dict():
            raise PermissionError('folder check-in requires the retained checkout')
        checkout = AuthoringCheckout.from_dict(record.payload['checkout'])
        if checkout.actor != actor or checkout.session_id != session_id:
            raise PermissionError('folder check-in actor/session mismatch')
        changes = self._folder_changes(state, document_changes)
        intent = {'schema': 'otto.project-folder-check-in.v1', 'session_id': session_id,
            'project_ref': ref.to_dict(), 'project_json': project_json, 'changes': changes}
        # Require current EDT custody and project/task bases before first effect.
        # After a completed finish, exact replay is governed by its receipts.
        if self.reader.get_receipt(request_id + ':finish') is None:
            from herzchen.authoring.sessions import SessionHandle
            handle = SessionHandle(ResourceRef(self.authority, 'authoring-scope', ref.id),
                checkout.target_scope, checkout.target_kind, actor, session_id, checkout.token,
                checkout.fence, checkout.base_revision, record.payload.get('checkout_path'))
            self.authoring.authorize_mutation(handle, checkout.target_scope,
                token=handle.token, fence=handle.fence, expected_base_revision=handle.base_revision)
            current = self._project_draft(ref, request_id, actor=actor)
            if current['ref'] != state['ref'] or current['base_task_revisions'] != state['base_task_revisions']:
                return {'outcome': 'conflict', 'error': {'code': 'stale_base'},
                        'committed': [], 'pending': changes, 'atomic': False}
            self.sheet.batches.validate_project_sheet(ref, self.sheet.validate_edit(project_json))
        return self._folder_apply(ref, state.get('document_bases', {}), changes, actor, request_id,
            intent=intent, complete=lambda: self.finish_project_sheet(project_ref=ref,
                session_id=session_id, project_json=project_json, actor=actor,
                request_id=request_id + ':finish'))

    def release_project_folder(self, *, project_ref, session_id, actor, request_id):
        """Release a conflicted checkout via EDT; preserve its files/history."""
        from herzchen.contracts import AuthoringCheckout
        from herzchen.authoring.sessions import SessionHandle
        ref = ResourceRef.from_dict(project_ref) if isinstance(project_ref, Mapping) else project_ref
        if ref.authority != self.authority or ref.kind != 'work.project':
            raise ValueError('release requires an owner project')
        scope = ResourceRef(self.authority, 'authoring-scope', ref.id)
        record = self.reader.get_identity(scope)
        checkout = AuthoringCheckout.from_dict(record.payload['checkout'])
        if checkout.actor != actor or checkout.session_id != session_id:
            raise PermissionError('release actor/session mismatch')
        handle = SessionHandle(scope, checkout.target_scope, checkout.target_kind, actor,
            session_id, checkout.token, checkout.fence, checkout.base_revision, record.payload.get('checkout_path'))
        result = self.authoring.release(handle, request_id=request_id)
        return {'outcome': result.status, 'session_id': session_id, 'receipt': result.receipt.to_dict(),
                'files_preserved': True, 'execution': False, 'dispatch': False}

    def _folder_changes(self, state, raw):
        if not isinstance(raw, (list, tuple)) or len(raw) > MAX_OPERATION_FILES:
            raise ValueError('document_changes must be a bounded explicit action list; '
                             'split larger change sets across check-ins')
        carried = sum(len(change.get('content', '').encode('utf-8')) for change in raw
                      if isinstance(change, Mapping) and isinstance(change.get('content'), str))
        if carried > MAX_OPERATION_BYTES:
            raise ValueError('document_changes carry more text than one check-in may; split them')
        files = dict(state.get('document_files', {}))
        seen = set()
        changes = []
        for value in raw:
            if not isinstance(value, Mapping):
                raise ValueError('document change must be an object')
            change = dict(value)
            operation, path = change.get('operation'), document_path(change.get('path'))
            fields = {'operation', 'path'} | ({'content'} if operation in {'add', 'edit'} else
                                             {'to_path'} if operation == 'move' else set())
            if operation not in {'add', 'edit', 'move', 'unlink'} or set(change) != fields or path in seen:
                raise ValueError('invalid or repeated document action')
            seen.add(path)
            if operation == 'add':
                if path in state.get('document_bases', {}):
                    raise ValueError('addition collides with a checkout path')
                files[path] = change['content']
            else:
                if path not in state.get('document_bases', {}):
                    raise ValueError('change requires an existing checkout document')
                if operation == 'edit':
                    files[path] = change['content']
                else:
                    text = files.pop(path)
                    if operation == 'move':
                        target = document_path(change['to_path'])
                        if target in files or target in state.get('document_bases', {}):
                            raise ValueError('move target collides with a checkout path')
                        files[target] = text
            changes.append(change)
        validate_files(files)
        return changes

    def _folder_pending(self, bases, changes, start, key):
        pending = []
        for index, change in enumerate(changes[start:], start):
            base = bases.get(change['path'], {})
            ref = ResourceRef.from_dict(base['document_ref']) if base else ResourceRef(
                self.authority, 'dat.content.document', 'folder-' + sha256(
                    (self.authority + ':' + key + ':document:' + str(index) + ':create').encode()).hexdigest()[:28])
            current = self.content.read(ref)
            pending.append({**change, 'document_ref': ref.to_dict(),
                'base_revision_ref': base.get('revision_ref'),
                'observed_current_revision_ref': current.get('current_revision'),
                'base_association_ref': base.get('association_ref')})
        return pending

    def _folder_apply(self, project, bases, changes, actor, key, *, intent, complete):
        # Freeze the parent input in an ordinary target-owned immutable DAT
        # revision. It is operation evidence, not a path/document registry.
        intent_ref = None
        committed = []
        current_action = None
        try:
            # Destination CAS pins are captured once and retained in the intent.
            # An existing active path is never overwritten by add/move.
            planned_ref = ResourceRef(self.authority, 'dat.content.document',
                'folder-' + sha256((self.authority + ':' + key + ':intent').encode()).hexdigest()[:28])
            prior = self.reader.get_receipt(key + ':intent')
            if prior is not None:
                saved = self.content.read(ResourceRef(planned_ref.authority, planned_ref.kind, planned_ref.id, 'rev-1'))['content']
                if canonical_json(saved['input']) != canonical_json(intent):
                    from herzchen.contracts import ReplayConflictError
                    raise ReplayConflictError('folder operation key was reused with changed input')
                destinations = saved['destinations']
            else:
                destinations = {}
                for change in changes:
                    path = change['path'] if change['operation'] == 'add' else change.get('to_path')
                    if path is None:
                        continue
                    association = DocumentAssociation(_identity(project), PROJECT_FILES_NAMESPACE, path,
                        ReferenceBinding(ResourceRef(self.authority, 'dat.content.document', 'placeholder'), 'current'))
                    target = ResourceRef(self.authority, 'document-association', association.identity)
                    current = self.reader.get_identity(target)
                    if current is not None and current.payload.get('active') is not False:
                        raise ValueError('destination path already has an active document')
                    destinations[path] = None if current is None else current.ref.revision
            intent_ref, intent_receipt = self._folder_create(project, actor, key + ':intent',
                {'input': intent, 'destinations': destinations}, 'evidence')
            for index, change in enumerate(changes):
                current_action = change
                path, operation = change['path'], change['operation']
                child = key + ':document:' + str(index)
                if operation == 'add':
                    document, receipt = self._folder_create(project, actor, child + ':create', change['content'])
                    link = self._folder_link(project, document, path, actor, child + ':link', base=destinations[path])
                    receipts = [receipt, link]
                    revision = ResourceRef(document.authority, document.kind, document.id, 'rev-1')
                else:
                    base = bases[path]
                    document = ResourceRef.from_dict(base['document_ref'])
                    revision = ResourceRef.from_dict(base['revision_ref'])
                    # A path can be reassigned independently of its document
                    # head. Check the original membership before a new effect.
                    effect_key = child + (':append' if operation == 'edit' else ':unlink')
                    if self.reader.get_receipt(effect_key) is None:
                        association_ref = ResourceRef.from_dict(base['association_ref'])
                        association = self.reader.get_identity(_identity(association_ref))
                        if (association is None or association.ref != association_ref
                                or association.payload.get('active') is not True):
                            from herzchen.kernel import VersionConflictError
                            raise VersionConflictError('checkout path membership is stale')
                    if operation == 'edit':
                        # Frozen parent revision determines both CAS and child
                        # request identity even after this write committed.
                        record = self.content.read(document)
                        typed = ContentDocument.from_dict(record['document'])
                        # Numeric folder revisions retain their old replay
                        # bytes. EDT also publishes opaque revision pins; derive
                        # their successor from the frozen parent and child key,
                        # never from the mutable current head.
                        suffix = revision.revision.removeprefix('rev-')
                        next_revision = ('rev-' + str(int(suffix) + 1)
                            if revision.revision.startswith('rev-') and suffix.isdecimal()
                            else 'rev-' + sha256((self.authority + ':' + child +
                                ':append:' + revision.revision).encode()).hexdigest()[:28])
                        appended = ContentRevision(document, next_revision, change['content'], actor,
                                                   parent_revision=revision.revision)
                        payload = {'document': typed, 'revision': appended}
                        context = self._folder_context('dat.content.revision.append', document, actor,
                            child + ':append', payload, revision.revision)
                        receipt = self.content.execute(self.content.build_append_revision(context, typed, appended))
                        receipts = [receipt]
                        revision = appended.ref
                    else:
                        receipts = []
                        if operation == 'move':
                            receipts.append(self._folder_link(project, document, change['to_path'], actor, child + ':link', base=destinations[change['to_path']]))
                        receipts.append(self._folder_link(project, document, path, actor, child + ':unlink',
                            unlink=True, base=base['association_ref']['revision']))
                committed.append({'operation': operation, 'path': path,
                    'document_ref': document.to_dict(), 'revision_ref': revision.to_dict(),
                    'receipts': [self._json_mapping(receipt.to_dict(), 'receipt') for receipt in receipts]})
            current_action = None
            finished = complete()
            success = finished.get('outcome') in {'finished', 'replayed', 'imported'}
            return {**finished, 'atomic': False, 'committed': committed, 'pending': [],
                    'project_sheet_pending': not success, 'intent_ref': intent_ref.to_dict(),
                    'intent_receipt': intent_receipt.to_dict(), 'execution': False, 'dispatch': False}
        except Exception as exc:
            if type(exc).__name__ == 'ReplayConflictError':
                raise
            # A child may have committed before formatting/return failed. Exact
            # retained receipts reveal that sub-progress, never a guessed retry.
            child_receipts = []
            for index in range(len(changes)):
                for suffix in ('create', 'append', 'link', 'unlink'):
                    receipt = self.reader.get_receipt(key + ':document:' + str(index) + ':' + suffix)
                    if receipt is not None:
                        child_receipts.append(receipt.to_dict())
            return {'outcome': 'partial', 'atomic': False, 'project_ref': project.to_dict(),
                    'committed': committed, 'pending': self._folder_pending(bases, changes, len(committed), key),
                    'project_sheet_pending': True, 'intent_ref': None if intent_ref is None else intent_ref.to_dict(),
                    'child_receipts': child_receipts, 'failed_action': current_action,
                    'error': {'code': type(exc).__name__, 'message': str(exc)},
                    'recovery': 'Inspect retained child receipts; resume only the exact input and request key.',
                    'execution': False, 'dispatch': False}


def validate_transfer(snapshot):
    """Validate genuine export record structure before any target creation.

    Offline validation establishes coherent source refs and byte digests. The
    caller still supplies the trusted source-owner export; a digest is not a
    signature or proof that invented records exist in another authority.
    """
    if not isinstance(snapshot, Mapping) or snapshot.get('schema') != 'otto.project-transfer.v1':
        raise ValueError('canonical transfer requires an owner-exported snapshot')
    source = ResourceRef.from_dict(snapshot['source_ref'])
    project = snapshot['project']
    if (source.kind != 'work.project' or source.revision is None
            or project.get('project_ref') != source.to_dict()):
        raise ValueError('transfer project/source revision refs are inconsistent')
    docs, links = snapshot.get('documents', []), snapshot.get('document_links', [])
    if (not isinstance(docs, list) or not isinstance(links, list) or len(docs) > MAX_OPERATION_FILES
            or len(links) > 4 * MAX_OPERATION_FILES):
        raise ValueError('transfer document selection exceeds one operation; transfer in selections')
    selected = set()
    paths = {}
    for item in docs:
        payload = item['payload']
        document = ContentDocument.from_dict(payload['document'])
        current = ResourceRef.from_dict(payload['current_revision'])
        record = ResourceRef.from_dict(item['project_ref'])
        revision = item['current_revision_record']['payload']
        if (document.ref.authority != source.authority or record != current
                or _identity(current) != document.ref or current.revision is None
                or revision.get('identity') != current.to_dict()
                or revision.get('revision') != current.revision
                or revision.get('content_digest') != sha256(canonical_json(revision.get('content')).encode()).hexdigest()):
            raise ValueError('transfer document refs/revision/content digest are inconsistent')
        if document.ref.id in selected:
            raise ValueError('duplicate source transfer document')
        selected.add(document.ref.id)
    for item in links:
        if item['payload'].get('active') is not True:
            raise ValueError('transfer link must be active')
        association = DocumentAssociation.from_dict(item['payload']['association'])
        if (association.subject.authority != source.authority
                or association.document.ref.authority != source.authority
                or association.document.ref.id not in selected):
            raise ValueError('transfer membership lacks its selected source document')
        if association.namespace == PROJECT_FILES_NAMESPACE:
            if _identity(association.subject) != _identity(source):
                raise ValueError('folder transfer paths require project memberships')
            if association.key in paths:
                raise ValueError('duplicate transfer document path')
            paths[association.key] = ''
    validate_files(paths)
