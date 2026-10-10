"""D03 real WRK/Evidence/FND late appends, with mechanical native fixtures."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch

from herzchen.contracts import ResourceRef, ReplayConflictError, AuthenticatedActor
from herzchen.domains.work import WorkGraph, contributions
from herzchen.authoring import domain_contribution as authoring_contribution
from herzchen.domains.work.assignments import ResponsibilityAssignments, StaleAssignmentError
from herzchen.domains.work.model import WorkValidationError
from herzchen.kernel.project_history import ProjectHistoryGrant, ProjectHistoryReader
from otto.agents.retained_native import RetainedNativeBodies
from otto.agents.usage_capture import UsageStream
from otto.agents.usage_accounting import account_usage
from otto.attention import due_record_contribution, issue_store_due_record_port
from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap
from otto.portfolio.herzchen_binding import HerzchenBindingConfig, ProjectReadGrant
from tests import test_evidence_projection as fixture
from tests.test_usage_capture import owner_capture, native


class LateUsageTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.EvidenceProjectionTests(); self.f.setUp(); self.addCleanup(self.f.tearDown)
        self.store, self.actor = self.f.store, self.f.actor
        self.store.register_domain_handler((*contributions(), due_record_contribution(), authoring_contribution()))
        graph = WorkGraph(self.store, actor=self.actor)
        self.project = graph.create_project(title='Usage', logical_request_key='usage-project')
        self.task = graph.create_task(self.project.ref, title='Historical task', logical_request_key='usage-task')
        self.p = ResponsibilityAssignments(self.store, actor=self.actor).command_port
        self.old = self.p.assign(self.project.ref, role='worker', principal='historical-worker',
            agent='historical-agent', session='session', logical_request_key='historical-assignment')
        self.manager = self.p.assign(self.project.ref, role='manager', principal='submitter', logical_request_key='manager')
        self.bodies = RetainedNativeBodies(self.f.handler, self.actor)
        self.owner = PortfolioOwnerBootstrap(self.store, binding=HerzchenBindingConfig('owner','credential'),
            owner_actor='submitter', project_read_grant=ProjectReadGrant(self.actor, (self.project.id,), 'test', 'v1'))
        self.op = self.owner.late_usage_operation(project_ref=self.project.ref,
            authorizing_assignment_ref=self.manager.ref, authorizing_generation=1, native_bodies=self.bodies)
        self.port = issue_store_due_record_port(self.store.domain_handler((due_record_contribution(),)), self.actor)
        from herzchen.command_ports import close_consumer_facade
        self.addCleanup(lambda: close_consumer_facade(self.port.transport))

    def original(self, adapter, *, phase='work', metrics=None, anchor=None, source_only=False, verified_model=None, context_verified=False, result_turn='turn', money_marker=None):
        metrics = {'input_tokens': 10, 'output_tokens': 2} if metrics is None else metrics
        events = native(adapter, metrics)
        if money_marker is not None:events[-1]['total_cost_usd']=money_marker
        line = json.dumps(events[-1])
        capture = UsageStream(adapter, phase=phase)
        for event in events: capture.feed(json.dumps(event))
        observation = capture.observations[0]
        if anchor: observation['first_qualified_recorded_at'] = anchor
        _, memory = owner_capture(); value = memory.read_due('schedule')
        value.update(assignment_ref=self.old.ref.to_dict(), generation=1, recipient='historical-worker',
            project_ref=self.project.id, manager_ref='submitter', lifecycle_owner='submitter')
        value['target'].update(project_ref=self.project.ref.to_dict(), task_ref=self.task.ref.to_dict(),
            assignment_ref=self.old.ref.to_dict(), principal='historical-worker')
        value['target'].pop('parent')
        value['host_evidence'] = {'gateway_attempt': {'state': 'result', 'logical_request_key': 'original',
            'request_fingerprint': 'original-fingerprint', 'assignment_ref': self.old.ref.to_dict(), 'generation': 1,
            'physical_session_id': 'session', 'delivery_admission': {'physical_session_id': 'session',
                'observed_turn_id': 'turn', 'observed_at': '2026-10-05T10:00:00Z'},
            'usage_observations': [observation] if anchor or phase == 'initializer' else [],
            'result': {'outcome': 'unknown', 'retry_allowed': False, 'raw_result': {'immutable': 'native'},
                'context_digest_verified':context_verified,'observed_model':verified_model,'observed_turn_id':result_turn}}}
        saved = self.port.save_due('schedule', value, request_id='original-due', expected_version=0)
        self.source_ref = ResourceRef('owner','otto.due-record','schedule','rev-1')
        self.source_line = line
        self.source = self.bodies.retain(line, project_ref=self.project.ref,
            task_ref=None if phase == 'initializer' else self.task.ref.to_dict(), attempt_ref=self.old.ref.to_dict())
        self.original_value = deepcopy(self.port.read_due('schedule'))
        return observation

    def append(self, adapter='codex-direct', *, key='late', phase='work', source=None, supersedes=None):
        return self.op.append(self.old.ref, self.source_ref, source or self.source, adapter_id=adapter,
            phase=phase, session_id='session', turn_id='turn', logical_request_key=key, supersedes_ref=supersedes)

    def replace(self):
        return self.p.reassign(self.old.ref, principal='today-worker', session='today-session', agent='today-agent',
            expected_generation=1, logical_request_key='replaced')

    def test_cross_adapter_old_generation_unknown_preserved_and_idempotent(self):
        for adapter in ('codex-direct', 'codex-host', 'claude-code'):
            with self.subTest(adapter=adapter):
                # Each adapter needs an isolated source namespace.
                if hasattr(self, 'source_ref'): self.tearDownFixture(); self.setUp()
                self.original(adapter, source_only=True); self.replace()
                before = self.store.consumer().snapshot_counts()
                retained = self.append(adapter); duplicate = self.append(adapter)
                self.assertEqual(retained, duplicate)
                self.assertEqual(retained['association']['generation'], 1)
                self.assertEqual(retained['association']['principal'], 'historical-worker')
                self.assertEqual(retained['association']['agent'], 'historical-agent')
                self.assertEqual(self.port.read_due('schedule'), self.original_value)
                self.assertEqual(self.store.consumer().snapshot_counts()['events'], before['events'] + 1)
                self.assertEqual(retained['observation']['capability']['live'], 'unverified' if adapter == 'claude-code' else 'supported')
                self.assertIsNotNone(self.store.get_receipt('late'))
                with self.assertRaises(StaleAssignmentError):
                    self.p.append_result(self.old.ref, {'outcome': 'succeeded'}, expected_generation=1, logical_request_key='forbidden-replay')
                with self.assertRaises(ReplayConflictError):
                    self.append(adapter, source={**self.source, 'sha256': '0'*64})

    def tearDownFixture(self):
        self.doCleanups()

    def test_monday_anchor_thursday_duplicate_richer_and_explicit_correction_as_of(self):
        self.original('codex-direct', anchor='2026-10-05T10:01:00Z'); self.replace()
        first = self.append()
        alias = self.append('codex-host', key='alias')
        richer = self.bodies.retain(json.dumps(native('codex-direct', {'input_tokens': 10, 'output_tokens': 2,
            'cached_input_tokens': 3})[-1]), project_ref=self.project.ref, task_ref=self.task.ref.to_dict(), attempt_ref=self.manager.ref.to_dict())
        rich = self.append(source=richer, key='richer')
        corrected = self.bodies.retain(json.dumps(native('codex-direct', {'input_tokens': 11, 'output_tokens': 2,
            'cached_input_tokens': 3})[-1]), project_ref=self.project.ref, task_ref=self.task.ref.to_dict(), attempt_ref=self.manager.ref.to_dict())
        correction = self.append(source=corrected, key='correction', supersedes=rich['ref'])
        for f in (first, alias, rich, correction):
            self.assertEqual(f['first_qualified_recorded_at'], '2026-10-05T10:01:00Z')
        facts = [first, alias, rich, correction]
        old = account_usage(facts, as_of=rich['append_position'], authorized_projects=[self.project.ref.to_dict()], complete=True)
        self.assertEqual(old['metrics'], {'input_tokens': 10, 'output_tokens': 2, 'cached_input_tokens': 3})
        # Equal aliases are one measurement. Explicit correction of the richer
        # canonical fact supersedes its equivalent partial carrier aliases.
        new = account_usage(facts, as_of=correction['append_position'], authorized_projects=[self.project.ref.to_dict()])
        self.assertEqual(new['metrics']['input_tokens'], 11)
        self.assertEqual(new['spans'][0]['state'], 'measured')
        self.assertEqual(account_usage(facts, as_of=rich['append_position'], authorized_projects=[self.project.ref.to_dict()], complete=True), old)

    def test_first_fact_correction_supersedes_and_never_moves_recorded_period(self):
        self.original('codex-host', anchor='2026-10-05T10:01:00Z'); self.replace()
        first = self.append('codex-host')
        source = self.bodies.retain(json.dumps(native('codex-host', {'input_tokens': 15})[-1]),
            project_ref=self.project.ref, task_ref=self.task.ref.to_dict(), attempt_ref=self.manager.ref.to_dict())
        correction = self.append('codex-host', key='correction', source=source, supersedes=first['ref'])
        args = dict(authorized_projects=[self.project.ref.to_dict()], from_at='2026-10-05T00:00:00Z', to_at='2026-10-06T00:00:00Z')
        old = account_usage([first, correction], as_of=first['append_position'], **args)
        new = account_usage([first, correction], as_of=correction['append_position'], **args)
        self.assertEqual(old['metrics']['input_tokens'], 10); self.assertEqual(new['metrics']['input_tokens'], 15)
        self.assertEqual(old['spans'][0]['first_qualified_recorded_at'], new['spans'][0]['first_qualified_recorded_at'])
        self.assertIsNone(account_usage([first, correction], as_of=correction['append_position'],
            authorized_projects=[self.project.ref.to_dict()], from_at='2026-10-08T00:00:00Z', to_at='2026-10-09T00:00:00Z')['metrics'])

    def test_old_inline_and_reference_only_wrk_result_pins_digest_unchanged(self):
        from herzchen.contracts import canonical_json
        import hashlib
        for reference_only in (False, True):
            with self.subTest(reference_only=reference_only):
                if hasattr(self, 'source_ref'): self.doCleanups(); self.setUp()
                self.original('codex-direct')
                value = {'assignment_ref': self.old.ref.to_dict(), 'generation': 1,
                    'logical_request_key': 'original-result', 'project_ref': self.project.ref.to_dict(),
                    'task_ref': self.task.ref.to_dict(), 'physical_session_id': 'session', 'observed_turn_id': 'turn',
                    'context_digest_verified': True, 'outcome': 'unknown', 'operation': 'resume',
                    'delivery_state': 'unknown', 'task_bound_evidence': {'session_id': 'session', 'turn_id': 'turn'},
                    'raw_result': {'stdout': 'original-native-' * 2000}, 'usage_capture': None}
                if reference_only:
                    value['task_bound_evidence'] = self.bodies.retain(value['task_bound_evidence'],
                        project_ref=self.project.ref, task_ref=self.task.ref.to_dict(), attempt_ref=self.old.ref.to_dict())
                    value['raw_result'] = self.bodies.retain(value['raw_result'],
                        project_ref=self.project.ref, task_ref=self.task.ref.to_dict(), attempt_ref=self.old.ref.to_dict())
                original = self.p.append_result(self.old.ref, value, expected_generation=1, logical_request_key='original-result')
                before = canonical_json(self.store.get_identity(original.ref).payload)
                receipt_before = self.store.get_receipt('original-result').to_dict()
                self.source_ref = original.ref; self.replace(); observed = self.append()
                self.assertEqual(observed['association']['generation'], 1)
                self.assertEqual(canonical_json(self.store.get_identity(original.ref).payload), before)
                self.assertEqual(self.store.get_receipt('original-result').to_dict(), receipt_before)
                self.assertEqual(hashlib.sha256(before.encode()).hexdigest(), hashlib.sha256(canonical_json(self.store.get_identity(original.ref).payload).encode()).hexdigest())

    def test_late_selected_cumulative_descendant_and_byte_exclusions(self):
        self.original('codex-direct'); self.replace()
        for index, extra in enumerate(({'usage_scope': 'cumulative'}, {'includes_descendants': True})):
            event = {**native('codex-direct', {'input_tokens': 10})[-1], **extra}
            source = self.bodies.retain(json.dumps(event), project_ref=self.project.ref,
                task_ref=None, attempt_ref=self.manager.ref.to_dict())
            f = self.append(source=source, key='excluded-' + str(index))
            q = account_usage([f], as_of=f['append_position'], authorized_projects=[self.project.ref.to_dict()])
            self.assertIsNone(q['metrics'])
            self.assertEqual(q['spans'][0]['state'], 'cumulative-not-additive' if index == 0 else 'parent-child-scope-unproven')
        with patch.object(self.bodies, 'resolve', side_effect=AssertionError('oversized selection must not be read')):
            with self.assertRaises(WorkValidationError):
                self.append(key='too-large', source={**self.source, 'utf8_bytes': 256*1024+1})
        self.assertIsNone(self.store.get_receipt('too-large'))

    def test_unissued_operation_and_changed_original_native_identity_fail_closed(self):
        self.original('codex-direct'); self.replace()
        with self.assertRaises(PermissionError):
            self.p.append_late_usage(self.old.ref, self.source_ref, self.source, adapter_id='codex-direct',
                phase='work', session_id='session', turn_id='turn', authorizing_assignment_ref=self.manager.ref,
                authorizing_generation=1, logical_request_key='not-issued', actor=self.actor)
        with self.assertRaises(WorkValidationError):
            self.op.append(self.old.ref, self.source_ref, self.source, adapter_id='codex-direct',
                phase='work', session_id='session', turn_id='different-turn', logical_request_key='wrong-turn')
        self.assertIsNone(self.store.get_receipt('wrong-turn'))

    def test_unknown_late_reply_retains_exact_receipt_no_replay_effect(self):
        self.original('codex-direct'); self.replace()
        def lose_reply():
            self.append()
            raise OSError('lost after committed append')
        with self.assertRaises(OSError): lose_reply()
        receipt = self.store.get_receipt('late')
        self.assertIsNotNone(receipt)
        count = self.store.consumer().snapshot_counts()['events']
        readback = self.append()
        self.assertEqual(readback['ref'], receipt.result_ref.to_dict())
        self.assertEqual(self.store.consumer().snapshot_counts()['events'], count)

    def test_current_grant_and_authorizer_fences_apply_to_retry(self):
        self.original('codex-direct'); self.replace(); self.append()
        self.owner.project_read_grant = ProjectReadGrant(self.actor, (), 'test', 'v2')
        with self.assertRaises(PermissionError): self.append()
        self.owner.project_read_grant = ProjectReadGrant(self.actor, (self.project.id,), 'test', 'v3')
        self.p.reassign(self.manager.ref, principal='replacement-manager', expected_generation=1, logical_request_key='replace-manager')
        with self.assertRaises(PermissionError): self.append()

    def test_source_identity_digest_origin_and_initializer_overhead(self):
        self.original('codex-direct', phase='initializer', anchor='2026-10-05T10:00:00Z'); self.replace()
        retained = self.append(phase='initializer')
        self.assertIsNone(retained['association']['task_ref'])
        result = account_usage([retained], as_of=retained['append_position'], authorized_projects=[self.project.ref.to_dict()])
        self.assertEqual(result['groups']['task'], [])
        self.assertEqual(result['groups']['project'][0]['metrics']['input_tokens'], 10)
        bad = {**self.source, 'sha256': '0'*64}
        with self.assertRaises(ValueError): self.append(key='bad', phase='initializer', source=bad)
        with self.assertRaises(ValueError): self.op.append(self.old.ref, self.source_ref, self.source,
            adapter_id='codex-direct', phase='initializer', session_id='foreign', turn_id='turn', logical_request_key='foreign')

    def test_shared_physical_span_retains_anchor_without_foreign_source_leak(self):
        self.original('codex-direct'); self.replace(); first = self.append()
        graph = WorkGraph(self.store, actor=self.actor)
        project = graph.create_project(title='Other', logical_request_key='other-project')
        task = graph.create_task(project.ref, title='Other', logical_request_key='other-task')
        worker = self.p.assign(project.ref, role='worker', principal='other-worker', logical_request_key='other-worker')
        manager = self.p.assign(project.ref, role='manager', principal='submitter', logical_request_key='other-manager')
        value = deepcopy(self.original_value)
        value.update(schedule_id='other-schedule', assignment_ref=worker.ref.to_dict(), project_ref=project.id,
            recipient='other-worker')
        value['target'].update(project_ref=project.ref.to_dict(), task_ref=task.ref.to_dict(),
            assignment_ref=worker.ref.to_dict(), principal='other-worker')
        value['host_evidence']['gateway_attempt'].update(assignment_ref=worker.ref.to_dict())
        self.port.save_due('other-schedule',value,request_id='other-due',expected_version=0)
        source = self.bodies.retain(self.source_line, project_ref=project.ref,
            task_ref=task.ref.to_dict(), attempt_ref=worker.ref.to_dict())
        self.owner.project_read_grant = ProjectReadGrant(self.actor,(self.project.id,project.id),'test','v2')
        op = self.owner.late_usage_operation(project_ref=project.ref, authorizing_assignment_ref=manager.ref,
            authorizing_generation=1, native_bodies=self.bodies)
        second = op.append(worker.ref, ResourceRef('owner','otto.due-record','other-schedule','rev-1'),source,
            adapter_id='codex-direct',phase='work',session_id='session',turn_id='turn',logical_request_key='other-late')
        self.assertEqual(second['first_qualified_recorded_at'],first['first_qualified_recorded_at'])
        self.assertEqual(second['shared_scope_count'],2)
        self.assertNotIn(self.project.id,json.dumps(second))
        self.assertNotIn(self.old.id,json.dumps(second))
        single = account_usage([second],as_of=second['append_position'],authorized_projects=[project.ref.to_dict()])
        self.assertEqual(single['spans'],[]); self.assertIsNone(single['metrics'])
        combined = account_usage([first,second],as_of=second['append_position'],
            authorized_projects=[self.project.ref.to_dict(),project.ref.to_dict()])
        self.assertEqual(combined['metrics']['input_tokens'],10)
        self.assertEqual(combined['groups']['project'],[])
        from otto.portfolio.observability_views import ObservabilityViews
        self.store.project_history_projection().maintain(limit=1000)
        grant=ProjectHistoryGrant(self.actor,(self.project.id,),'public','v1')
        reader=ProjectHistoryReader(self.store,grant=grant);views=ObservabilityViews(reader)
        single=views.read('usage',projects=[self.project.ref],limit=50)
        self.assertEqual(single['usage']['accounting']['coverage']['limited'],1)
        self.assertIsNone(single['usage']['accounting']['metrics']);self.assertNotIn(project.id,json.dumps(single))
        self.assertNotIn('"input_tokens": 10',json.dumps(single))
        reader.grant=ProjectHistoryGrant(self.actor,(self.project.id,project.id),'public','v2')
        combined=views.read('usage',projects=[self.project.ref,project.ref],limit=50)
        self.assertEqual(combined['usage']['accounting']['metrics']['input_tokens'],10)
        self.assertEqual(combined['usage']['accounting']['groups']['project'],[])

    def test_imported_task_without_birth_event_uses_exact_admission_project(self):
        # Imported package identities predate a separate per-task event; the
        # ordinary assignment writer still captures exact validated membership.
        legacy = ResourceRef(self.project.ref.authority, 'work.task', 'imported-task', 'rev-1')
        self.store.put_identity(legacy, {**deepcopy(self.task.payload), 'project_ref': self.project.ref.to_dict(), 'parent': self.project.ref.to_dict()}, version=1)
        self.task = WorkGraph(self.store, actor=self.actor).get(legacy)
        self.assertEqual(self.store.list_events(subjects=(legacy,)), ())
        self.old = self.p.assign(legacy, role='worker', principal='historical-worker',
            agent='historical-agent', session='session', logical_request_key='imported-task-assignment')
        self.original('codex-direct')
        # A later current head cannot alter historical admission membership.
        other = WorkGraph(self.store, actor=self.actor).create_project(title='Later', logical_request_key='later-project')
        changed = {**self.task.payload, 'project_ref': other.ref.to_dict(), 'parent': other.ref.to_dict()}
        self.store.revise_identity(legacy, changed, expected_version=1, expected_revision='rev-1', revision='rev-2')
        result = self.append()
        self.assertEqual(result['association']['project_ref']['id'], self.project.id)
        self.assertEqual(result['association']['task_ref'], legacy.to_dict())
        self.assertEqual(self.append()['ref'], result['ref'])

    def test_task_admission_resolution_rejects_missing_foreign_changed_and_ambiguous(self):
        from herzchen.domains.work.usage import _admitted_task_project
        target = self.old.ref
        facet = {'schema':'fnd.history-summary.v1','coverage':'captured-pre-post',
            'after':{'exists':True,'ref':target.to_dict(),'fields':{'generation':1,'scope':self.task.ref.to_dict()}},
            'project_resolution':[{'side':'after','scope_ref':self.task.ref.to_dict(),
                                   'coverage':'validated-exact-state-at-capture'}],
            'resolved_projects':[self.project.ref.to_dict()]}
        self.assertEqual(_admitted_task_project(facet,target,self.task.ref.to_dict(),1),self.project.ref.to_dict())
        changes=[]
        for field, value in (('resolved_projects',[]),('resolved_projects',[self.project.ref.to_dict()]*2),
                             ('project_resolution',[]),('coverage','legacy-source-only')):
            value_facet=deepcopy(facet);value_facet[field]=value;changes.append(value_facet)
        for field,value in (('generation',2),('scope',{**self.task.ref.to_dict(),'id':'foreign-task'})):
            value_facet=deepcopy(facet);value_facet['after']['fields'][field]=value;changes.append(value_facet)
        value_facet=deepcopy(facet);value_facet['after']['ref']['revision']='rev-999';changes.append(value_facet)
        value_facet=deepcopy(facet);value_facet['resolved_projects'][0]['authority']='foreign';changes.append(value_facet)
        for value_facet in changes:
            with self.subTest(facet=value_facet), self.assertRaises(WorkValidationError):
                _admitted_task_project(value_facet,target,self.task.ref.to_dict(),1)

    def test_source_backed_history_facets_keep_old_snapshot_immutable(self):
        self.original('codex-direct'); self.replace()
        projection = self.store.project_history_projection(); projection.maintain(limit=1000)
        grant = ProjectHistoryGrant(self.actor, (self.project.id,), 'test', 'v1')
        reader = ProjectHistoryReader(self.store, grant=grant)
        before = reader.read(projects=[self.project.ref])
        retained = self.append(); projection.maintain(limit=1000)
        old = reader.read(projects=[self.project.ref], snapshot=before['snapshot'])
        self.assertFalse(any(r['summary']['after']['fields'].get('usage_fact') for r in old['rows']))
        new = reader.read(projects=[self.project.ref])
        usage = [r for r in new['rows'] if r['summary']['after']['fields'].get('usage_fact')]
        self.assertEqual(len(usage), 1)
        self.assertEqual(usage[0]['summary']['after']['fields']['usage_fact']['first_qualified_recorded_at'], retained['first_qualified_recorded_at'])

    def test_observed_model_requires_verified_same_work_turn_never_initializer(self):
        for phase,verified,turn,expected in (('work',True,'turn','gpt-5.6-luna'),('work',False,'turn',None),('work',True,'other',None),('initializer',True,'turn',None)):
            with self.subTest(phase=phase,verified=verified,turn=turn):
                if hasattr(self,'source_ref'):self.doCleanups();self.setUp()
                self.original('codex-host',phase=phase,anchor='2026-10-05T10:00:00Z',verified_model='gpt-5.6-luna',context_verified=verified,result_turn=turn)
                retained=self.append('codex-host',phase=phase)
                self.assertEqual(retained['observation']['observed']['model'],expected)
                self.assertEqual(self.port.read_due('schedule'),self.original_value)

    def test_native_cumulative_money_early_late_and_public_fold_agree(self):
        from otto.portfolio.observability_views import ObservabilityViews
        for cost in (0,1.25):
            with self.subTest(cost=cost):
                if hasattr(self,'source_ref'):self.doCleanups();self.setUp()
                early=self.original('claude-code',anchor='2026-10-05T10:00:00Z',money_marker=cost)
                retained=self.append('claude-code');late=retained['observation']['provider_reported_money']
                self.assertEqual(late,early['provider_reported_money']);self.assertEqual(late['status'],'zero' if cost==0 else 'usage_report_estimate')
                projection=self.store.project_history_projection();projection.maintain(limit=1000)
                grant=ProjectHistoryGrant(self.actor,(self.project.id,),'public','v1');views=ObservabilityViews(ProjectHistoryReader(self.store,grant=grant))
                page=views.read('usage',projects=[self.project.ref],limit=50)
                self.assertIsNone(page['usage']['accounting']['provider_reported']['amount'])
                money=page['usage']['accounting']['spans'][0]['provider_reported_money']
                self.assertEqual(money['reason'],'provider-money-cumulative-not-additive')
                self.assertEqual(money['observation']['amount'],str(cost))
                self.assertEqual(self.port.read_due('schedule'),self.original_value)
                event=json.loads(self.source_line);event['total_cost_usd']=cost+1
                source=self.bodies.retain(json.dumps(event),project_ref=self.project.ref,task_ref=self.task.ref.to_dict(),attempt_ref=self.manager.ref.to_dict())
                self.append('claude-code',key='money-conflict',source=source);projection.maintain(limit=1000)
                conflict=views.read('usage',projects=[self.project.ref],limit=50)['usage']['accounting']
                self.assertIsNone(conflict['provider_reported']['amount']);self.assertEqual(conflict['provider_reported']['span_count'],0)
                self.assertIn('provider-money-conflict',conflict['coverage']['monetary']['provider_money_exclusion_reasons'])

    def test_public_usage_and_detail_fold_late_facts_at_original_anchor(self):
        from otto.portfolio.observability_views import ObservabilityViews
        self.original('codex-host',anchor='2026-10-05T10:00:00Z',metrics={'input_tokens':10,'cached_input_tokens':0,'output_tokens':2},verified_model='gpt-5.6-luna',context_verified=True)
        projection=self.store.project_history_projection();projection.maintain(limit=1000)
        grant=ProjectHistoryGrant(self.actor,(self.project.id,),'public','v1');reader=ProjectHistoryReader(self.store,grant=grant);views=ObservabilityViews(reader)
        args={'projects':[self.project.ref],'from_at':'2026-10-05T00:00:00Z','to_at':'2026-10-06T00:00:00Z','limit':50}
        old=views.read('usage',**args);retained=self.append('codex-host');projection.maintain(limit=1000)
        preserved=views.read('usage',snapshot=old['snapshot'],**args);self.assertEqual(preserved['snapshot'],old['snapshot']);self.assertEqual(preserved['rows'],old['rows']);self.assertNotIn('accounting',preserved['usage'])
        new=views.read('usage',**args);accounting=new['usage']['accounting'];self.assertEqual(accounting['metrics']['input_tokens'],10)
        self.assertEqual(accounting['pricing']['status'],'estimated');self.assertEqual(accounting['coverage']['totals'],'exact-window')
        span=accounting['spans'][0];self.assertEqual(span['first_qualified_recorded_at'],'2026-10-05T10:00:00Z');self.assertEqual(span['provider_reported_money']['status'],'missing')
        row=next(r for r in new['rows']if r['subject_ref']==retained['ref']);detail=views.detail(row['facet_id'],snapshot=new['snapshot'],projects=[self.project.ref.to_dict()]);self.assertEqual(detail['usage']['pricing']['status'],'estimated')
        timeline=views.read('timeline',projects=[self.project.ref],from_at='2026-10-05T00:00:00Z',to_at='2026-10-06T00:00:00Z');self.assertFalse(any(r['subject_ref']==retained['ref']for r in timeline['rows']))
        with self.assertRaises(Exception):views.read('timeline',snapshot=new['snapshot'],**args)
        # A changed grant cannot reuse a formerly authorized snapshot.
        reader.grant=ProjectHistoryGrant(self.actor,('foreign-project',),'public','v2')
        from herzchen.kernel.project_history import AuthorizationError
        with self.assertRaises(AuthorizationError):views.read('usage',snapshot=new['snapshot'],**args)

    def test_public_partial_correction_page_never_invents_new_span_total(self):
        from otto.portfolio.observability_views import ObservabilityViews
        self.original('codex-host',anchor='2026-10-05T10:00:00Z',metrics={'input_tokens':10,'cached_input_tokens':0,'output_tokens':2},verified_model='gpt-5.6-luna',context_verified=True)
        first=self.append('codex-host')
        correction_source=self.bodies.retain(json.dumps(native('codex-host',{'input_tokens':20,'output_tokens':2})[-1]),project_ref=self.project.ref,task_ref=self.task.ref.to_dict(),attempt_ref=self.old.ref.to_dict())
        second=self.append('codex-host',key='corrected',source=correction_source,supersedes=first['ref']);self.store.project_history_projection().maintain(limit=1000)
        reader=ProjectHistoryReader(self.store,grant=ProjectHistoryGrant(self.actor,(self.project.id,),'public','v1'));views=ObservabilityViews(reader)
        args={'projects':[self.project.ref],'from_at':'2026-10-05T00:00:00Z','to_at':'2026-10-06T00:00:00Z','limit':1}
        page=views.read('usage',**args);self.assertEqual(page['usage']['accounting']['coverage']['totals'],'page-only');self.assertEqual(page['usage']['accounting']['metrics']['input_tokens'],10)
        nextpage=views.read('usage',snapshot=page['snapshot'],cursor=page['continuation']['next_cursor'],**args);self.assertIsNone(nextpage['usage']['accounting']['metrics']);self.assertEqual(nextpage['usage']['accounting']['coverage']['totals'],'unavailable')
        complete=views.read('usage',**{**args,'limit':50});self.assertEqual(complete['usage']['accounting']['metrics']['input_tokens'],20);self.assertEqual(complete['usage']['accounting']['coverage']['totals'],'exact-window')


if __name__ == '__main__': unittest.main()
