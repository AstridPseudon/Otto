"""Task admission: a reviewer's pin on the exact revision a dispatch may use.

The project's user (USER) creates the project; a different actor (AGENT) edits
the task. Content edits by AGENT leave the task unadmitted until USER admits the
exact reviewed revision; USER's own edits are admitted by being made.
"""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import json
import tempfile
import types
import unittest
from collections.abc import Mapping

from herzchen.contracts import AuthenticatedActor, ResourceRef, TransactionContext
from herzchen.content import ContentCommandHandler, ContentDocument, ContentRevision, domain_contribution
from herzchen.domains.assessment import AssessmentModule
from herzchen.domains.work import WorkGraph, contributions
from herzchen.domains.work.admission import AdmissionDiffError, TaskNotAdmittedError
from herzchen.domains.work.assignments import ResponsibilityAssignments
from herzchen.domains.work.model import Lifecycle
from herzchen.kernel.store import Store
from otto.portfolio import cli
from otto.portfolio.tests import test_reviewed_activation as reviewed_fixture
from tests import test_execution_application as owner_fixture


AUTHORITY = "owner"
USER = AuthenticatedActor(AUTHORITY, "user", "user-credential")
AGENT = AuthenticatedActor(AUTHORITY, "agent", "agent-credential")


DEFAULT_REVIEW = object()


def unpinned(ref):
    return ResourceRef(ref.authority, ref.kind, ref.id)


