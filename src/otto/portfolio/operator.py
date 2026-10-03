"""Local operator entry for one existing owner Store and project.

Configuration is an owner-controlled capability, pinned by the launcher. There
is no create/import/dispatch command. Adoption delegates all domain effects to
existing owners, inside one Store transaction, and never changes a work item.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import socket
import stat
from typing import Any
from herzchen.contracts import ReferenceBinding, ResourceRef, TransactionContext, canonical_json
from herzchen.kernel.store import Store
from .herzchen_binding import HerzchenBindingConfig, ProjectReadGrant
from .owner_bootstrap import PortfolioOwnerBootstrap
from .owner_readers import json_value, mandate_reader, task_reader


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def need(condition: Any, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def checked_file(path: Path) -> bytes:
    need(path.is_absolute(), "configuration and source paths must be absolute")
    for part in (path, *path.parents):
        info = part.lstat()
        need(not stat.S_ISLNK(info.st_mode), "symbolic links are not admitted")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(fd)
        need(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
             and not info.st_mode & 0o022, "file must be regular, owner owned and not publicly writable")
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            return stream.read()
    finally:
        os.close(fd)


def domains() -> tuple:
    from herzchen.domains.work import contributions
    from herzchen.content.model import domain_contribution as content
    from herzchen.content.packets import domain_contribution as packets
    from herzchen.authoring.sessions import domain_contribution as authoring
    from herzchen.domains.assessment.module import contribution as assessment
    return tuple(sorted((*contributions(include_assignment_resources=True), content(),
                         packets(), authoring(), assessment()), key=lambda item: item.domain_id))


def load_config(path: Path, expected_sha256: str) -> dict:
    raw = checked_file(path)
    need(digest(raw) == expected_sha256, "configuration digest mismatch")
    config = json.loads(raw)
    need(config['schema'] == 'otto.project-operator.v1', "unsupported operator configuration")
    need(os.getuid() == os.geteuid() and os.getgid() == os.getegid(), "effective credentials differ")
    need(config['principal'] == {'uid': os.geteuid(), 'gid': os.getegid(),
                                'account': pwd.getpwuid(os.geteuid()).pw_name}, "configured principal mismatch")
    need(config['host_id'] == socket.gethostname(), "configured host mismatch")
    # The established host config remains the source of principal and credential.
    host = config['host_binding']
    host_raw = checked_file(Path(host['path']))
    need(digest(host_raw) == host['sha256'], "host binding digest mismatch")
    original = json.loads(host_raw)
    for key in ('principal', 'host_id', 'authority', 'credential_ref'):
        need(config[key] == original[key], 'host binding mismatch: ' + key)
    need(config['store']['path'] == original['canonical_destination'], 'Store differs from host binding')
    need(config['project_ref']['authority'] == config['authority']
         and config['project_ref']['kind'] == 'work.project'
         and config['project_ref'].get('revision'), 'exact project reference required')
    return config


class ProjectOperator:
    def __init__(self, config: dict, config_sha256: str):
        self.config, self.config_sha256 = config, config_sha256
        self.store = None

    def __enter__(self):
        target = self.config['store']
        path = Path(target['path'])
        need(path.is_absolute(), 'Store path must be absolute')
        for part in (path, *path.parents):
            need(not stat.S_ISLNK(part.lstat().st_mode), 'Store path contains symbolic link')
        info = path.stat()
        need(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
             and not info.st_mode & 0o022, 'Store custody mismatch')
        need([info.st_dev, info.st_ino] == target['device_inode'], 'Store identity changed')
        self.store = Store.open(path, authority=self.config['authority'], expected_domains=domains())
        try:
            need(self.store.domain_descriptor_digest == target['domain_descriptor_digest'], 'Store composition changed')
            self.project = ResourceRef.from_dict(self.config['project_ref'])
            record = self.store.consumer().get_record(self.project)
            need(record is not None and record.ref == self.project, 'project missing or revision changed')
            self.actor = self.config['principal']['account']
            binding = HerzchenBindingConfig(self.config['authority'], self.config['credential_ref'])
            grant = ProjectReadGrant(binding.authenticated_actor(self.actor), (self.project.id,),
                                     'otto.project-operator.v1', self.config_sha256)
            self.owner = PortfolioOwnerBootstrap(self.store, binding=binding, owner_actor=self.actor,
                                                project_read_grant=grant)
            self.application = self.owner.manager_application()
            self.operations = self.application.portfolio.operations
            return self
        except BaseException:
            self.store.close()
            raise

    def __exit__(self, *_):
        self.store.close()

    def _task(self, raw: str) -> dict:
        pin = json.loads(raw)
        observed = task_reader(self.operations, self.project.to_dict(), pin)(
            {k: pin[k] for k in ('authority', 'kind', 'id')})
        need(observed['ref'] == pin, 'task revision changed')
        return pin

    def read(self, command: str, options: list[str]) -> int:
        """Only listed read commands reach the existing finite manager CLI."""
        need(command in ('projects', 'project', 'tasks', 'task', 'documents', 'gate'), 'unsupported read command')
        need(not any(v.split('=')[0] in ('--actor', '--project-ref', '--parent-ref') for v in options),
             'actor and project overrides are forbidden')
        project = json.dumps(self.project.to_dict())
        common = ['--actor', self.actor, '--project-ref', project]
        if command == 'projects':
            # Reuse the existing inventory operation without caller scope selectors.
            argv = ['projects', '--actor', self.actor, *options]
        elif command == 'project':
            argv = ['overview', *common, *options]
        elif command in ('tasks', 'task'):
            if command == 'task':
                parsed = self._option(options, '--task-ref')
                self._task(parsed)
            argv = [command, *common, *options]
        elif command == 'documents':
            need(options and options[0] in ('list', 'search', 'read', 'link', 'history', 'bundle', 'diff'), 'document read command required')
            argv = ['documents', options[0], *common, *options[1:]]
        else:
            self._task(self._option(options, '--task-ref'))
            argv = ['completion-gate', *options]
        return self.application.run(argv)

    @staticmethod
    def _option(options, name):
        for i, value in enumerate(options):
            if value == name and i + 1 < len(options):
                return options[i + 1]
            if value.startswith(name + '='):
                return value.split('=', 1)[1]
        raise ValueError(name + ' is required')

    def instructions(self, assignment_pin: dict) -> dict:
        from .resource_sync import resolve_assignment_attachments
        assignment = self.owner.assignments.get(ResourceRef.from_dict(assignment_pin))
        need(json_value(assignment.ref) == assignment_pin, 'assignment revision changed')
        need(assignment.scope.authority == self.project.authority and assignment.scope.kind == self.project.kind
             and assignment.scope.id == self.project.id, 'assignment is outside project')
        value = self.operations._assignment_dict(assignment)
        return {'outcome': 'read', 'read_only': True, 'assignment': value,
                'instructions': json_value(resolve_assignment_attachments(value, self.operations.content_port))}

    def _sealed_plan(self, name: str, schema: str) -> dict:
        binding = self.config.get(name, {})
        need(binding.get('path'), name + ' requires an owner-sealed proposal')
        raw = checked_file(Path(binding['path']))
        need(digest(raw) == binding['sha256'], name + ' proposal digest mismatch')
        plan = json.loads(raw)
        need(plan['schema'] == schema and plan['project_ref'] == self.project.to_dict(),
             name + ' project/schema mismatch')
        self._sealed_context(plan)
        need(isinstance(plan['request_id'], str) and plan['request_id'].strip(), 'stable request id required')
        return plan

    def _sealed_context(self, plan: dict) -> None:
        need(plan['roles']['manager'] == self.actor, 'configured manager must be the executing owner principal')
        need(plan['roles'].get('profile') == 'CUSTOM', 'CUSTOM configuration required')
        need('resources' not in plan['roles'], 'adopt exact instruction resources through the owner adoption port')
        # Validate configured principal evidence; model names are not identities.
        principals_raw = checked_file(Path(plan['principals_source']['path']))
        need(digest(principals_raw) == plan['principals_source']['sha256'], 'principal source digest mismatch')
        principals = json.loads(principals_raw)
        need(principals['roles'] == plan['roles'], 'role principals differ from saved configured source')
        scope = plan['pilot_scope']
        need(scope['task_alias'] == 'T01' and scope['criterion_alias'] == 'C01', 'only original T01/C01 is permitted')
        self._task(json.dumps(scope['task_ref']))
        from herzchen.domains.assessment import AssessmentModule
        assessment = AssessmentModule(self.store, actor=self.owner.owner_actor)
        assessment_scope = assessment.get_scope(ResourceRef.from_dict(scope['assessment_scope_ref']))
        need(json_value(assessment_scope.ref) == scope['assessment_scope_ref'],
             'original C01 scope is stale')
        criterion = ResourceRef.from_dict(scope['criterion_ref'])
        need(criterion in assessment_scope.criterion_refs, 'C01 is outside original assessment scope')
        current_criterion = self.store.consumer().get_record(criterion)
        need(current_criterion is not None and current_criterion.ref == criterion, 'C01 revision changed')
        parent = json_value(assessment_scope.parent_obligation_ref)
        if parent != scope['task_ref']:
            # WorkerProjectImporter deliberately declares one project-owned
            # worker-source-freeze scope. Bind the exact pilot through its
            # authored aliases and provenance instead of inventing a task scope.
            need(parent == self.project.to_dict(), 'original C01 scope is outside the exact project/T01')
            mapping_sha = scope.get('source_mapping_sha256')
            need(isinstance(mapping_sha, str) and len(mapping_sha) == 64
                 and all(c in '0123456789abcdef' for c in mapping_sha), 'source mapping digest pin required')
            need(scope.get('assessment_protocol') == assessment_scope.protocol == 'worker-source-freeze'
                 and assessment_scope.policy.get('source_mapping_sha256') == mapping_sha
                 and assessment_scope.policy.get('imported_verdicts') is False
                 and assessment_scope.review_required is True
                 and assessment_scope.allow_no_review is False, 'imported assessment policy mismatch')
            project_record = self.store.consumer().get_record(self.project)
            need(project_record.payload.get('metadata', {}).get('worker_source_mapping_sha256') == mapping_sha,
                 'project and assessment source mappings differ')
            task_record = task_reader(self.operations, self.project.to_dict(), scope['task_ref'])(
                {k: scope['task_ref'][k] for k in ('authority', 'kind', 'id')})
            metadata = task_record['payload'].get('metadata', {})
            need(metadata.get('source_alias') == 'T01' and metadata.get('criterion_aliases') == ['C01']
                 and metadata.get('canonical_source_task') is True
                 and metadata.get('worker_binding') == 'worker_normal', 'original T01/C01 authored association mismatch')
            need(current_criterion.payload.get('definition', {}).get('source_alias') == 'C01',
                 'selected criterion is not original C01')
        need(scope['dispatch_enabled'] is False and scope['requires_prerequisites'] is True, 'dispatch is held pending prerequisites')
        need(scope['native_records_govern'] is True and scope['frozen_source_is_provenance'] is True,
             'native handover semantics required')
        need(scope['forbidden'] == ['T02+', 'GPU', 'final_review', 'provider_dispatch'], 'pilot fence mismatch')
        for source in plan['source_pins']:
            need(digest(checked_file(Path(source['path']))) == source['sha256'], 'source revision changed')
        need(plan['source_pins'], 'original T01/C01 and resource source pins are required')

        need(plan['roles']['parent'] == self.project.to_dict(), 'role parent must be the exact project')

    def _new_document(self, raw: dict) -> ResourceRef:
        ref = ResourceRef.from_dict(raw)
        need(ref.authority == self.project.authority and ref.kind == 'dat.content.document'
             and not ref.revision, 'new local document identity required')
        need(self.store.consumer().get_record(ref) is None,
             'document already exists; inspect prior publication before retry')
        return ref

    def _document_read(self, pin: dict, role: str) -> dict:
        ref = ResourceRef.from_dict(pin)
        need(ref.authority == self.project.authority and ref.kind == 'dat.content.document'
             and ref.is_pinned, 'exact local document revision required')
        observed = json_value(self.owner.content.read(ResourceRef(ref.authority, ref.kind, ref.id)))
        document, revision = observed['document'], observed['revision']
        need(document['role'] == role and document['maintainer'] == self.actor
             and document['authoring_scope'] == self.project.to_dict(), 'document custody/scope mismatch')
        need(observed['current_revision']['revision'] == ref.revision
             and revision['revision'] == ref.revision, 'document revision is stale')
        return {'ref': pin, 'document': document, 'content': revision['content']}

    def _publish_document(self, ref: ResourceRef, role: str, content: dict, key: str) -> dict:
        # Transaction ownership stays with the caller; all writes stay with the content owner.
        from herzchen.content import ContentDocument, ContentRevision
        from herzchen.content.model import DocumentAssociation
        doc = ContentDocument(ref, role=role, visibility='private', access_mode='append',
                              maintainer=self.actor, authoring_scope=self.project)
        revision = ContentRevision(doc.ref, 'rev-1', content, self.owner.owner_actor, initial=True)
        context = TransactionContext(self.owner.owner_actor, key + ':document',
                                     digest(canonical_json(content).encode()), expected_version=0)
        receipt = self.owner.content.execute(self.owner.content.build_create_document(context, doc, revision))
        pin = json_value(receipt.result_ref)
        association = DocumentAssociation(self.project, 'otto', role + ':' + ref.id,
                                          ReferenceBinding(ResourceRef.from_dict(pin), 'pinned'))
        link_context = TransactionContext(self.owner.owner_actor, key + ':link',
                                         digest(canonical_json({'subject': self.project.to_dict(), 'document': pin, 'key': role + ':' + ref.id}).encode()))
        link = self.owner.content.execute(self.owner.content.build_link(link_context, association))
        read = self._document_read(pin, role)
        need(read['content'] == content, 'published content readback mismatch')
        return {'document': read, 'create_receipt': json_value(receipt), 'link_receipt': json_value(link)}

    def publication_plan(self) -> dict:
        from herzchen.content.instructions import validate_instruction_content
        plan = self._sealed_plan('publication', 'otto.project-resource-publication.v1')
        self._new_document(plan['document_ref'])
        source = plan['resource_source']
        raw = checked_file(Path(source['path']))
        need(digest(raw) == source['sha256'], 'resource source digest mismatch')
        content = json.loads(raw)
        need(validate_instruction_content(content) == plan['content_digest'], 'instruction content digest mismatch')
        need(content['name'] == plan['resource_name'] and content['required'] is plan['required'],
             'instruction metadata mismatch')
        return {**plan, 'content': content}

    def publish_resource(self) -> dict:
        need(self.config.get('publication', {}).get('enabled') is True, 'publication is not enabled in owner configuration')
        with self.store.transaction():
            plan = self.publication_plan()
            result = self._publish_document(ResourceRef.from_dict(plan['document_ref']), 'instructions',
                                            plan['content'], plan['request_id'])
            return {'outcome': 'published', **result, 'resource': {
                'resource_ref': result['document']['ref'], 'resource_name': plan['resource_name'],
                'content_digest': plan['content_digest'], 'required': plan['required']},
                'resource_source': plan['resource_source'], 'dispatch': False,
                'adoption': 'not_performed', 'delivery_state': 'not_delivered'}

    def operating_brief(self, request: dict) -> dict:
        # Delegate preparation and every domain check to the existing manager CLI.
        import io
        from contextlib import redirect_stdout
        need(request['project_ref'] == self.project.to_dict(), 'brief project mismatch')
        with redirect_stdout(io.StringIO()) as output:
            self.application.run(['operating-brief', '--request-json', json.dumps(request)])
        return json.loads(output.getvalue())

    def brief_plan(self) -> dict:
        plan = self._sealed_plan('brief_publication', 'otto.project-brief-publication.v1')
        self._new_document(plan['document_ref'])
        request = plan['request']
        need(request['role'] == 'manager' and request['task_ref'] == plan['pilot_scope']['task_ref'],
             'brief must bind the manager and original T01')
        prepared = self.operating_brief(request)
        need(prepared.get('outcome') == 'prepared', 'canonical brief unavailable: ' + json.dumps(prepared.get('error', prepared)))
        brief = prepared['operating_brief']
        need(brief['render']['snapshot']['principal'] == self.actor, 'brief principal differs from configured manager')
        mandate = mandate_reader(self.operations, self.project.to_dict(), request['mandate_ref'])(
            {k: request['mandate_ref'][k] for k in ('authority', 'kind', 'id')})
        need(mandate['payload']['pilot_scope'] == plan['pilot_scope'], 'brief mandate pilot fence mismatch')
        need(brief['evidence_sha256'] == plan['expected_evidence_sha256'], 'canonical brief changed since selection')
        return {**plan, 'prepared': brief}

    def publish_brief(self) -> dict:
        need(self.config.get('brief_publication', {}).get('enabled') is True, 'brief publication is not enabled in owner configuration')
        with self.store.transaction():
            plan = self.brief_plan()
            result = self._publish_document(ResourceRef.from_dict(plan['document_ref']), 'operating_brief',
                                            plan['prepared'], plan['request_id'])
            return {'outcome': 'published', **result, 'dispatch': False,
                    'delivery_state': 'published_for_owner_readback', 'runtime_delivery': 'not_performed'}

    def read_brief(self, pin: dict) -> dict:
        result = self._document_read(pin, 'operating_brief')
        prepared = result['content']
        refs = prepared['source_refs']
        request = {'role': prepared['role'], 'project_ref': refs['project'], 'task_ref': refs['task'],
                   'assignment_ref': refs['assignment'], 'mandate_ref': refs['mandate'],
                   'expected_generation': prepared['generation'], 'as_of': prepared['render']['freshness']['as_of']}
        current = self.operating_brief(request)
        need(current.get('outcome') == 'prepared' and current['operating_brief'] == prepared,
             'published brief sources are stale; refresh through canonical preparation')
        return {'outcome': 'read', **result, 'read_only': True, 'dispatch': False,
                'delivery_state': 'owner_readback', 'runtime_delivery': 'not_performed'}

    def adoption_plan(self) -> dict:
        """Read the owner-sealed proposal; validate bytes and current native pins."""
        binding = self.config.get('adoption')
        need(isinstance(binding, dict) and binding.get('path'),
             'adoption is locked: missing configured manager/executor principals and exact current native instruction revisions; O07 must supply the owner-sealed proposal')
        raw = checked_file(Path(binding['path']))
        need(digest(raw) == binding['sha256'], 'adoption proposal digest mismatch')
        plan = json.loads(raw)
        need(plan['schema'] == 'otto.project-adoption.v1' and plan['project_ref'] == self.project.to_dict(), 'adoption project mismatch')
        self._sealed_context(plan)
        scope = plan['pilot_scope']
        # Existing instruction revisions only: publishing new instructions stays
        # with the current resource owner. This entry never invents a revision.
        from herzchen.content.instructions import validate_instruction_content
        need(len(plan['resource_sources']) == len(plan['resources']), 'every resource needs exact saved content provenance')
        for resource, source in zip(plan['resources'], plan['resource_sources']):
            source_bytes = checked_file(Path(source['path']))
            need(digest(source_bytes) == source['sha256'], 'resource source digest mismatch')
            ref = ResourceRef.from_dict(resource['resource_ref'])
            need(ref.authority == self.project.authority and ref.is_pinned, 'instruction must pin local revision')
            observed = self.owner.content.read(ResourceRef(ref.authority, ref.kind, ref.id))
            current = json_value(observed['current_revision'])
            content = json_value(observed['revision'])['content']
            need(json.loads(source_bytes) == content, 'native resource differs from selected saved source')
            need(current['revision'] == ref.revision, 'instruction revision is stale')
            need(validate_instruction_content(content) == resource['content_digest'], 'instruction content digest mismatch')
            need(content['name'] == resource['resource_name'] and content['required'] is resource['required'], 'instruction metadata mismatch')
        need(plan['resources'], 'exact native instruction resources required')
        mandate = plan['mandate']
        need(mandate['content']['pilot_scope'] == scope and mandate['content']['status'] == 'active', 'mandate scope mismatch')
        need(mandate['content']['role'] == 'manager', 'manager mandate required')
        brief = mandate['content']['brief']
        if isinstance(brief, dict):
            from .operating_brief import OperatingBrief
            need(OperatingBrief.from_mapping(brief, role='manager').mandate.strip(), 'manager mandate text required')
        else:
            need(isinstance(brief, str) and brief.strip(), 'manager mandate brief required')
        need(mandate['ref']['authority'] == self.project.authority and mandate['ref']['kind'] == 'dat.content.document'
             and not mandate['ref'].get('revision'), 'new mandate identity required')
        need(self.store.consumer().get_record(ResourceRef.from_dict(mandate['ref'])) is None, 'mandate already exists; inspect prior adoption before retry')
        return plan

    def adopt(self) -> dict:
        need(self.config.get('adoption', {}).get('enabled') is True, 'adoption is not enabled in owner configuration')
        from herzchen.content import ContentDocument, ContentRevision
        from herzchen.content.model import DocumentAssociation
        with self.store.transaction():
            plan = self.adoption_plan()
            key = plan['request_id']
            need(isinstance(key, str) and key.strip(), 'stable request id required')
            result = self.application.portfolio.assign_roles(self.project.to_dict(), plan['roles'], actor=self.actor, request_id=key + ':roles')
            need(result.get('outcome') == 'assigned', 'canonical role assignment rejected')
            adopted = []
            for item in result['roles'].values():
                if item['role'] == 'parent':
                    continue
                assignment = self.owner.assignments.adopt_resources(ResourceRef.from_dict(item['ref']),
                    resources=plan['resources'], expected_revision=item['ref']['revision'],
                    expected_generation=item['generation'], logical_request_key=key + ':resources:' + item['ref']['id'], actor=self.owner.owner_actor)
                adopted.append(json_value(self.operations._assignment_dict(assignment)))
            mandate = plan['mandate']
            doc = ContentDocument(ResourceRef.from_dict(mandate['ref']), role='mandate', visibility='private',
                                  access_mode='append', maintainer=self.actor, authoring_scope=self.project)
            revision = ContentRevision(doc.ref, 'rev-1', mandate['content'], self.owner.owner_actor, initial=True)
            context = TransactionContext(self.owner.owner_actor, key + ':mandate', digest(canonical_json(mandate).encode()), expected_version=0)
            receipt = self.owner.content.execute(self.owner.content.build_create_document(context, doc, revision))
            pin = json_value(receipt.result_ref)
            association = DocumentAssociation(self.project, 'otto', 'mandate', ReferenceBinding(revision.ref, 'pinned'))
            link_context = TransactionContext(self.owner.owner_actor, key + ':mandate-link',
                                              digest(canonical_json({'subject': self.project.to_dict(), 'document': pin, 'key': 'mandate'}).encode()))
            self.owner.content.execute(self.owner.content.build_link(link_context, association))
            read = mandate_reader(self.operations, self.project.to_dict(), pin)(json_value(doc.ref))
            need(read['payload'] == mandate['content'] and read['document_owner'] == self.actor, 'mandate readback mismatch')
            return {'outcome': 'adopted', 'project_ref': self.project.to_dict(), 'assignments': adopted,
                    'mandate': read, 'dispatch': False, 'pilot_scope': plan['pilot_scope']}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='otto-project', description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--config-sha256', required=True)
    parser.add_argument('command', choices=('projects', 'project', 'tasks', 'task', 'documents', 'gate', 'instructions', 'mandate', 'adoption-check', 'adopt', 'resource-publish-check', 'resource-publish', 'operating-brief', 'brief-publish-check', 'brief-publish', 'brief-read'))
    parser.add_argument('options', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    import io
    from contextlib import redirect_stdout
    try:
        config = load_config(args.config, args.config_sha256)
        with redirect_stdout(io.StringIO()) as buffered, ProjectOperator(config, args.config_sha256) as operator:
            def dispatch():
                if args.command in ('resource-publish-check', 'resource-publish', 'brief-publish-check', 'brief-publish', 'operating-brief', 'brief-read'):
                    if args.command in ('operating-brief', 'brief-read'):
                        need(len(args.options) == 1, args.command + ' requires one JSON request/reference')
                        payload = json.loads(args.options[0])
                        result = operator.operating_brief(payload) if args.command == 'operating-brief' else operator.read_brief(payload)
                    else:
                        need(not args.options, 'publication takes no caller payload overrides')
                        commands = {'resource-publish-check': lambda: {'outcome': 'validated', 'read_only': True, 'plan': operator.publication_plan()},
                                    'resource-publish': operator.publish_resource,
                                    'brief-publish-check': lambda: {'outcome': 'validated', 'read_only': True, 'plan': operator.brief_plan()},
                                    'brief-publish': operator.publish_brief}
                        result = commands[args.command]()
                    print(json.dumps(result, sort_keys=True))
                    return 0 if result.get('outcome') in ('validated', 'published', 'prepared', 'read') else 1
                if args.command in ('instructions', 'mandate', 'adoption-check', 'adopt'):
                    if args.command == 'mandate':
                        need(len(args.options) == 1, 'mandate requires one exact document ResourceRef JSON')
                        pin = json.loads(args.options[0])
                        result = {'outcome': 'read', 'read_only': True, 'mandate': mandate_reader(
                            operator.operations, operator.project.to_dict(), pin)(
                                {k: pin[k] for k in ('authority', 'kind', 'id')})}
                    elif args.command == 'instructions':
                        need(len(args.options) == 1, 'instructions requires one exact assignment ResourceRef JSON')
                        result = operator.instructions(json.loads(args.options[0]))
                    else:
                        need(not args.options, 'adoption takes no caller payload overrides')
                        result = operator.adopt() if args.command == 'adopt' else {'outcome': 'validated', 'read_only': True, 'plan': operator.adoption_plan()}
                    print(json.dumps(result, sort_keys=True))
                    return 0
                return operator.read(args.command, args.options)
            code = dispatch()
        print(buffered.getvalue(), end="")
        return code
    except Exception as exc:
        print(json.dumps({'outcome': 'error', 'error': {'code': type(exc).__name__, 'message': str(exc)}, 'dispatch': False}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
