## 1. Design, in implementation order

1. [config.py:33](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/config.py:33) and [config.py:203](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/config.py:203) → consume XFERMAP’s **complete, pinned** inventory of old and destination homes, host client homes, external connection and binding locators, exports, and exact proposed deletion paths. Reject missing entries, symlinks, path overlap with exports or destination state, and inventory drift. A saved plan establishes correspondence, not custody.
2. [product_service.py:1299](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/product_service.py:1299) and [product_service.py:1349](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/product_service.py:1349) → keep a transfer-marked destination under the existing admission hold. Read every corresponding old request, Due, receipt, native and runner hold through the owner’s existing bounded custody reads. Require a verified settlement or explicit no-effect disposition before enabling the corresponding new operation. Unknown remains held; imported project content does not count as effect disposition.
3. [project_service.py:91](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/project_service.py:91) → retain the existing held-owner read route. Recheck custody under serialized owner control before the **unheld destination restart**; do not add a second dispatch path.
4. [service.py:119](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/service.py:119) → add `transfer_boundary.py` with `assess_boundary(plan, readbacks, go=None)`. Its production caller must obtain readbacks itself: destination status after restart, old owner and supervisor process/lock status, every export’s current digest, and every inventoried client’s current owner identity and project scope. Reassess at deletion time; a retained “ready” result is not authority.
5. [orchestrator_client.py:163](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/orchestrator_client.py:163), [root_direction_client.py:144](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/root_direction_client.py:144), and [service.py:510](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/service.py:510) → reissue each binding through its existing owner route, then verify its exact assignment, generation, principal, authority, conversation, projects and canonical supervision. Require a bijection with the inventory: one successful client cannot cover another.
6. [cli.py:845](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/cli.py:845) → expose the boundary assessment to CUTOVER. It returns only the enumerated old paths when all checks pass **and** the existing user go names that exact set and plan digest. The deletion executor must consume this assessment immediately before removal. No deletion occurs in the test.

## 2. Failing test to write first

New file: `tests/test_hostctl_transfer_boundary.py`. This tests the decision contract with disposable paths and structured owner readbacks; the worker must also test the production readback collector against disposable owner installations.

```python
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from otto.hostctl.transfer_boundary import assess_boundary


class TransferBoundaryTests(unittest.TestCase):
    def test_unknown_work_and_one_stale_client_fence_exact_deletion(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old, new = root / "old", root / "new"
            old.mkdir()
            new.mkdir()
            export = root / "preserved-export"
            export.write_bytes(b"canonical export")
            first = root / "client-one" / "binding.json"
            second = root / "client-two" / "binding.json"
            first.parent.mkdir()
            second.parent.mkdir()
            first.write_text("{}")
            second.write_text("{}")

            with subprocess.Popen([sys.executable, "-c", "pass"]) as exited:
                exited.wait()

            plan = {
                "old_home": str(old),
                "new_home": str(new),
                "corresponding_work": ["effect-1"],
                "clients": [
                    {"locator": str(first), "principal": "one",
                     "assignment_ref": "new-one", "generation": 2,
                     "project_ids": ["project-1"]},
                    {"locator": str(second), "principal": "two",
                     "assignment_ref": "new-two", "generation": 2,
                     "project_ids": ["project-2"]},
                ],
                "exports": [{"path": str(export),
                             "sha256": hashlib.sha256(export.read_bytes()).hexdigest()}],
                "delete_paths": [str(old)],
            }
            readbacks = {
                "old_work": {"effect-1": {"state": "unknown", "receipt": None}},
                "new_work": {"effect-1": {"admitted": False}},
                "old_owner": {"state": "closed", "pid": exited.pid,
                              "supervisor_pid": exited.pid, "writer_lock_free": True},
                "destination": {"state": "serving", "owner": "new-owner",
                                "authority": "new", "prior_generation": 1,
                                "generation": 2},
                "clients": {
                    str(first): {"principal": "one", "assignment_ref": "new-one",
                                 "generation": 2, "project_ids": ["project-1"],
                                 "owner": "new-owner", "authority": "new"},
                    str(second): {"principal": "two", "assignment_ref": "new-two",
                                  "generation": 2, "project_ids": ["project-2"],
                                  "owner": "new-owner", "authority": "new"},
                },
            }

            initial = assess_boundary(plan, readbacks)
            self.assertFalse(initial["admission_allowed"])
            self.assertEqual(initial["eligible_delete_paths"], [])

            readbacks["old_work"]["effect-1"] = {
                "state": "settled", "receipt": "verified-effect-1"
            }
            settled = assess_boundary(plan, readbacks)
            self.assertTrue(settled["admission_allowed"])
            self.assertEqual(settled["eligible_delete_paths"], [])
            go = {"action": "CUTOVER", "plan_digest": settled["plan_digest"],
                  "delete_paths": [str(old)]}

            readbacks["clients"][str(second)]["assignment_ref"] = "old-two"
            self.assertEqual(
                assess_boundary(plan, readbacks, go=go)["eligible_delete_paths"], [])
            readbacks["clients"][str(second)]["assignment_ref"] = "new-two"

            readbacks["destination"]["generation"] = 1
            self.assertEqual(
                assess_boundary(plan, readbacks, go=go)["eligible_delete_paths"], [])
            readbacks["destination"]["generation"] = 2

            export.unlink()
            self.assertEqual(
                assess_boundary(plan, readbacks, go=go)["eligible_delete_paths"], [])
            export.write_bytes(b"canonical export")

            readbacks["old_owner"]["pid"] = os.getpid()
            self.assertEqual(
                assess_boundary(plan, readbacks, go=go)["eligible_delete_paths"], [])
            readbacks["old_owner"]["pid"] = exited.pid

            self.assertEqual(
                assess_boundary(plan, readbacks, go=go)["eligible_delete_paths"],
                [str(old)])
            self.assertTrue(new.exists())
            self.assertTrue(export.exists())
```

The production collector must establish the readbacks from current owner records and OS/process observations, never accept this dictionary from a client.

## 3. What to delete

The eligible physical set is exactly `plan.delete_paths`; exports, destination state, shared Store paths and unlisted client homes stay outside it. There is no existing CUTOVER deletion implementation on `canon/main` to remove. Keep the old wrapper route at [cli.py:849](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/cli.py:849) until CUTOVER has proved the old installation stopped; retire that duplicate start route at the final switch, not during preparation.

## 4. Plausible mistake

Treating an exported plan as settled work, or checking only the first client, could replay an unknown effect or leave a stale owner usable. The test holds new admission on unknown work and keeps deletion ineligible when the second client is stale. It also rejects a failed restart, missing export and live old PID.

## 5. Existing test expectations and D19

No existing assertion needs to change for this additive, transfer-marked gate. Fresh-install expectations in [test_compose.py:205](${TRANSFER_ROOT}/source/otto/tests/test_compose.py:205) remain valid. If implementation changes any existing assertion, record the file and reason in a D19 decision before landing.

## 6. Stale or incorrect row references

`config.py:199` is a section comment; client configuration starts at [config.py:203](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/config.py:203). `orchestrator_client.py:325` starts the CLI parser; binding validation is at [orchestrator_client.py:163](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/orchestrator_client.py:163). `PATH-TO-CUTOVER` and numbered CUTOVER steps 4–6 are absent from `canon/main`, so their attachment point must be supplied by the program. Current project import is explicitly *passive adoption* at [herzchen_binding.py:1063](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/herzchen_binding.py:1063); it does not migrate live custody. No files were changed and no tests were run.