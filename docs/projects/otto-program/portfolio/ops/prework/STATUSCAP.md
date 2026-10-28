## 1. Design, in build order

1. [tests/test_hostctl_project_service.py:17](${TRANSFER_ROOT}/source/otto/tests/test_hostctl_project_service.py:17) → Add the failing status test below.
2. [src/herzchen/fleet/capacity.py:43](${TRANSFER_ROOT}/source/otto/src/herzchen/fleet/capacity.py:43) → Add `CapacityPolicy.total_turn_units`, returning `turn_units + manager_reserve`. Keep `total_units`: it includes heavy headroom and still describes the ledger pool.
3. [src/herzchen/fleet/capacity.py:63](${TRANSFER_ROOT}/source/otto/src/herzchen/fleet/capacity.py:63) → Use `self.total_turn_units` for the manager branch’s combined-turn check. Leave the worker-specific check intact.
4. [src/otto/hostctl/project_service.py:492](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/project_service.py:492) → Set `native_capacity.total_limit` to `policy.total_turn_units`. Keep the worker, manager, and heavy ceilings as they are.

## 2. Failing test to write first

File: `tests/test_hostctl_project_service.py`. Name: `SharedHostAdmissionTests.test_status_reports_admitted_turn_limits`. Existing imports suffice.

```python
    def test_status_reports_admitted_turn_limits(self):
        cases = (
            ("default", CapacityPolicy(), (8, 6, 6)),
            ("configured", CapacityPolicy(
                turn_units=4, manager_reserve=1, heavy_headroom=2,
                worker_floor=1), (5, 4, 4)),
        )
        for name, policy, expected in cases:
            with self.subTest(policy=name), tempfile.TemporaryDirectory() as directory:
                home = Path(directory)
                config = {
                    "home": str(home),
                    "owner": {"actor": "owner"},
                    "store": {
                        "authority": "status-test",
                        "domain_descriptor_digest": "digest",
                    },
                    "hosts": {},
                    "max_active_manager_turns": policy.manager_units,
                }
                host = SimpleNamespace(
                    bounded_transports=True,
                    capacity=SimpleNamespace(policy=policy),
                    capacity_holds=lambda: {},
                    _executions={},
                    _capacity_holds={},
                )
                router = SimpleNamespace(host=host, store=object(), services={})
                service = ProjectOwnerService(config, router=router)
                capacity = service._status()["native_capacity"]

                self.assertEqual(
                    tuple(capacity[key] for key in (
                        "total_limit", "worker_limit", "manager_limit")),
                    expected,
                )
                self.assertEqual(policy.total_turn_units, expected[0])
                self.assertTrue(policy.admits_turn("worker", expected[1] - 1, 0))
                self.assertFalse(policy.admits_turn("worker", expected[1], 0))
                workers, managers = policy.worker_floor, expected[2]
                self.assertEqual(workers + managers, expected[0])
                self.assertTrue(policy.admits_turn("manager", workers, managers - 1))
                self.assertFalse(policy.admits_turn("manager", workers, managers))
                self.assertTrue(policy.admits_turn("worker", workers - 1, managers))
                self.assertFalse(policy.admits_turn("worker", workers, managers))
```

On `canon/main`, the first status assertion fails: it reports `(6, 6, 6)` instead of `(8, 6, 6)`. The configured case uses the policy already exercised by [tests/test_compose.py:419](${TRANSFER_ROOT}/source/otto/tests/test_compose.py:419).

## 3. What to delete

Delete the inline `turn_units + manager_reserve` expression in `admits_turn` and the incorrect `policy.manager_units` reference for `total_limit`. No file or alternate capacity path needs deletion.

## 4. Plausible mistake

Using `total_units` would report 11 by including three heavy-only units. Hardcoding 8 in status would fix the default while leaving the configured case wrong. The test rejects both and requires the shared policy property.

## 5. Existing expectations and D19

**No existing assertion needs changing; no D19 decision is needed.** [tests/test_capacity_pool.py:323](${TRANSFER_ROOT}/source/otto/tests/test_capacity_pool.py:323) still expects ledger `total_units == 11`. The existing manager-limit assertion and the compose ready-payload assertion retain their meanings.

## 6. Stale or imprecise row text

`native_capacity` comes from **owner service status** at `ProjectOwnerService._status`; [project status](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/cli.py:518) does not return that field. Also, PERCH stage 2 specifies `pool_limit=2` and `manager_reserve=1` as observation thresholds, not a full `CapacityPolicy` with a worker floor and heavy headroom. Its three expected status ceilings therefore cannot be derived from that canary file alone. The configured policy test above is grounded in `canon/main`; calling it “PERCH2C’s limits” would overstate the evidence.

This was a read-only design review. I did not run tests.