import json
from pathlib import Path
import tempfile
import unittest

from otto.portfolio.retained_projection import (
    record_preparation_stage, read_checkpoint_detail, read_projection,
)


class PreparationStageProducerTests(unittest.TestCase):
    def test_two_real_stages_keep_exact_details_without_recursive_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preparation.json"
            binding = {"principal": "owning-preparation", "generation": 1,
                       "assignment_ref": {"authority": "owner", "kind": "wrk.assignment", "id": "manager", "revision": "rev-4"}}
            first = record_preparation_stage(path, stage="prepared", binding=binding,
                value={"outcome": "prepared", "schedule_id": "same-occurrence", "raw_result": "x" * 2_000_000})
            pin = dict(first["artifact_ref"])
            second = record_preparation_stage(path, stage="qualified", binding=binding,
                value={"outcome": "qualified", "provider_called": False, "before_state": json.loads(path.read_text())})
            ledger = json.loads(path.read_text())
            self.assertLess(path.stat().st_size, 4096)
            self.assertEqual(ledger["stages"]["prepared"]["artifact_ref"], pin)
            self.assertNotIn("raw_result", first)
            self.assertEqual(first["schedule_id"], "same-occurrence")
            read = read_projection(first["checkpoint_path"], expected_binding=binding)
            self.assertEqual(read["io_work"]["payload_bytes_read"], 0)
            detail = read_checkpoint_detail(first["checkpoint_path"], expected_binding=binding, max_bytes=97)
            self.assertEqual(len(detail["bytes"]), 97)
            self.assertEqual(detail["verification"], "range-not-revalidated")
            self.assertEqual(second["outcome"], "qualified")
            self.assertNotIn("stages", second.get("before_state", {}))

    def test_changed_binding_replay_unsafe_name_and_partial_capture_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preparation.json"
            binding = {"principal": "owner", "generation": 1}
            record_preparation_stage(path, stage="first", value={"outcome": "prepared"}, binding=binding)
            original = path.read_bytes()
            for bad in ({"principal": "foreign", "generation": 1}, {**binding, "generation": 2}):
                with self.assertRaises(PermissionError):
                    record_preparation_stage(path, stage="next", value={}, binding=bad)
            with self.assertRaises(FileExistsError):
                record_preparation_stage(path, stage="first", value={}, binding=binding)
            with self.assertRaises(ValueError):
                record_preparation_stage(path, stage="../escape", value={}, binding=binding)
            path.with_name("preparation-next.detail.json").write_text("retained partial")
            with self.assertRaises(FileExistsError):
                record_preparation_stage(path, stage="next", value={}, binding=binding)
            self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
