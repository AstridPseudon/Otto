## 1. Design, in implementation order

1. `src/otto/hostctl/config.py:64–75, 103–108, 139–143` → Add one shared validator for installation principals. It must require distinct owner, operator, and host principals; check prospective manager and worker principals against all three sets by **exact equality**. Keep worker naming otherwise unchanged, including assignment-scoped names. Call the validator when loading an installation, and make host-principal text exact at `host_entry`.
2. `src/otto/hostctl/service.py:526–533` → Validate a new host principal against owner, operator, and every other host **before** `join_host`, which creates its orchestrator assignment. Keep same-kind replay behavior.
3. `src/otto/hostctl/register.py:357–373` → Validate `registration["manager"]["principal"]` against `session.config` at the start of `materialize`, before task or role writes. Line 455 is too late.
4. `src/otto/portfolio/manager_journey_service.py:2214–2228` → Validate the submitted worker principal against the real server installation config immediately after input validation, before occurrence lookup, lab preparation, or `assign_worker` at line 2421. Give synthetic worker-service fixtures installation config; preserve their existing assertions.
5. Add entrance tests: manager activation with owner, operator, and host principals leaves the draft without tasks, assignments, or schedules; worker submission with each reserved principal leaves no worker assignment or Due; distinct manager and assignment-scoped worker principals prepare successfully.

## 2. Failing test to write first

Add to `tests/test_hostctl_cli.py`, in `HostctlCliTest`:

```python
def test_admit_host_rejects_reserved_or_reused_principal_before_identity_write(self):
    from herzchen.contracts import ResourceRef
    from otto.hostctl.owner import HostSession

    self._init()
    home = Path(self.home)
    installation = home / "installation.json"
    before = installation.read_bytes()

    def codex_identities():
        config = host_config.load(home)
        authority = config["store"]["authority"]
        assignment_id = "assignment-" + hashlib.sha256(
            (authority + ":host-join:codex:v1").encode()
        ).hexdigest()[:28]
        with HostSession(config) as session:
            return tuple(
                session.store.get_identity(ResourceRef(authority, kind, assignment_id))
                for kind in ("wrk.assignment", "wrk.responsibility")
            )

    for principal in (
        "otto-test-owner",
        "claude-code-orchestrator",
        OPERATOR,
    ):
        with self.subTest(principal=principal):
            code, reply = self._ottoctl(
                "service", "admit-host", "--host", "codex",
                "--principal", principal,
            )
            self.assertNotEqual(code, 0, reply)
            self.assertEqual(installation.read_bytes(), before)
            self.assertEqual(self.owner_service.call(codex_identities), (None, None))

    code, reply = self._ottoctl(
        "service", "admit-host", "--host", "codex",
        "--principal", "codex-distinct-orchestrator",
    )
    self.assertEqual((code, reply["outcome"]), (0, "admitted"), reply)
    assignment, responsibility = self.owner_service.call(codex_identities)
    self.assertEqual(assignment.payload["principal"], "codex-distinct-orchestrator")
    self.assertEqual(responsibility.payload["principal"], "codex-distinct-orchestrator")
```

## 3. Delete

Replace the inline operator/host collision condition in `config.py:139–143` and the operator-only admission check in `service.py:529–530` with calls to the shared validator. Do not add a second assignment-level policy path.

## 4. Plausible mistake

Rejecting a collision **after** `join_host` can leave both a `wrk.assignment` and its `wrk.responsibility` identity even if installation writing fails. The first test checks both identities and the installation bytes after each refusal. It also catches an operator-only guard that overlooks owner and duplicate-host collisions.

## 5. Existing expectations and D19

No existing test assertion needs to change. `test_operator_must_differ_from_owner_and_host_principals` already expects the operator collision to fail. Synthetic worker-service fixtures need representative installation config, but their behavioral assertions should stay intact. Any proposed change to an existing assertion requires a written D19 decision.

## 6. Stale points in the row

`config.py:139–143` already rejects operator/host equality, `service.py:529–530` already rejects a newly admitted host using the operator principal, and `new_installation` already rejects owner/operator equality. Thus the claim that *all* collision cases are accepted before the fix is stale. `manager_journey_service.py:2222–2227` is worker submission validation; manager assignment is created through `register.materialize`. I inspected `canon/main` read-only and ran no tests.