def revision_of(value):
    return value["revision"] if isinstance(value, Mapping) else value.revision


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="admit-test-")
        self.addCleanup(self.temporary.cleanup)
        self.store = Store.create(Path(self.temporary.name) / "admit.sqlite", authority=AUTHORITY)
        self.addCleanup(self.store.close)
        self.store.register_domain_handler(contributions())
        self.graph = WorkGraph(self.store)
        self.assignments = ResponsibilityAssignments(self.store, actor=USER).command_port
        self.project = self.graph.create_project(title="Admission", logical_request_key="project", actor=USER)
        self.task = self.graph.create_task(self.project, title="Plan", logical_request_key="task", actor=USER)
        self.review = self.graph.create_effort(self.project, title="Review", logical_request_key="review", actor=USER)

    # ---- helpers -----------------------------------------------------------------

    def task_ref(self):
        return unpinned(self.task.ref)

    def current_task(self):
        return self.graph.get(self.task_ref())

    def agent_revise(self, title, key):
        return self.graph.revise(self.task_ref(), title=title, actor=AGENT, logical_request_key=key)

    def assign_task(self, scope=None, key="assign-task"):
        return self.assignments.assign(scope if scope is not None else self.task_ref(), role="worker",
                                       principal="worker", logical_request_key=key, actor=USER)

    def admit(self, revision, *, key, review=DEFAULT_REVIEW, actor=USER, disposition="approved"):
        return self.graph.admit(self.task_ref(), revision=revision,
                                review_ref=self.review.ref if review is DEFAULT_REVIEW else review,
                                disposition=disposition, logical_request_key=key, actor=actor)

    def dispatch_events(self, assignment):
        return tuple(self.store.list_events(stream="dispatch:" + assignment.id))

    def revised_event_ids(self):
        return [event.event_id for event in self.store.list_events(stream="work:" + self.task.id)
                if event.event_type == "work.revised"]

    # ---- tests -------------------------------------------------------------------

    def test_unadmitted_agent_revision_refused_then_admit_recovers(self):
        assignment = self.assign_task()
        revised = self.agent_revise("Plan revised by agent", "agent-1")
        self.assertNotEqual(revised.revision, self.task.revision)
        with self.assertRaises(TaskNotAdmittedError):
            self.assignments.dispatch(assignment, logical_request_key="d1", actor=AGENT)
        outcome = self.admit(revised.revision, key="a1")
        self.assertEqual(outcome["outcome"], "admitted")
        self.assignments.dispatch(assignment, logical_request_key="d2", actor=AGENT)
        events = self.dispatch_events(assignment)
        self.assertEqual(len(events), 1)
        admitted = events[0].effects["admitted_task"]
        self.assertEqual(revision_of(admitted), revised.revision)
        self.assertNotEqual(revision_of(admitted), self.current_task().revision)

    def test_admit_refuses_unreviewed_agent_revision(self):
        revised = self.agent_revise("Plan revised by agent", "agent-1")
        with self.assertRaises(TaskNotAdmittedError):
            self.admit(revised.revision, key="a-none", review=None)
        with self.assertRaises(TaskNotAdmittedError):
            self.admit(revised.revision, key="a-rejected", disposition="rejected")
        with self.assertRaises(TaskNotAdmittedError):
            self.admit(revised.revision, key="a-agent", actor=AGENT)
        with self.assertRaises(TaskNotAdmittedError):
            self.admit(revised.revision, key="a-unpinned-review", review=unpinned(self.review.ref))
        self.assertIsNone(self.graph.admission_state(self.task_ref())["admitted_revision"])

    def test_admit_requires_stored_review_revision_after_review_advances(self):
        task = self.agent_revise("Agent plan", "agent-plan")
        retained_review = self.review.ref
        later_review = self.graph.revise(
            unpinned(retained_review), title="Review updated",
            logical_request_key="review-updated", actor=USER)
        self.assertNotEqual(later_review.revision, retained_review.revision)
        self.assertEqual(self.store.get_revision(retained_review).ref, retained_review)

        missing_review = ResourceRef(
            retained_review.authority, retained_review.kind,
            retained_review.id, "rev-999999")
        self.assertIsNone(self.store.get_revision(missing_review))
        before = self.graph.admission_state(self.task_ref())
        self.assertIsNone(before["admitted_revision"])
        writes = self.revised_event_ids()

        with self.assertRaisesRegex(TaskNotAdmittedError, "exact stored revision"):
            self.admit(task.revision, key="missing-review-revision",
                       review=missing_review)

        self.assertEqual(self.revised_event_ids(), writes)
        self.assertEqual(self.graph.admission_state(self.task_ref()), before)
        self.assertIsNone(self.store.get_receipt("missing-review-revision"))

        admitted = self.admit(
            task.revision, key="retained-review-revision",
            review=retained_review)
        self.assertEqual(admitted["outcome"], "admitted")
        self.assertEqual(admitted["stamp"]["review_ref"],
                         retained_review.to_dict())

    def test_admit_accepts_retained_dat_review_revision(self):
        self.store.register_domain_handler((domain_contribution(),))
        content = ContentCommandHandler(self.store)
        document = ContentDocument(
            ResourceRef(AUTHORITY, "dat.content.document", "review-doc"),
            "review", "private", "append", "user")
        first = ContentRevision(document.ref, "rev-1", {"disposition": "approved"}, USER, initial=True)
        content.execute(content.build_create_document(
            TransactionContext(USER, "review-doc-create", "a" * 64), document, first))
        retained_review = first.ref
        second = ContentRevision(document.ref, "rev-2", {"disposition": "approved", "note": "updated"},
                                 USER, parent_revision="rev-1")
        content.execute(content.build_append_revision(
            TransactionContext(USER, "review-doc-update", "b" * 64, expected_revision="rev-1"),
            document, second))
        self.assertEqual(content.read(retained_review)["content"], {"disposition": "approved"})

        task = self.agent_revise("Agent plan", "agent-plan-dat")
        admitted = self.admit(task.revision, key="retained-dat-review", review=retained_review)
        self.assertEqual(admitted["outcome"], "admitted")
        self.assertEqual(admitted["stamp"]["review_ref"], retained_review.to_dict())

    def test_user_edit_admitted_by_authoring(self):
        assignment = self.assign_task()
        state = self.graph.admission_state(self.task_ref())
        self.assertEqual(state["stamp"]["basis"], "authoring")
        self.assertEqual(state["admitted_revision"], self.task.revision)
        self.assignments.dispatch(assignment, logical_request_key="d-0", actor=AGENT)
        for index, title in enumerate(("Plan, second", "Plan, third"), start=1):
            record = self.graph.revise(self.task_ref(), title=title, actor=USER,
                                       logical_request_key="user-edit-" + str(index))
            state = self.graph.admission_state(self.task_ref())
            self.assertEqual(state["stamp"]["basis"], "authoring")
            self.assertEqual(state["admitted_revision"], record.revision)
            self.assignments.dispatch(assignment, logical_request_key="d-" + str(index), actor=AGENT)
        events = self.dispatch_events(assignment)
        self.assertEqual(len(events), 3)
        self.assertEqual(revision_of(events[-1].effects["admitted_task"]), self.current_task().revision)

    def test_lost_reply_then_replay_resumes_without_duplicates(self):
        assignment = self.assign_task()
        revised = self.agent_revise("Agent plan", "agent-1")
        first = self.admit(revised.revision, key="a1")
        self.assertEqual(first["outcome"], "admitted")
        writes = self.revised_event_ids()
        replay = self.admit(revised.revision, key="a1")
        self.assertEqual(replay["outcome"], "replayed")
        self.assertEqual(self.revised_event_ids(), writes)
        other = self.admit(revised.revision, key="a2")
        self.assertEqual(other["outcome"], "already-admitted")
        self.assertEqual(self.revised_event_ids(), writes)
        once = self.assignments.dispatch(assignment, logical_request_key="d-once", actor=AGENT)
        again = self.assignments.dispatch(assignment, logical_request_key="d-once", actor=AGENT)
        self.assertEqual(once.ref, again.ref)
        self.assertEqual(len(self.dispatch_events(assignment)), 1)

    def test_changed_sheet_is_refused_with_the_diff(self):
        reviewed = self.agent_revise("Plan A", "agent-a")
        self.agent_revise("Plan B", "agent-b")
        with self.assertRaises(AdmissionDiffError) as raised:
            self.admit(reviewed.revision, key="a-diff")
        diff = raised.exception.diff
        self.assertIn("title", diff)
        self.assertEqual(diff["title"], {"reviewed": "Plan A", "current": "Plan B"})
        self.assertIsNone(self.graph.admission_state(self.task_ref())["admitted_revision"])

    def test_admit_n_then_author_n_plus_1_is_never_used(self):
        assignment = self.assign_task()
        n = self.agent_revise("Plan N", "agent-n")
        self.assertEqual(self.admit(n.revision, key="a-n")["outcome"], "admitted")
        early = self.assignments.dispatch(assignment, logical_request_key="d-early", actor=AGENT)
        n1 = self.agent_revise("Plan N plus one", "agent-n1")
        self.assertNotEqual(n1.revision, n.revision)
        with self.assertRaises(TaskNotAdmittedError):
            self.assignments.dispatch(assignment, logical_request_key="d-new", actor=AGENT)
        with self.assertRaises(TaskNotAdmittedError):
            self.assignments.dispatch(assignment, logical_request_key="d-new", actor=AGENT)
        unpinned_assignment = self.assign_task(key="assign-unpinned-2")
        with self.assertRaises(TaskNotAdmittedError):
            self.assignments.dispatch(unpinned_assignment, logical_request_key="d-unpinned", actor=AGENT)
        pinned_assignment = self.assign_task(scope=n1.ref, key="assign-pinned-n1")
        with self.assertRaises(TaskNotAdmittedError):
            self.assignments.dispatch(pinned_assignment, logical_request_key="d-pinned", actor=AGENT)
        replayed = self.assignments.dispatch(assignment, logical_request_key="d-early", actor=AGENT)
        self.assertEqual(replayed.ref, early.ref)
        events = self.dispatch_events(assignment)
        self.assertEqual(len(events), 1)
        self.assertEqual(revision_of(events[0].effects["admitted_task"]), n.revision)
        review_two = self.graph.create_effort(self.project, title="Review two", logical_request_key="review-two", actor=USER)
        self.assertEqual(self.admit(n1.revision, key="a-n1", review=review_two.ref)["outcome"], "admitted")
        self.assignments.dispatch(assignment, logical_request_key="d-late", actor=AGENT)
        events = self.dispatch_events(assignment)
        self.assertEqual(len(events), 2)
        self.assertEqual(revision_of(events[-1].effects["admitted_task"]), n1.revision)

    def test_non_content_changes_keep_admission(self):
        assignment = self.assign_task()
        revised = self.agent_revise("Agent plan", "agent-1")
        self.admit(revised.revision, key="a1")
        before = self.graph.admission_state(self.task_ref())
        self.assertEqual(before["admitted_revision"], revised.revision)
        self.graph.set_readiness(self.task_ref(), {"ready": True, "status": "passed"},
                                 logical_request_key="ready-1", actor=AGENT)
        self.graph.set_lifecycle(self.task_ref(), Lifecycle.ACTIVE, logical_request_key="life-1", actor=AGENT)
        after = self.graph.admission_state(self.task_ref())
        self.assertEqual(after["admitted_revision"], revised.revision)
        self.assignments.dispatch(assignment, logical_request_key="d-after", actor=AGENT)
        events = self.dispatch_events(assignment)
        self.assertEqual(len(events), 1)
        self.assertEqual(revision_of(events[0].effects["admitted_task"]), revised.revision)

    def test_project_scoped_assignment_is_not_gated(self):
        self.agent_revise("Agent plan", "agent-1")
        self.assertIsNone(self.graph.admission_state(self.task_ref())["admitted_revision"])
        assignment = self.assignments.assign(self.project.ref, role="worker", principal="worker",
                                             logical_request_key="assign-project", actor=USER)
        self.assignments.dispatch(assignment, logical_request_key="d-project", actor=AGENT)
        events = self.dispatch_events(assignment)
        self.assertEqual(len(events), 1)
        self.assertNotIn("admitted_task", events[0].effects)


class AdmitVerbTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="admit-verb-test-")
        self.addCleanup(self.temporary.cleanup)
        self.store = Store.create(Path(self.temporary.name) / "admit.sqlite", authority=AUTHORITY)
        self.addCleanup(self.store.close)
        self.store.register_domain_handler(contributions())
        self.graph = WorkGraph(self.store)
        self.project = self.graph.create_project(title="Admission", logical_request_key="project", actor=USER)
        self.task = self.graph.create_task(self.project, title="Plan", logical_request_key="task", actor=USER)
        self.review = self.graph.create_effort(self.project, title="Review", logical_request_key="review", actor=USER)
        self.session = types.SimpleNamespace(owner=types.SimpleNamespace(graph=self.graph, owner_actor=USER))

    # ---- helpers -----------------------------------------------------------------

    def argv(self, revision, key):
        return ["admit", "--task-ref", json.dumps(unpinned(self.task.ref).to_dict()), "--revision", revision,
                "--review-ref", json.dumps(self.review.ref.to_dict()), "--request-key", key]

    def run_admit(self, revision, key):
        out = StringIO()
        with redirect_stdout(out):
            code = cli.main(self.argv(revision, key), status_session=self.session)
        return code, json.loads(out.getvalue())

    def agent_revise(self, title, key):
        return self.graph.revise(unpinned(self.task.ref), title=title, actor=AGENT, logical_request_key=key)

    def admitted_revision(self):
        return self.graph.admission_state(unpinned(self.task.ref))["admitted_revision"]

    def revised_event_ids(self):
        return [event.event_id for event in self.store.list_events(stream="work:" + self.task.id)
                if event.event_type == "work.revised"]

    # ---- tests -------------------------------------------------------------------

    def test_generic_admit_verb_is_denied_even_with_injected_owner_session(self):
        revised = self.agent_revise("Plan revised by agent", "agent-1")
        writes = self.revised_event_ids()
        code, out = self.run_admit(revised.revision, "verb-1")
        self.assertEqual(code, 4, out)
        self.assertEqual(out["error"]["code"], "owner_presence_required", out)
        self.assertEqual(self.revised_event_ids(), writes)
        self.assertIsNone(self.admitted_revision())

    def test_admit_verb_refuses_a_changed_sheet_with_the_diff(self):
        reviewed = self.agent_revise("Plan A", "agent-a")
        self.agent_revise("Plan B", "agent-b")
        code, out = self.run_admit(reviewed.revision, "verb-diff")
        self.assertEqual(code, 4, out)
        self.assertEqual(out["outcome"], "denied", out)
        self.assertEqual(out["error"]["code"], "owner_presence_required", out)
        self.assertIsNone(self.admitted_revision())

    def test_admit_verb_refuses_without_an_owner_session(self):
        revised = self.agent_revise("Plan revised by agent", "agent-1")
        out = StringIO()
        with redirect_stdout(out):
            code = cli.main(self.argv(revised.revision, "verb-none"))
        result = json.loads(out.getvalue())
        self.assertEqual(result["outcome"], "denied", result)
        self.assertEqual(code, 4, result)
        self.assertIsNone(self.admitted_revision())


