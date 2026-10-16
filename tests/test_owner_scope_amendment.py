import unittest
from dataclasses import replace
from herzchen.contracts import ResourceRef
from herzchen.domains.assessment import AssessmentModule, AssessmentError, contribution
from herzchen.domains.work import WorkGraph
from otto.portfolio.tests import test_portfolio_direction as fixtures


class OwnerScopeAmendmentTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.PortfolioDirectionTests(); self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.actor = self.f.actor
        self.graph = WorkGraph(self.f.store, actor=self.actor)
        self.root, _, _, self.project = self.f.setup_portfolio()
        self.initial_task = self.graph.create_task(self.project.ref,title='Original requirement',logical_request_key='amend-task')
        self.f.store.register_domain_handler((contribution(),))
        self.assessment = AssessmentModule(self.f.store, actor=self.actor)
        catalogue = self.assessment.declare_scope('catalogue', parent_obligation=self.project.ref,
            protocol='criteria', criteria=[{'id':'before'}, {'id':'after'}], logical_request_key='catalogue')
        self.before, self.after = catalogue.criterion_refs
        self.scope = self.assessment.declare_scope('required', parent_obligation=self.initial_task.ref,
            protocol='ordinary-manager-judgment', criteria=[self.before], designated_approver='manager',
            authority=self.actor.authority, policy={'required_for_completion':True}, logical_request_key='scope')
        batch = self.f.owner.sheet.apply(self.project.ref, {'tasks':[{'id':self.initial_task.id,
            'outcome':'Mechanical only; no paid provider calls', 'acceptance':['after']}]},
            logical_request_key='changed-owner-task', actor=self.actor)
        self.task = self.graph.current(self.initial_task.ref)
        self.key = 'owner-scope-amendment'

    def authorization(self, **changes):
        value = {'schema':'otto.owner-scope-amendment.v1', 'scope_ref':self.scope.ref.to_dict(),
                 'task_ref':self.task.ref.to_dict(), 'criterion_refs':[self.after.to_dict()],
                 'request_key':self.key, 'logical_request_key':'scope-authority', 'reason':'Explicit changed owner requirement'}
        value.update(changes)
        return self.f.owner.assignments.command_port.append_report(self.root.ref,value,
            expected_generation=1,logical_request_key=value['logical_request_key'],actor=self.actor).ref

    def call(self, authority=None, **changes):
        args={'parent_obligation':self.task.ref,'criteria':[self.after],
              'owner_authorization':authority or self.authorization(), 'logical_request_key':self.key,'actor':self.actor}
        args.update(changes)
        return self.assessment.amend_required_scope(self.scope.ref,**args)

    def test_same_gate_revision_idempotent_and_old_pins_preserved(self):
        authority=self.authorization(); first=self.call(authority); second=self.call(authority)
        self.assertEqual(first.ref,second.ref);self.assertEqual(first.ref.id,self.scope.ref.id)
        self.assertNotEqual(first.ref,self.scope.ref);self.assertEqual(first.parent_obligation_ref,self.task.ref)
        self.assertEqual(first.criterion_refs,(self.after,));self.assertEqual(first.designated_approver,'manager')
        self.assertTrue(first.policy['required_for_completion'])
        with self.assertRaises(AssessmentError):self.assessment.get_scope(self.scope.ref)
        gate=self.assessment.completion_blockers(self.task.ref)
        self.assertEqual(gate['scope_refs'],[first.ref.to_dict()])
        self.assertIsNotNone(self.f.store.consumer().get_reference(self.scope.ref))
        self.assertEqual(first.policy,self.scope.policy)

    def test_foreign_actor_cannot_use_root_report(self):
        with self.assertRaises(AssessmentError):self.call(actor=self.f.binding.authenticated_actor("foreign"))

    def test_owner_report_must_match_complete_changed_pins(self):
        authority=self.authorization(criterion_refs=[self.before.to_dict()])
        with self.assertRaises(AssessmentError):self.call(authority)

    def test_stale_or_foreign_scope_and_task_rejected(self):
        authority=self.authorization();self.call(authority)
        with self.assertRaises(AssessmentError):self.call(authority,logical_request_key='different-key')
        other=self.graph.create_task(self.project.ref,title='Other',logical_request_key='other')
        with self.assertRaises(AssessmentError):self.call(authority,parent_obligation=other.ref)

    def test_current_completed_task_rejected(self):
        authority=self.authorization()
        self.graph.revise(self.task.ref,lifecycle='completed',logical_request_key='complete')
        with self.assertRaises(AssessmentError):self.call(authority,parent_obligation=self.graph.current(self.task.ref).ref)

if __name__=='__main__':unittest.main()
