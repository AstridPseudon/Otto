"""Sessionless manager: public setup, bound help return and new continuation.

Only the native provider is substituted. The initial known native session is
issued through the maintained owner bootstrap preparation composition.
"""
import unittest
from dataclasses import replace
from types import SimpleNamespace
from otto.portfolio.operating_setup import evaluate_setup
from tests import test_execution_application as owner_fixture
from otto.attention import DueRecord
from otto.portfolio.execution_operations import prepare_current_assignment_occurrence
from otto.portfolio.help_delivery import BoundHelpDelivery
from otto.portfolio.owner_issue_loop import OwnerIssueReaders


class MissingSetupReturnTests(unittest.TestCase):
    def test_public_setup_binds_return_without_replaying_old_unknown(self):
        f = owner_fixture.ExecutionApplicationTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        manager, guide, mandate = f.role_handles('manager', 'manager', None)
        root, _, _ = f.role_handles('orchestrator', 'root', 'root-session')
        project = f.project.ref.to_dict()
        binding = {'project_ref': project, 'assignment_ref': root.ref.to_dict(),
                   'generation': 1, 'principal': 'root',
                   'conversation_ref': {'host': 'codex', 'native_id': 'root-session'}}
        delivery = BoundHelpDelivery(readers=OwnerIssueReaders(f.owner.consumer_operations(), f.port),
                                     interim_supervision=binding)
        portfolio = f.owner.portfolio(due_port=f.port, issue_delivery=delivery)
        f.app.portfolio = f.app.runtime.portfolio = portfolio
        target = {'host': 'local', 'native_id': 'manager-session', 'project_ref': project,
                  'task_ref': f.task.ref.to_dict(), 'assignment_ref': manager.ref.to_dict(),
                  'mandate_ref': mandate, 'role': 'manager', 'principal': 'manager',
                  'requested_model': 'gpt-test', 'requested_reasoning': 'high',
                  'requested_profile': 'workspace-write'}
        due = DueRecord(schedule_id='manual-bootstrap', recipient='manager', instruction='Advance project',
            profile='workspace-write', anchor=owner_fixture.NOW.isoformat(), due_at=owner_fixture.NOW.isoformat(), last_covered_slot=0,
            invocation_identity='fixture-bootstrap', in_flight_request='fixture-bootstrap', delivery_state='ready',
            owner='manager', project_ref=f.project.id, manager_ref='manager', assignment_ref=manager.ref.to_dict(),
            generation=1, target=target, role='manager', purpose='role-execution', lifecycle_owner='manager',
            execution_mode='continue_existing', requested_model='gpt-test', requested_reasoning='high',
            context_refs=(guide, mandate), result_owner='manager', timeout_seconds=1200)
        prepared = prepare_current_assignment_occurrence(due_port=f.port,
            assignments=f.owner.assignments.command_port, binding=f.binding, due=due,
            assignment_ref=manager.ref.to_dict(), assignment_owner='manager', operation='resume',
            lifecycle='resume', request_key='fixture-bootstrap')
        self.assertEqual(prepared['outcome'], 'committed')
        self.assertEqual(f.app.start(schedule_id=due.schedule_id)['outcome'], 'succeeded')

        def reply(key):
            issue = portfolio.submit_issue(project_ref=project, assignment_ref=manager.ref.to_dict(),
                generation=1, actor='manager', issue_key=key, problem='Need route', impact='Held', evidence=[],
                requested_decision='Owner decision', return_condition='Applied', request_id=key)
            request = {'command': 'respond-help', 'request_key': key + ':reply', 'issue_id': issue['issue_id'],
                'authority_source': 'Owner binding', 'response': 'Verified decision',
                'proposed_solution': 'Use route', 'next_action': 'Continue'}
            # The trusted host authenticates root independently of the reply.
            actor = f.binding.authenticated_actor('root')
            result = portfolio.respond_to_issue(project_ref=project, issue_id=issue['issue_id'], actor=actor.actor,
                authority_source=request['authority_source'], response=request['response'],
                proposed_solution=request['proposed_solution'], next_action=request['next_action'],
                request_id=request['request_key'])
            return issue, request, result

        old_issue, _, old = reply('before-setup')
        self.assertEqual(old['delivery']['state'], 'unknown')
        self.assertEqual(old['delivery']['error'], 'help delivery recipient or real conversation is stale')
        self.assertIsNone(delivery.readers.conversation(project, manager))
        calls = len(f.provider.calls)
        setup = {'schema': 'otto.operating-setup.v1', 'mode': 'manual', 'roles': {'manager': due.schedule_id},
                 'advisor_policy': {'mode': 'disabled', 'reason': 'No advisor authorized'}, 'acceptance_tasks': []}
        result = f.app.prepare_operating_setup(project_ref=project, setup=setup, request_key='adopt-current-setup')
        self.assertEqual(result['outcome'], 'prepared', result)
        self.assertEqual(len(f.provider.calls), calls)
        self.assertEqual(delivery.readers.conversation(project, manager), 'manager-session')
        new_issue, _, new = reply('after-setup')
        self.assertEqual(new['delivery']['state'], 'pending')
        self.assertEqual(new['delivery']['receipt']['conversation_id'], 'manager-session')
        self.assertFalse(new['delivery']['receipt']['notification_sent'])
        prepared = f.app.continue_manager_from_help(manager_schedule_id=due.schedule_id,
            report_ref=new['report_ref'], execute=False)
        callback = f.app._read(prepared['schedule_id'])
        self.assertNotIn('gateway_attempt', callback.host_evidence or {})
        current = replace(callback, requested_model='gpt-current',
            target={**callback.target, 'requested_model': 'gpt-current'})
        decision = evaluate_setup(f.app.runtime, project, setup, current_due=current)
        self.assertTrue(decision['ready'], decision)
        self.assertEqual(decision['roles']['manager']['execution']['model'], 'gpt-current')
        anchor = f.port.read_due(due.schedule_id)
        # Each guard is checked on a read-only projection; no owner history or
        # provider attempt is rewritten to manufacture the negative cases.
        mutations = {
            'generation': {**anchor, 'generation': 2},
            'native': {**anchor, 'target': {**anchor['target'], 'native_id': 'different'}},
            'principal': {**anchor, 'recipient': 'different'},
            'owner': {**anchor, 'lifecycle_owner': 'different'},
            'project': {**anchor, 'project_ref': 'different'},
            'missing-admission': {**anchor, 'host_evidence': {}},
        }
        for name, changed in mutations.items():
            with self.subTest(name=name):
                port = SimpleNamespace(read_due=lambda schedule, value=changed: value)
                runtime = SimpleNamespace(adapter=f.app.runtime.adapter, actor=f.app.runtime.actor,
                    due_port=port, prepare_execution_readiness=f.app.runtime.prepare_execution_readiness,
                    portfolio=portfolio, operations=f.app.runtime.operations)
                self.assertFalse(evaluate_setup(runtime, project, setup, current_due=callback)['ready'])
        self.assertEqual(f.port.read_due(due.schedule_id), anchor)
        self.assertEqual(len(f.provider.calls), calls)
        continued = f.app.recover(schedule_id=callback.schedule_id, execute=True)
        self.assertEqual(continued['outcome'], 'succeeded', continued)
        issues = portfolio.read_issues(project_ref=project)['issues']
        old_history = next(i for i in issues if i['issue_id'] == old_issue['issue_id'])['deliveries']
        self.assertEqual([x['state'] for x in old_history if x['delivery_id'] == old['delivery']['delivery_id']],
                         ['intent', 'unknown'])
        self.assertEqual(len(f.provider.calls), calls + 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