class ReviewedActivationAdmitsTests(unittest.TestCase):
    def setUp(self):
        self.f = owner_fixture.ExecutionApplicationTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    # ---- helpers -----------------------------------------------------------------

    def task_count(self):
        return len(self.f.owner.graph.list(project=self.f.project.ref, kind="task"))

    def revised_event_ids(self, task):
        return [event.event_id for event in self.f.store.list_events(stream="work:" + task.id)
                if event.event_type == "work.revised"]

    # ---- tests -------------------------------------------------------------------

    def test_activation_requires_a_previously_admitted_revision(self):
        plan_ref, review_ref = reviewed_fixture.ReviewedActivationTests._documents_for(self.f)
        graph, owner = self.f.owner.graph, self.f.owner.owner_actor
        task = graph.create_task(self.f.project.ref, title="Pair task", logical_request_key="pair-task", actor=owner)
        scope = AssessmentModule(self.f.store, actor=owner, payload_resolver=self.f.owner.evidence_payload_resolver).declare_scope(
            "pair-scope", parent_obligation=task.ref, protocol="otto-reviewed-plan", criteria=[{"id": "c1", "definition": "pair"}],
            review_required=True, designated_approver="manager", authority=owner.authority,
            policy={"required_for_completion": True}, logical_request_key="pair-scope", actor=owner)
        criterion = types.SimpleNamespace(ref=scope.criterion_refs[0])
        agent =self.f.binding.authenticated_actor("agent")
        revised = graph.revise(unpinned(task.ref), title="Agent pair task", logical_request_key="agent-pair", actor=agent)
        self.assertNotEqual(revised.revision, task.revision)
        policy = {"task_specs": [{"id": "one", "title": "Agent pair task"}],
                  "task_criterion_pairs": [{"task_ref": revised.ref.to_dict(),
                                            "criterion_ref": criterion.ref.to_dict()}]}
        activation = self.f.owner.reviewed_plan_activation(owner_policy=policy)
        before = self.task_count()
        from otto.portfolio.reviewed_activation import ReviewedActivationError
        writes = self.revised_event_ids(task)
        with self.assertRaises(ReviewedActivationError):
            activation.activate(project_ref=self.f.project.ref.to_dict(), plan_ref=plan_ref,
                review_ref=review_ref, owner_policy=policy, request_key="admit-activate", manager="manager")
        self.assertEqual(self.revised_event_ids(task), writes)
        graph.admit(unpinned(task.ref), revision=revised.revision, review_ref=self.f.owner.graph.create_effort(
            self.f.project.ref, title="Operator review", logical_request_key="operator-review", actor=owner).ref,
            logical_request_key="pre-admitted", actor=owner)
        result = activation.activate(project_ref=self.f.project.ref.to_dict(), plan_ref=plan_ref,
            review_ref=review_ref, owner_policy=policy, request_key="admit-activate", manager="manager")
        self.assertEqual(result["outcome"], "activated", result)
        self.assertEqual([ref["id"] for ref in result["task_refs"]], [task.id], result)
        state = graph.admission_state(unpinned(task.ref))
        self.assertEqual(state["admitted_revision"], revised.revision, state)
        self.assertEqual(state["stamp"]["basis"], "review", state)
        self.assertEqual(state["stamp"]["disposition"], "approved", state)
        self.assertEqual(self.task_count(), before)
        writes = self.revised_event_ids(task)
        again = activation.activate(project_ref=self.f.project.ref.to_dict(), plan_ref=plan_ref,
            review_ref=review_ref, owner_policy=policy, request_key="admit-activate", manager="manager")
        self.assertEqual(again["outcome"], "replayed", again)
        self.assertEqual(again["task_refs"], result["task_refs"])
        self.assertEqual(self.revised_event_ids(task), writes)
        self.assertEqual(self.task_count(), before)
        self.assertEqual(graph.admission_state(unpinned(task.ref))["admitted_revision"], revised.revision)


if __name__ == "__main__":
    unittest.main()
