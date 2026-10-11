"""Real owner/CLI recovery of a completed resume whose live admission failed."""
import json
import sys
from pathlib import Path
from unittest.mock import patch
import unittest

from tests import test_fresh_manager_admission as fixture_module
digest = fixture_module.digest
from otto.agents.herzchen_adapter import HerzchenCodexAdapter


class CompletedResumeCaptureTests(unittest.TestCase):
    def fixture(self):
        f, root = fixture_module.FreshManagerTests.fixture(self)
        self.assertEqual(f.app.start(schedule_id="fresh-manager")["outcome"], "succeeded")
        launcher = root / "fixture-cli"
        text = launcher.read_text().replace('turn = "work-turn" if resume else "ready-turn"',
            'turn = "resume-turn" if resume else "ready-turn"')
        launcher.write_text(text)
        prior = f.app._read("fresh-manager")
        role = f.app.prepare_role(role="manager", project_ref=prior.target["project_ref"],
            task_ref=prior.target["task_ref"], assignment_ref=prior.assignment_ref,
            generation=prior.generation, mandate_ref=prior.target["mandate_ref"],
            request_key="exact-resume", instruction="Inspect this exact recovered task",
            model="gpt-test", reasoning="high", profile="workspace-write",
            native_session_id="bootstrap-session", binding_schedule_id="fresh-manager")
        original = HerzchenCodexAdapter.set_turn_started_callback
        def failed_callback(adapter, callback):
            def fail(*args, **kwargs):
                raise OSError("exact user message is not retained yet")
            original(adapter, fail)
        with patch.object(HerzchenCodexAdapter, "set_turn_started_callback", failed_callback):
            result = f.app.start(schedule_id=role["schedule_id"])
        self.assertEqual(result["outcome"], "unknown", result)
        due = f.port.read_due(role["schedule_id"])
        captured = due["host_evidence"]["gateway_attempt"]["result"]
        self.assertEqual(captured["raw_result"]["work_envelope"]["stderr"], "native turn-start capture failed")
        f.app.runtime.adapter.trusted_thread_reader = lambda session: {
            "thread": {"id": session, "path": str(root / "native.jsonl")}}
        return f, root, role["schedule_id"], captured

    def test_terminal_reparse_retains_failed_transport_and_unknown_without_replay(self):
        f, root, schedule, prior = self.fixture()
        before = f.port.read_due(schedule)
        submitted = (root / "submitted.jsonl").read_bytes()
        preview = f.app.runtime.reconcile_completed_resume_capture(schedule_id=schedule,
            expected_unknown_sha256=digest(prior), validate_only=True)
        self.assertEqual(preview["outcome"], "qualified")
        self.assertEqual(f.port.read_due(schedule), before)
        result = f.app.runtime.reconcile_completed_resume_capture(schedule_id=schedule,
            expected_unknown_sha256=digest(prior))
        self.assertFalse(result["provider_called"])
        self.assertEqual(result["admission_reconciliation"]["source_unknown"], prior)
        self.assertFalse(result["admission_reconciliation"]["original_admission_claimed"])
        due = f.port.read_due(schedule)
        replacement = due["host_evidence"]["gateway_attempt"]["result"]
        for key in ("work_receipt", "initialization_receipt", "initialization_envelope"):
            self.assertEqual(replacement["raw_result"][key], prior["raw_result"][key])
        for key, value in prior["raw_result"]["work_envelope"].items():
            if key != "host_evidence":
                self.assertEqual(replacement["raw_result"]["work_envelope"][key], value)
        self.assertEqual(f.app.recover(schedule_id=schedule, execute=False)["outcome"], "succeeded")
        self.assertEqual((root / "submitted.jsonl").read_bytes(), submitted)
        self.assertTrue(f.app.runtime.reconcile_completed_resume_capture(schedule_id=schedule,
            expected_unknown_sha256=digest(prior))["replayed"])
        next_role = f.app.prepare_role(role="manager", project_ref=prior["project_ref"],
            task_ref=prior["task_ref"], assignment_ref=prior["assignment_ref"],
            generation=prior["generation"], mandate_ref=before["target"]["mandate_ref"],
            request_key="continue-after-reconciled-capture", instruction="Advance retained work",
            model="gpt-test", reasoning="high", profile="workspace-write",
            native_session_id=prior["physical_session_id"], binding_schedule_id=schedule)
        from otto.portfolio.operating_setup import verify_role_conversation
        next_due = f.app._read(next_role["schedule_id"])
        assignment = f.app.runtime._assignment_reader(next_due.assignment_ref)(
            {k: next_due.assignment_ref[k] for k in ("authority", "kind", "id")})
        native, _ = verify_role_conversation(due=next_due, assignment=assignment,
            project_ref=prior["project_ref"], due_port=f.port, actor=f.app.runtime.actor)
        self.assertEqual(native, prior["physical_session_id"])
        self.assertEqual((root / "submitted.jsonl").read_bytes(), submitted)
        from copy import deepcopy
        from otto.agents.manager_capture_reconciliation import completed_resume_admission
        attempt = f.port.read_due(schedule)["host_evidence"]["gateway_attempt"]
        for field, value in (("resolver", "foreign-owner"),
                             ("replacement_sha256", "0" * 64),
                             ("observed_turn_id", "foreign-turn")):
            changed = deepcopy(attempt)
            changed["delivery_admission_reconciliation"][field] = value
            self.assertEqual(completed_resume_admission(changed, f.app.runtime.actor), {})

    def test_foreign_active_changed_prompt_model_and_stale_custody_are_rejected(self):
        for mode in ("foreign_session", "active", "model", "prompt", "no_completion", "digest", "stale"):
            with self.subTest(mode=mode):
                f, root, schedule, prior = self.fixture()
                before = f.port.read_due(schedule); path = root / "native.jsonl"
                raw = path.read_text()
                if mode == "foreign_session":
                    f.app.runtime.adapter.trusted_thread_reader = lambda session: {
                        "thread": {"id": "foreign", "path": str(path)}}
                elif mode == "active":
                    path.write_text(raw + json.dumps({"type": "event_msg", "payload": {
                        "type": "task_started", "turn_id": "new-active"}}) + "\n")
                elif mode == "model":
                    path.write_text(raw.replace('"model": "gpt-test"', '"model": "foreign-model"'))
                elif mode == "prompt":
                    path.write_text(raw.replace("Inspect this exact recovered task", "foreign instruction"))
                elif mode == "no_completion":
                    path.write_text("\n".join(line for line in raw.splitlines()
                        if not ("task_complete" in line and "resume-turn" in line)) + "\n")
                elif mode == "stale":
                    from herzchen.contracts import ResourceRef
                    f.app.assignments.reassign(ResourceRef.from_dict(prior["assignment_ref"]),
                        principal="manager", session="bootstrap-session", reason="changed custody",
                        expected_generation=1, logical_request_key="reassignment", actor=f.actor)
                with self.assertRaises(Exception):
                    f.app.runtime.reconcile_completed_resume_capture(schedule_id=schedule,
                        expected_unknown_sha256="0" * 64 if mode == "digest" else digest(prior))
                self.assertEqual(f.port.read_due(schedule), before)


if __name__ == "__main__":
    unittest.main()
