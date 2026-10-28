## Implementation design

1. [src/herzchen/fleet/landing.py:322](${TRANSFER_ROOT}/source/otto/src/herzchen/fleet/landing.py:322) → Extract the configured-branch, HEAD-at-tip, and clean-status checks into a module-level `assert_line_checkout(repo, line_ref, *, git=None)`. Preserve the current error messages and `status --porcelain -z --untracked-files=all`. Move the default Git command code from line 350 into a module-level function; the injected `git` argument lets landing retain its existing Git hook.
2. [src/herzchen/fleet/landing.py:89](${TRANSFER_ROOT}/source/otto/src/herzchen/fleet/landing.py:89), [147](${TRANSFER_ROOT}/source/otto/src/herzchen/fleet/landing.py:147), [212](${TRANSFER_ROOT}/source/otto/src/herzchen/fleet/landing.py:212) → Call the shared preflight at all three existing landing points, passing `self._git`. The last check remains necessary because the checkout can change after preparation.
3. [src/otto/hostctl/product_service.py:610](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/product_service.py:610) → Keep the planned branch’s format and existence checks. At line 617, inside `_pair_lock`, call `assert_line_checkout(repo, "refs/heads/" + branch)` **before** `_pair` and the `fleet.get`/`fleet.create` choice. This covers both new and reused labs without changing the generic `LabFleet.create` contract. [ManagerJourneyService calls preparation before constructing the worker execution](${TRANSFER_ROOT}/source/otto/src/otto/portfolio/manager_journey_service.py:2325), so refusal occurs before provider input.

## Failing test to write first

Add to [tests/test_fleet_custody.py](${TRANSFER_ROOT}/source/otto/tests/test_fleet_custody.py:290). It uses a real disposable Git checkout and fleet; the new test patches no product method.

```python
def test_prepare_worker_lab_refuses_unusable_line_before_creation_or_reuse(monkeypatch, tmp_path):
    from herzchen.fleet.landing import LandingError

    registry, task, _record, _token, repo = _fleet_registry_fixture(
        monkeypatch, tmp_path, plan={"repo": "repo-a", "branch": "planned-line"})
    project = registry.owner.graph.current(
        ResourceRef("fixture", "work.project", "project-owned"))

    def git(*args):
        return subprocess.run(
            ["git", "-C", str(repo), *args], check=True,
            capture_output=True, text=True).stdout.strip()

    git("branch", "planned-line")  # Valid plan; another branch is checked out.
    lab_dir = (repo.parent / (repo.name + ".otto-labs")
               / hashlib.sha256(b"planned-line").hexdigest()[:20] / task.ref.id)
    with pytest.raises(LandingError, match="configured line branch"):
        registry.prepare_worker_lab(project.ref, task.ref)
    assert not lab_dir.exists()

    git("checkout", "planned-line")
    prepared = registry.prepare_worker_lab(project.ref, task.ref)
    assert Path(prepared["workspace"]).is_dir()
    head = prepared["lab"].head()

    dirty = repo / "untracked.txt"
    dirty.write_text("dirty\n")
    with pytest.raises(LandingError, match="clean and at its branch tip"):
        registry.prepare_worker_lab(project.ref, task.ref)
    assert dirty.read_text() == "dirty\n"
    assert prepared["lab"].head() == head

    dirty.unlink()
    assert registry.prepare_worker_lab(project.ref, task.ref)["workspace"] == prepared["workspace"]
```

## Delete

Delete [LandingService._assert_line_clean](${TRANSFER_ROOT}/source/otto/src/herzchen/fleet/landing.py:322) after replacing its callers. Keep [LabFleet.create’s dirty-line guard](${TRANSFER_ROOT}/source/otto/src/herzchen/fleet/labs.py:313): direct fleet callers still need it.

## Likely mistake and decisions

Checking only the `fleet.create` branch would leave `fleet.get` able to hand out an existing lab while the line is dirty. The test creates a lab on a clean checkout, dirties the line, and requires reuse to fail while preserving the lab.

No existing test assertion needs to change, so no D19 decision is needed. In particular, `test_create_refuses_dirty_line` retains its expectation for direct `LabFleet.create`.

The row’s `labs.py:313` evidence describes a **dirty-line check during creation**, not a configured-branch or clean-tip check; reuse bypasses it. The other cited code locations are current on `canon/main`. I found no tracked `GITCUSTODY` or `LINECHECK` text there to verify “GITCUSTODY 5.” This was a read-only design review; I did not run tests.