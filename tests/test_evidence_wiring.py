"""Production owner composition verifies managed evidence through its evidence handler.

The owner is built by PortfolioOwnerBootstrap and every assessment call goes
through the manager assessment command path the owner composes, not through a
hand-built AssessmentModule.  Without the evidence handler passed as the owner's
payload_resolver, accept refuses managed DAT evidence as unverified.
"""
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from herzchen.content import ContentDocument, ContentRevision
from herzchen.contracts import ResourceRef, TransactionContext
from herzchen.domains.assessment import AssessmentModule
from herzchen.domains.assessment.model import AssessmentStateError
from herzchen.evidence.commands import EvidenceCommandHandler, register_evidence
from herzchen.evidence.model import load_evidence_pack
from otto.portfolio.herzchen_binding import ProjectReadGrant
from otto.portfolio.local_assessment_policy import compose_manager_assessment_state
from otto.portfolio.manager_assessment_command import manager_assessment_from_command, manager_assessment_pool_from_command
from otto.portfolio.owner_bootstrap import PortfolioOwnerBootstrap
from tests import test_evidence_lifecycle as lifecycle
from tests import test_execution_application as execution

OCTET_STREAM = "application/octet-stream"


class ProductionEvidenceWiringTests(unittest.TestCase):
    def setUp(self):
        self.f = execution.ExecutionApplicationTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        f = self.f
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        register_evidence(f.store)
        # Same public pack snapshot as tests/test_evidence_verification.py.
        root, discover, loader = lifecycle._public_pack_hooks()
        found = discover(project_root=root)[0]
        found.entry.definition.version = "1.1.0"
        found.entry.definition.to_dict = lambda: {"id": "evidence", "version": "1.1.0", "schema_version": 2}
        found.entry.resource_handles += tuple(SimpleNamespace(path=path, kind="evidence_preset",
            resolved=root / path, sha256=hashlib.sha256((root / path).read_bytes()).hexdigest())
            for path in ("presets/list.json", "presets/read.json"))
        pack = load_evidence_pack(project_root=root, discoverer=lambda **kwargs: (found,), loader=loader)
        self.handler = EvidenceCommandHandler(f.store, Path(self.directory.name) / "managed", pack=pack,
            adopted_pins=[item.to_dict() for item in pack.resources])

        issuer = f.binding.authenticated_actor("manager")
        self.owner = PortfolioOwnerBootstrap(f.store, binding=f.binding, owner_actor="manager",
            project_read_grant=ProjectReadGrant(issuer, (f.project.id,), "test-host", "v1"),
            evidence_payload_resolver=self.handler)

        self.attempt = ResourceRef(f.actor.authority, "work.attempt", "attempt")
        f.store.put_identity(self.attempt, {"record_type": "work.attempt", "project_ref": f.project.ref,
                                            "task_ref": f.task.ref}, version=0)
        self.manager = self.owner.assignments.command_port.assign(f.project.ref, role="manager", principal="manager",
            manager="manager", session="retained-manager", pins=[], logical_request_key="manager-assignment", actor=f.actor)
        scope = AssessmentModule(f.store, actor=f.actor).declare_scope("original-criteria", parent_obligation=f.project.ref,
            protocol="original-criteria", criteria=[{"id": "C01"}], logical_request_key="original-criteria")
        self.state = {"authority": f.actor.authority, "project_ref": f.project.ref.to_dict(),
            "task_refs": {"PA01": f.task.ref.to_dict()}, "criterion_refs": {"C01": scope.criterion_refs[0].to_dict()},
            "manager": "manager", "manager_generation": 1, "assignment_ref": self.manager.ref.to_dict()}
        self.config = {"kind": "owner_local_bookkeeping", "purpose": "local retained inspection", "local_only": True,
            "pool_id": "local-inspection", "capacity_units": 1, "cumulative_allowance_units": 1,
            "task_criterion_pairs": ["PA01/C01"]}
        config_path = Path(self.directory.name) / "run.yaml"
        config_path.write_text(json.dumps({"assessment_accounting": self.config}))
        self.state = compose_manager_assessment_state(self.state, config_path=config_path)
        manager_assessment_pool_from_command(self.owner, state=self.state, request=self.request("pool-create"))

        document = ContentDocument(ResourceRef(f.actor.authority, "dat.content.document", "source-PA01"),
            role="SOURCE", visibility="shared", access_mode="read", maintainer="manager", authoring_scope=f.project.ref)
        revision = ContentRevision(document.ref, "rev-1", {"inspection": "PA01", "source_digest": "a" * 64}, f.actor, initial=True)
        envelope = self.owner.content.build_create_document(TransactionContext(f.actor, "source-PA01", "b" * 64), document, revision)
        self.owner.content.execute(envelope)
        self.candidate = revision.ref.to_dict()

    def request(self, key, operation=None, arguments=None):
        value = {"command": "manager-assessment" if operation else "manager-assessment-pool", "task": "PA01",
            "request_key": key, "expected_task_ref": self.state["task_refs"]["PA01"],
            "expected_assignment_ref": self.state["assignment_ref"], "expected_generation": 1}
        if operation:
            value.update(operation=operation, arguments=arguments)
        return value

    def call(self, operation, arguments, key):
        return manager_assessment_from_command(self.owner, state=self.state,
            request=self.request(key, operation, arguments))

    def _accept_managed(self, name, *, tamper=False):
        """Run declare→freeze→select→assess→accept with one managed runner result as evidence."""
        f = self.f
        payload = ("runner output for " + name).encode()
        submitted = self.handler.submit(payload, actor=f.actor, logical_request_key="runner-" + name,
            project_ref=f.project.ref, task_ref=f.task.ref, attempt_ref=self.attempt,
            original_creator="creator", format=OCTET_STREAM)
        runner = submitted["revision_ref"]
        runner = runner.to_dict() if hasattr(runner, "to_dict") else runner
        criterion = self.state["criterion_refs"]["C01"]
        scope = self.call("declare-scope", {"scope_ref": {"authority": f.actor.authority, "kind": "assessment.scope",
            "id": "gate-" + name}, "criterion_refs": [criterion], "protocol": "retained-source-inspection"},
            "scope-" + name)["ref"]
        packet = self.call("freeze-input", {"scope_ref": scope, "candidate_ref": self.candidate,
            "criterion_refs": [criterion], "source_refs": [self.candidate], "evidence_refs": [runner],
            "packet": {"inspected": True}}, "input-" + name)["ref"]
        self.call("select-candidate", {"scope_ref": scope, "candidate_ref": self.candidate, "criterion_ref": criterion,
            "rationale": "exact current admitted source"}, "select-" + name)
        result = self.call("assess", {"scope_ref": scope, "candidate_ref": self.candidate, "criterion_ref": criterion,
            "input_ref": packet, "verdict": "PASS",
            "limit_pool_ref": {"authority": f.actor.authority, "kind": "limit", "id": "local-inspection"},
            "protocol_result": {"inspected": True}}, "assess-" + name)["ref"]
        if tamper:
            path = Path(self.directory.name) / "managed" / submitted["manifest"]["storage"]["location"]
            data = path.read_bytes()
            path.write_bytes(bytes([data[0] ^ 0xFF]) + data[1:])
        return self.call("accept", {"result_ref": result, "candidate_ref": self.candidate, "criterion_ref": criterion,
            "evidence_refs": [runner], "rationale": "runner evidence verified"}, "accept-" + name)["ref"]

    def test_production_owner_accepts_verified_managed_result(self):
        decision = self._accept_managed("good")
        record = self.f.store.get_identity(ResourceRef.from_dict(decision))
        digest = hashlib.sha256(("runner output for good").encode()).hexdigest()
        digests = [item.get("digest") if isinstance(item, Mapping) else item for item in record.payload["evidence_digests"]]
        self.assertIn(digest, digests)

    def test_production_owner_refuses_tampered_managed_result(self):
        with self.assertRaisesRegex(AssessmentStateError, "is not verified"):
            self._accept_managed("tampered", tamper=True)
