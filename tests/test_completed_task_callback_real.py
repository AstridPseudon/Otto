import unittest
import hashlib
from herzchen.content.instructions import validate_instruction_content
from tests.test_manager_journey_command import ManagerJourneyCommandTests


class RealCompletedReplayTests(ManagerJourneyCommandTests):
    def test_finish_true_completed_replay_after_adoption_is_read_only(self):
        request = self.request(key="completed-replay-after-adoption")
        first = self.commands.review_task(request)
        self.assertEqual(first["completion"]["outcome"], "completed", first)
        self.fixture.state["task_refs"]["PA01"] = first["completion"]["task_ref"]
        f = self.application
        content = {"schema": "herzchen.instructions.v1", "name": "replay-guide",
            "entrypoint": "MANAGER.md", "instructions": "Retained replay guide",
            "bundle_digest": hashlib.sha256(b"Retained replay guide").hexdigest(),
            "export_manifest_digest": "replay-guide-export", "required": True, "supporting_refs": []}
        made = f.app.portfolio.create_document(f.project.ref.to_dict(), actor="manager",
            request_id="replay-guide-create", document_id=content["name"], content=content)
        ref = made["record"]["payload"]["current_revision"]
        adopted = f.owner.assignments.command_port.adopt_resources(self.fixture.manager.ref,
            resources=[{"resource_ref": ref, "resource_name": content["name"],
                "content_digest": validate_instruction_content(content), "required": True}],
            expected_revision=self.fixture.manager.revision, expected_generation=self.fixture.manager.generation,
            logical_request_key="replay-guide-adopt", actor=f.actor)
        self.fixture.state["assignment_ref"] = adopted.ref.to_dict()
        before = f.owner.graph.reader.snapshot_counts()
        read = self.commands.review_input("PA01")
        self.assertEqual(read["outcome"], "read", read)
        self.assertFalse(read["review_eligible"])
        replay = self.commands.review_task(request)
        self.assertEqual(replay["completion"]["outcome"], "replayed", replay)
        self.assertEqual(replay["completion"]["receipt"]["result_ref"], first["completion"]["task_ref"])
        self.assertEqual(f.owner.graph.reader.snapshot_counts(), before)
        self.assertEqual(self.application.provider.calls, [])


if __name__ == "__main__":
    unittest.main()
