"""Reviewer reports do not execute; current manager dispositions author pending work."""
import argparse
import copy
import unittest
from herzchen.contracts import ResourceRef
from otto.portfolio.manager_journey_client import add_manager_journey_parsers
from otto.portfolio.manager_journey_command import ManagerJourneyCommands
from tests import test_local_assessment_composition as local

class ManagerCorrectionPlanningTests(unittest.TestCase):
    def setUp(self):
        self.fixture = local.LocalAssessmentCompositionTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.f = self.fixture.f
        self.commands = ManagerJourneyCommands(owner=self.f.owner, portfolio=self.f.app.portfolio, state=self.fixture.state)
        self.report = self.f.owner.assignments.command_port.append_report(self.fixture.manager.ref,
            {"findings": [{"id": "F1", "correction": "Protect exact task scope", "route": "normal"}]},
            expected_generation=1, logical_request_key="review-evidence", actor=self.f.actor)

    def request(self):
        return {"command": "task-list-author", "request_key": "correction-plan", "base_revision": self.fixture.state["project_ref"]["revision"],
            "review_ref": self.report.ref.to_dict(),
            "dispositions": [{"finding_id": "F1", "decision": "accept", "reason": "Supported in-scope defect", "task": "FIX01", "route": "normal", "routing_rationale": "Bounded change with decisive regression"}],
            "tasks": [{"alias": "FIX01", "title": "Protect exact task scope", "instructions": "Implement supported correction", "acceptance": "Reject foreign scope", "lifecycle": "pending"}]}

    def test_report_to_pending_correction_replays_and_maps_without_grants(self):
        request = self.request()
        policy = copy.deepcopy(self.fixture.state["assessment_policy"])
        oldtasks = copy.deepcopy(self.fixture.state["task_refs"])
        first = self.commands.author_tasks(request)
        self.assertEqual(first["outcome"], "authored", first)
        ref = ResourceRef.from_dict(self.fixture.state["task_refs"]["FIX01"])
        task = self.f.owner.graph.reader.get_identity(ref)
        self.assertEqual(task.payload["lifecycle"], "pending")
        self.assertFalse(first["dispatch"])
        self.assertFalse(first["assessment_authority_granted"])
        self.assertEqual(self.fixture.state["assessment_policy"], policy)
        self.assertEqual({k:self.fixture.state["task_refs"][k] for k in oldtasks}, oldtasks)
        counts = self.f.owner.graph.reader.snapshot_counts()
        self.assertEqual(self.commands.author_tasks(request), first)
        self.assertEqual(self.f.owner.graph.reader.snapshot_counts(), counts)
        self.assertEqual(self.f.provider.calls, [])
        with self.assertRaises(ValueError): self.commands.author_tasks({**request, "tasks": []})

    def test_wrong_manager_generation_and_foreign_report_fail_before_effects(self):
        request = self.request()
        counts = self.f.owner.graph.reader.snapshot_counts()
        self.fixture.state["manager_generation"] = 2
        with self.assertRaises(PermissionError): self.commands.author_tasks(request)
        self.fixture.state["manager_generation"] = 1
        project = self.f.owner.graph.create_project(title="foreign", logical_request_key="foreign")
        assignment = self.f.owner.assignments.command_port.assign(project.ref, role="manager", principal="foreign", logical_request_key="foreign-manager", actor=self.f.actor)
        report = self.f.owner.assignments.command_port.append_report(assignment.ref, {"findings": []}, expected_generation=1, logical_request_key="foreign-report", actor=self.f.actor)
        counts = self.f.owner.graph.reader.snapshot_counts()
        with self.assertRaises(PermissionError): self.commands.author_tasks({**request, "review_ref": report.ref.to_dict()})
        self.assertEqual(self.f.owner.graph.reader.snapshot_counts(), counts)

    def test_protected_authority_and_activation_rejected_before_journal(self):
        for extra in ({"budget": 10}, {"accepted": True}, {"lifecycle": "active"}):
            request = self.request(); request["tasks"][0].update(extra)
            counts = self.f.owner.graph.reader.snapshot_counts()
            with self.assertRaises(ValueError): self.commands.author_tasks(request)
            self.assertEqual(self.f.owner.graph.reader.snapshot_counts(), counts)

    def test_manager_can_defer_or_reject_without_creating_work(self):
        request = self.request(); request["tasks"] = []
        request["dispositions"] = [{"finding_id":"F1", "decision":"defer", "reason":"Real prerequisite", "revisit":"After installed proof"},
                                   {"finding_id":"F2", "decision":"reject", "reason":"Completed finding superseded by exact passing proof"}]
        tasks = copy.deepcopy(self.fixture.state["task_refs"])
        result = self.commands.author_tasks(request)
        self.assertEqual(result["task_count"], 0)
        self.assertEqual(self.fixture.state["task_refs"], tasks)
        self.assertFalse(result["provider_called"])

    def test_merge_by_canonical_id_refreshes_existing_alias_without_reopening(self):
        request=self.request()
        old=self.fixture.state["task_refs"]["PA01"]
        request["tasks"]=[{"id":old["id"],"instructions":"Bounded correction in existing pending work","lifecycle":"pending"}]
        request["dispositions"][0].update(decision="merge",task="PA01",route="xhard",routing_rationale="Irreducible subtle dependency reasoning")
        result=self.commands.author_tasks(request)
        self.assertEqual(result["outcome"],"authored",result)
        self.assertEqual(self.fixture.state["task_refs"]["PA01"]["id"],old["id"])
        self.assertNotEqual(self.fixture.state["task_refs"]["PA01"]["revision"],old["revision"])
        self.assertEqual(self.fixture.state["task_refs"]["PA01"],self.fixture.state["task_refs"][old["id"]])
        self.assertEqual(result["dispositions"][0]["route"],"xhard")

    def test_created_task_has_no_existing_assessment_authority_and_reviewer_cannot_author(self):
        from otto.portfolio.local_assessment_policy import LocalAssessmentPolicy
        from otto.portfolio.manager_journey_service import ManagerJourneyService
        from types import SimpleNamespace
        self.commands.author_tasks(self.request())
        state = self.fixture.state
        policy = LocalAssessmentPolicy.from_run_config(state["assessment_policy"], state=state)
        counts = self.f.owner.graph.reader.snapshot_counts()
        with self.assertRaises(PermissionError):
            policy.validate_binding(ResourceRef.from_dict(state["project_ref"]),
                ResourceRef.from_dict(state["task_refs"]["FIX01"]), self.f.owner.graph.reader)
        service = ManagerJourneyService.__new__(ManagerJourneyService)
        service.server = SimpleNamespace(state=state)
        service.commands = self.commands
        context = {"role":"reviewer", "principal":state["manager"], "assignment_ref":state["assignment_ref"], "generation":1}
        with self.assertRaises(PermissionError): service.authorize_caller(context, self.request())
        self.assertEqual(self.f.owner.graph.reader.snapshot_counts(), counts)

    def test_delivered_parser_exposes_exact_typed_operation(self):
        parser=argparse.ArgumentParser(); sub=parser.add_subparsers(dest="command");add_manager_journey_parsers(sub)
        result=vars(parser.parse_args(['task-list-author','--request-key','k','--base-revision','r','--review-ref','{}','--dispositions','[]','--tasks','[]']))
        self.assertEqual(result['command'],'task-list-author');self.assertEqual(result['tasks'],[])

    def test_canonical_pending_authoring_is_pumped_on_same_owner_thread(self):
        import json, tempfile, threading, time
        from pathlib import Path
        from otto.portfolio.execution_host import ExecutionHost
        request=self.request(); threads={}; ready=threading.Event()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            def handler(value):
                if value['command']=='start-manager':
                    threads['owner']=threading.get_ident()
                    def native():
                        threads['native']=threading.get_ident()
                        (root/'request-1111.json').write_text(json.dumps(request))
                        deadline=time.monotonic()+4
                        while time.monotonic()<deadline:
                            if (root/'response-1111.json').exists():
                                result=json.loads((root/'response-1111.json').read_text())
                                self.assertEqual(result['outcome'],'authored',result)
                                ready.set();return {'outcome':'succeeded'}
                            time.sleep(.01)
                        raise AssertionError('pending task authoring self-waited')
                    return ExecutionHost.external_call(native)
                threads['planning']=threading.get_ident()
                return self.commands.author_tasks(value)
            host=ExecutionHost(directory=root,handler=handler)
            try:
                host.start();(root/'request-aaaa.json').write_text(json.dumps({'command':'start-manager'}))
                self.assertTrue(ready.wait(6))
                self.assertEqual(threads['owner'],threads['planning'])
                self.assertNotEqual(threads['native'],threads['planning'])
                self.assertIn('FIX01',self.fixture.state['task_refs'])
            finally:host.close()
