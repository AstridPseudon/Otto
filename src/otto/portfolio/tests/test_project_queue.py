"""D03 queue proof through existing disposable WRK/DAT ports and owner ingress."""
import argparse
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest

from herzchen.authoring import domain_contribution as authoring_contribution
from herzchen.content import domain_contribution
from herzchen.contracts import ResourceRef
from herzchen.domains.work import contributions
from herzchen.kernel import Store
from otto.portfolio.herzchen_binding import HerzchenBindingConfig
from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap
from otto.portfolio.project_queue import ProjectQueue, identity
from otto.portfolio.owner_authoring_ingress import OwnerAuthoringIngress
from otto.portfolio.manager_journey_service import ManagerJourneyService
from otto.portfolio.manager_journey_client import add_manager_journey_parsers
from otto.portfolio.execution_host import ExecutionHost, _nested_capability


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="d03-queue-")
        self.addCleanup(self.temp.cleanup)
        self.store = Store.create(Path(self.temp.name) / "fixture.sqlite", authority="queue-proof")
        self.store.register_domain_handler((*contributions(), domain_contribution(), authoring_contribution()))
        self.addCleanup(self.store.close)
        self.binding = HerzchenBindingConfig("queue-proof", "fixture-credential")
        seed = PortfolioOwnerBootstrap(self.store, binding=self.binding, owner_actor="owner")
        self.portfolio = ResourceRef("queue-proof", "wrk.portfolio", "portfolio")
        self.root = seed.assignments.assign(self.portfolio, role="orchestrator", principal="root",
                                            logical_request_key="root")
        self.owner = PortfolioOwnerBootstrap(self.store, binding=self.binding, owner_actor="owner",
            portfolio_ref=self.portfolio, main_assignment_ref=self.root.ref)
        self.ops = self.owner.consumer_operations()
        self.queue = ProjectQueue(self.ops)
        self.first = self.owner.graph.create_project(title="Predecessor", logical_request_key="predecessor")
        self.pending = self.owner.graph.create_project(title="Pending", logical_request_key="pending")
        self.third = self.owner.graph.create_project(title="Extension", logical_request_key="extension")
        attached = self.ops.execute("work.orchestrator.projects.attach", {
            "target_assignment_ref": self.root.ref.to_dict(), "target_assignment_revision": self.root.revision,
            "target_assignment_generation": self.root.generation,
            "projects": [{"project_ref": self.first.ref.to_dict()}]}, request_id="first-enroll", actor="owner")
        self.assertEqual(attached["outcome"], "attached")
        self.order = [identity(self.first.ref).to_dict()]
        self.seed = self.queue.apply(actor="owner", request_id="seed", operation="seed", order=self.order)
        self.assertEqual(self.seed["outcome"], "seeded", self.seed)
        self.base = self.seed["readback"]["queue_ref"]["revision"]

    def append(self, **extra):
        values = dict(actor="owner", request_id="append", operation="after", order=self.order,
            expected_revision=self.base, project_ref=self.pending.ref.to_dict(), predecessor_ref=self.first.ref.to_dict())
        values.update(extra)
        return self.queue.apply(**values)

    def test_same_portfolio_nondefault_supervisor_is_visible_to_every_consumer(self):
        root = self.owner.assignments.assign(self.portfolio, role="orchestrator",
            principal="product-root", logical_request_key="product-root")
        project = self.owner.graph.get(self.first.ref)
        relation = project.payload["metadata"]["otto_orchestrator"]
        default_before = self.ops._owner_reader.get_record(identity(relation["default_ref"]))
        self.owner.orchestration_port.transfer_supervision(
            actor=self.owner.owner_actor, request_id="transfer-first", portfolio_ref=self.portfolio.to_dict(),
            project_ref=project.ref.to_dict(), expected_project_revision=project.ref.revision,
            expected_project_version=project.version, current_assignment_ref=relation["assignment_ref"],
            current_assignment_revision=relation["assignment_revision"], current_assignment_generation=relation["generation"],
            target_assignment_ref=root.ref.to_dict(), target_assignment_revision=root.revision,
            target_assignment_generation=root.generation, overlap_acknowledged=True)
        counts = self.store.consumer().snapshot_counts()
        for consumer in ("root", "continuation", "observer"):
            value = self.queue.read(actor="owner", consumer=consumer)
            self.assertEqual(value["outcome"], "read", value)
            self.assertEqual(value["order"], self.order)
        self.assertEqual(self.store.consumer().snapshot_counts(), counts)
        self.assertEqual(self.ops._owner_reader.get_record(identity(relation["default_ref"])), default_before)
        # Exact relation revision/generation must still match its own current
        # supervisor. A later supported reassignment leaves the stale relation held.
        self.owner.assignments.reassign(root.ref, principal="new-product-root",
            expected_generation=root.generation, logical_request_key="product-root-reassignment")
        value = self.queue.read(actor="owner")
        self.assertEqual(value["outcome"], "held", value)
        self.assertIn("stale", value["reason"])

    def test_append_replay_extension_all_consumers_and_current_work_join(self):
        result = self.append()
        self.assertEqual(result["outcome"], "queued", result)
        self.assertTrue(result["queued"])
        self.assertEqual(result["enrollment"]["outcome"], "attached")
        self.assertEqual(result["readback"]["order"][:1], self.order)
        counts = self.store.consumer().snapshot_counts()
        self.assertTrue(self.append()["replayed"])
        self.assertEqual(self.store.consumer().snapshot_counts(), counts)
        changed = self.append(rule="pause")
        self.assertEqual(changed["outcome"], "held")
        self.assertIn("changed-input", changed["reason"])
        current = result["readback"]
        extension = self.append(request_id="extend", project_ref=self.third.ref.to_dict(),
            predecessor_ref=self.pending.ref.to_dict(), order=current["order"],
            expected_revision=current["queue_ref"]["revision"])
        self.assertEqual(extension["outcome"], "queued", extension)
        self.assertTrue(self.append()["replayed"])
        self.owner.graph.revise(self.pending.ref, title="Current title", logical_request_key="edit-title")
        for consumer in ("root", "continuation", "observer"):
            read = self.queue.read(actor="owner", consumer=consumer)
            self.assertEqual(read["terminal_project_ref"], identity(self.third.ref).to_dict())
            self.assertEqual(read["projects"][1]["title"], "Current title")
            self.assertEqual(read["order"], extension["readback"]["order"])
            self.assertFalse(read["dispatch"])
        for p in (self.first, self.pending, self.third):
            now = self.owner.graph.get(p.ref)
            self.assertEqual(now.payload["lifecycle"], "pending")
            self.assertEqual(now.payload["tasks"], [])
            self.assertIsNone(now.payload["execution"])

    def test_invalid_inputs_reject_before_effects(self):
        counts = self.store.consumer().snapshot_counts()
        cases = [dict(actor="intruder"), dict(expected_revision="rev-stale"),
                 dict(project_ref=self.first.ref.to_dict()), dict(predecessor_ref=self.pending.ref.to_dict()),
                 dict(project_ref={"authority": "foreign", "kind": "work.project", "id": "project"}),
                 dict(project_ref={"authority": "queue-proof", "kind": "work.project", "id": "missing"}),
                 dict(order=self.order * 2), dict(rule="pause")]
        for changes in cases:
            with self.subTest(changes=changes):
                result = self.append(**changes)
                self.assertEqual(result["outcome"], "held", result)
                self.assertEqual(result["stage"], "validation")
                self.assertEqual(self.store.consumer().snapshot_counts(), counts)
        # A foreign same-authority portfolio is also rejected, before attachment.
        foreign = self.owner.graph.create_project(title="Foreign", metadata={"otto_orchestrator": {
            "portfolio_ref": ResourceRef("queue-proof", "wrk.portfolio", "foreign").to_dict(),
            "assignment_ref": self.root.ref.to_dict(), "project_ref": self.pending.ref.to_dict()}},
            logical_request_key="foreign-supervision")
        counts = self.store.consumer().snapshot_counts()
        self.assertEqual(self.append(project_ref=foreign.ref.to_dict())["outcome"], "held")
        self.assertEqual(self.store.consumer().snapshot_counts(), counts)

    def test_stale_cas_after_enrollment_keeps_exact_enrollment_and_new_attempt_reuses_it(self):
        original = self.ops.content_port
        queue = self.queue
        class RacingPort:
            def __getattr__(self, name):
                return getattr(original, name)
            def execute(self, envelope):
                # A real DAT CAS winner intervenes between WRK and publication.
                current = queue._head()[1]
                actor = queue.binding["owner"]
                competing = queue._envelope(actor=actor, key="race", content=current,
                    base=self_test.base, intent="f" * 64)
                original.execute(competing)
                return original.execute(envelope)
        self_test = self
        self.ops.content_port = RacingPort()
        failed = self.append()
        self.assertFalse(failed["queued"], failed)
        self.assertEqual(failed["stage"], "publication")
        self.assertEqual(failed["enrollment_receipt"]["status"], "committed")
        self.assertFalse(failed["unknown_effect"])
        self.assertIsNotNone(self.owner.graph.get(self.pending.ref).payload["metadata"]["otto_orchestrator"])
        self.ops.content_port = original
        now = self.queue.read(actor="owner")
        current_project = self.owner.graph.get(self.pending.ref).ref.to_dict()
        finished = self.append(request_id="new-publication", expected_revision=now["queue_ref"]["revision"],
                               project_ref=current_project)
        self.assertEqual(finished["outcome"], "queued", finished)
        self.assertEqual(finished["enrollment"]["outcome"], "existing")
        self.assertIsNone(self.ops._receipt("new-publication:enroll"))
        self.assertIsNotNone(self.ops._receipt("append:enroll"))

    def test_lost_reply_after_publication_returns_partial_then_exact_readback_without_writes(self):
        original = self.ops.content_port
        class LostReply:
            def __getattr__(self, name):
                return getattr(original, name)
            def execute(self, envelope):
                original.execute(envelope)
                raise TimeoutError("fixture lost publication reply")
        self.ops.content_port = LostReply()
        partial = self.append()
        self.assertEqual(partial["outcome"], "held")
        self.assertEqual(partial["enrollment_receipt"]["status"], "committed")
        self.assertEqual(partial["publication"]["status"], "committed")
        self.assertFalse(partial["unknown_effect"])
        self.ops.content_port = original
        counts = self.store.consumer().snapshot_counts()
        self.assertEqual(self.append()["outcome"], "queued")
        self.assertEqual(self.store.consumer().snapshot_counts(), counts)

    def test_unchanged_partial_retry_and_changed_input_enrollment_receipt_binding(self):
        original = self.ops.content_port
        class BeforePublication:
            def __getattr__(self, name):
                return getattr(original, name)
            def execute(self, envelope):
                raise TimeoutError("fixture publication not observed")
        self.ops.content_port = BeforePublication()
        partial = self.append()
        self.assertEqual(partial["stage"], "publication")
        self.assertTrue(partial["unknown_effect"])
        self.assertFalse(partial["retry"])
        # Fixture explicitly reconciles no DAT effect, then restores the port.
        self.assertIsNone(self.ops._receipt("append:publish"))
        self.ops.content_port = original
        changed = self.append(project_ref=self.third.ref.to_dict())
        self.assertEqual(changed["outcome"], "held", changed)
        self.assertIsNone(self.owner.graph.get(self.third.ref).payload["metadata"].get("otto_orchestrator"))
        replay = self.append()
        self.assertEqual(replay["outcome"], "queued", replay)
        self.assertEqual(replay["enrollment"]["outcome"], "replayed")

    def test_missing_malformed_queue_and_root_replacement_hold_reads(self):
        # No fallback to filenames, transition docs or a copied stop target.
        binding = dict(self.ops.queue_binding)
        binding["locator"] = ResourceRef("queue-proof", "dat.content.document", "absent")
        self.ops.queue_binding = binding
        self.assertEqual(ProjectQueue(self.ops).read(actor="owner")["outcome"], "held")
        self.ops.queue_binding = self.owner.queue_binding
        self.owner.assignments.reassign(self.root.ref, principal="replacement", expected_generation=1,
                                        logical_request_key="replace-root")
        # A replaced generation requires owner reconciliation of the default.
        self.assertEqual(self.queue.read(actor="owner")["outcome"], "held")

    def test_parser_lane_and_exact_owner_grant_service_path(self):
        parser = argparse.ArgumentParser()
        add_manager_journey_parsers(parser.add_subparsers(dest="command", required=True))
        read = vars(parser.parse_args(["project-queue", "--consumer", "observer"]))
        self.assertEqual(_nested_capability(read), "admitted")
        ingress = OwnerAuthoringIngress(actor=self.owner.owner_actor, owner_actor=self.owner.owner_actor,
                                        directory=Path(self.temp.name) / "ingress")
        service = object.__new__(ManagerJourneyService)
        service.server = SimpleNamespace(owner=self.owner)
        service.authoring_authorizer = ingress.authorize
        with self.assertRaises(PermissionError):
            service._project_queue(read)
        ingress.publish({"schema": ingress.schema, "request": read})
        observed = service._project_queue(read)
        self.assertEqual(observed["outcome"], "read", observed)
        request = {"command": "project-queue", "operation": "after", "request_key": "service-append",
            "order": self.order, "rule": "continue", "expected_revision": self.base,
            "predecessor_ref": self.first.ref.to_dict(), "project_ref": self.pending.ref.to_dict()}
        ingress.publish({"schema": ingress.schema, "request": request})
        result = service._project_queue(request)
        self.assertEqual(result["outcome"], "queued", result)
        self.assertEqual(_nested_capability({**request, "activate": True}), "held")

    def test_fresh_owner_read_keys_preserve_old_receipt_and_same_queue_for_consumers(self):
        ingress = OwnerAuthoringIngress(actor=self.owner.owner_actor, owner_actor=self.owner.owner_actor,
                                        directory=Path(self.temp.name) / "fresh-ingress")
        service = ManagerJourneyService(server=SimpleNamespace(owner=self.owner, portfolio=None, state={},
            due_port=None, _execution=lambda **kw: None), host=None, run_path=Path(self.temp.name),
            workspace=Path(self.temp.name), authoring_authorizer=ingress.authorize)
        first = {"command":"project-queue", "operation":"read", "consumer":"root", "request_key":"before"}
        with self.assertRaises(PermissionError): service(first)
        issued = ingress.publish({"schema":ingress.schema, "request":first})
        old = service(first); retained = Path(issued["response_path"])
        retained.write_text(json.dumps(old, sort_keys=True))
        raw = retained.read_bytes()
        appended = self.append(); self.assertEqual(appended["outcome"], "queued")
        counts = self.store.consumer().snapshot_counts(); refs = []
        for consumer in ("root", "continuation", "observer"):
            request = {**first,"consumer":consumer,"request_key":"after:"+consumer}
            fresh = ingress.publish({"schema":ingress.schema,"request":request})
            self.assertNotEqual(fresh["request_id"], issued["request_id"])
            value = service(request); refs.append(value["queue_ref"])
            self.assertEqual(value["order"], appended["readback"]["order"])
        self.assertEqual(refs,[appended["readback"]["queue_ref"]]*3)
        self.assertEqual(self.store.consumer().snapshot_counts(),counts)
        self.assertEqual(retained.read_bytes(),raw)
        for key in ("", " ", " padded ", 17):
            invalid={**first,"request_key":key}
            ingress.publish({"schema":ingress.schema,"request":invalid})
            with self.assertRaises(ValueError): service(invalid)
        with self.assertRaises(PermissionError):
            service.dispatch_bound({"role":"manager","principal":"manager"},{**first,"request_key":"no-owner-grant"})

    def test_queue_request_is_serialized_during_native_wait(self):
        ipc = Path(self.temp.name) / "pump"
        ingress = OwnerAuthoringIngress(actor=self.owner.owner_actor, owner_actor=self.owner.owner_actor, directory=ipc)
        service = ManagerJourneyService(server=SimpleNamespace(owner=self.owner, portfolio=None, state={},
            due_port=None, _execution=lambda **kw: None),
            host=None, run_path=Path(self.temp.name), workspace=Path(self.temp.name), authoring_authorizer=ingress.authorize)
        owner_threads, queue_threads = [], []
        def wait(path):
            deadline = time.monotonic() + 5
            while not path.exists() and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(path.exists(), "finite queue request blocked behind native wait")
            return json.loads(path.read_text())
        def handler(request):
            if request["command"] == "start-manager":
                owner_threads.append(threading.get_ident())
                def native_wait():
                    intent = {"command": "project-queue", "operation": "after", "request_key": "pump-after",
                        "order": self.order, "rule": "continue", "expected_revision": self.base,
                        "predecessor_ref": self.first.ref.to_dict(), "project_ref": self.pending.ref.to_dict()}
                    issued = ingress.publish({"schema": ingress.schema, "request": intent})
                    result = wait(Path(issued["response_path"]))
                    self.assertEqual(result["outcome"], "queued", result)
                    for consumer in ("root", "continuation", "observer"):
                        issued = ingress.publish({"schema": ingress.schema, "request": {
                            "command": "project-queue", "operation": "read", "consumer": consumer}})
                        read = wait(Path(issued["response_path"]))
                        self.assertEqual(read["order"], result["readback"]["order"])
                    return {"outcome": "succeeded"}
                return ExecutionHost.external_call(native_wait)
            queue_threads.append(threading.get_ident())
            return service(request)
        host = ExecutionHost(directory=ipc, handler=handler)
        try:
            host.start()
            (ipc / "request-aaaa.json").write_text(json.dumps({"command": "start-manager"}))
            self.assertEqual(wait(ipc / "response-aaaa.json")["outcome"], "succeeded")
            self.assertEqual(len(queue_threads), 4)
            self.assertTrue(all(t == owner_threads[0] for t in queue_threads))
        finally:
            host.close()

    def test_reordered_prefix_and_unpinned_existing_enrollment_reject(self):
        appended = self.append()
        current = appended["readback"]
        counts = self.store.consumer().snapshot_counts()
        rejected = self.append(request_id="reorder", order=list(reversed(current["order"])),
            predecessor_ref=self.first.ref.to_dict(), project_ref=self.third.ref.to_dict(),
            expected_revision=current["queue_ref"]["revision"])
        self.assertEqual(rejected["outcome"], "held")
        self.assertIn("reordered", rejected["reason"])
        self.assertEqual(self.store.consumer().snapshot_counts(), counts)
        # An already-enrolled input still must pin the actual current project.
        stale = self.append(request_id="other", order=self.order, project_ref=identity(self.pending.ref).to_dict())
        self.assertEqual(stale["outcome"], "held")

    def test_adopted_locator_and_malformed_document_hold(self):
        other = ResourceRef("queue-proof", "dat.content.document", "accepted-queue")
        owner = PortfolioOwnerBootstrap(self.store, binding=self.binding, owner_actor="owner",
            portfolio_ref=self.portfolio, main_assignment_ref=self.root.ref, queue_ref=other)
        queue = ProjectQueue(owner.consumer_operations())
        adopted = queue.apply(actor="owner", request_id="adopted-seed", operation="seed", order=self.order)
        self.assertEqual(adopted["readback"]["locator"], other.to_dict())
        # Existing DAT primitive simulates an invalid owner edit; all reads hold.
        content = {**queue._head()[1], "root_ref": ResourceRef("queue-proof", "wrk.assignment", "foreign").to_dict()}
        original = queue._envelope(actor=owner.owner_actor, key="malformed", content=content,
            base=adopted["readback"]["queue_ref"]["revision"], intent="c" * 64)
        queue.ops.content_port.execute(original)
        for consumer in ("root", "continuation", "observer"):
            self.assertEqual(queue.read(actor="owner", consumer=consumer)["outcome"], "held")


if __name__ == "__main__":
    unittest.main()
