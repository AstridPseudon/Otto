## Design for BOOTLAND

Line numbers below are from `canon/main`. Publication is complete only when the remote is confirmed to contain the merge of the checked SHA. A later gate must resolve that publication and its cleanup before working on its own task.

1. [ops/bootstrap/land.sh:36](${TRANSFER_ROOT}/source/otto/ops/bootstrap/land.sh:36) → After validating the task name, acquire a nonblocking POSIX `fcntl.lockf` lock on a persistent regular file at `land.lock`, before lab preconditions. A small Python entry wrapper can acquire the lock and `exec` Bash so the gate process owns it; process death releases it. Keep the file’s inode and preserve the single `LAND RESULT` line on lock refusal.
2. [ops/bootstrap/land.sh:50](${TRANSFER_ROOT}/source/otto/ops/bootstrap/land.sh:50) → Under that lock, fetch and reconcile any previous landing *before* checking the requested lab. Identify an unfinished `Land TASK` merge using its Git parents and that task’s `BASE`/tested-commit log evidence. If remote `main` contains the merge, preserve local main and finish the prior task’s cleanup. If remote `main` is exactly the merge’s first parent, restore local main to that parent, leave the prior lab retriable, and refuse the new task if its branch descends from the discarded merge. If the evidence or remote relationship is ambiguous, refuse without resetting. A retry of the already accepted task should report its confirmed landing.
3. [ops/bootstrap/land.sh:108–115](${TRANSFER_ROOT}/source/otto/ops/bootstrap/land.sh:108) → Save the rebased lab tip once as `TESTED_SHA`. Keep its full SHA in the log.
4. [ops/bootstrap/land.sh:436](${TRANSFER_ROOT}/source/otto/ops/bootstrap/land.sh:436) → Give staging `TESTED_SHA` and check reports against it; remove the later, independent read of lab HEAD.
5. [ops/bootstrap/land.sh:456–468](${TRANSFER_ROOT}/source/otto/ops/bootstrap/land.sh:456) → Retain the remote check near publication. Immediately before merging, require `canon/main == BASE`, lab HEAD and `lab/TASK` both equal `TESTED_SHA`, and the lab is clean. Refuse on any mismatch. Merge **`TESTED_SHA`**, then log the full merge SHA and verify its parents are `BASE` and `TESTED_SHA`.
6. [ops/bootstrap/land.sh:469–479](${TRANSFER_ROOT}/source/otto/ops/bootstrap/land.sh:469) → Treat a push error as an unknown outcome: fetch and compare remote `main` with the exact merge. If it contains the merge, record publication and clean up. If it is exactly `BASE`, restore local main to `BASE` and refuse, leaving the lab. If fetch fails or refs diverge, retain the merge and refuse pending reconciliation. Use the same reconciliation after a crash. Do not let a later task push an unconfirmed local merge.
7. [ops/bootstrap/otto-lab.sh:26–40](${TRANSFER_ROOT}/source/otto/ops/bootstrap/otto-lab.sh:26) → Make `remove` safe to repeat after interruption between worktree removal and branch deletion. Archive and remove a present, clean lab; delete a remaining branch only after confirming it is the published merge’s checked parent. Reuse `remove` for normal and recovered publication; block the next landing if cleanup cannot finish.

## Failing test to write first

Add `LandGate.test_lab_advance_after_check_refuses_without_moving_main` to [tests/test_bootstrap_gate.py:125](${TRANSFER_ROOT}/source/otto/tests/test_bootstrap_gate.py:125). The check runs a real pytest file, then commits unchecked content. On `canon/main` now, the gate merges that later branch tip, so `assertRefused` fails.

```python
def test_lab_advance_after_check_refuses_without_moving_main(self):
    from shlex import quote

    lab = self.lab("T31", {"note.txt": "checked\n"})
    checked = sh(["git", "rev-parse", "HEAD"], cwd=lab).stdout.strip()
    advance = self.tmp / "advance_lab.py"
    advance.write_text(textwrap.dedent("""\
        import subprocess
        from pathlib import Path

        Path("unchecked.txt").write_text("unchecked\\n")
        subprocess.run(["git", "add", "unchecked.txt"], check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "advance after check"],
            check=True,
        )
    """))
    check = ("%s -m pytest -q tests/test_herzchen_boundary.py && %s %s"
             % (quote(sys.executable), quote(sys.executable),
                quote(str(advance))))

    result = self.land("T31", "--check", check)

    self.assertRefused(result, "T31", "lab HEAD changed")
    self.assertNotEqual(
        sh(["git", "rev-parse", "HEAD"], cwd=lab).stdout.strip(), checked
    )
    remote_head = sh(
        ["git", "--git-dir", str(self.remote), "rev-parse", "main"]
    ).stdout.strip()
    self.assertEqual(remote_head, self.base)
```

Add separate disposable-repo tests for the other acceptance cases: a real remote rejection followed by B must leave A unpublished; a Git transport stand-in that performs the real push but loses its reply must lead to A cleanup without reset; killing a locked gate must let the next gate acquire the lock, while a second live gate is refused. Assert Git refs and lab/branch state in each case. The transport stand-in replaces an external reply, not a product method; none of these tests needs a timer as its pass condition.

## Delete and review

- Delete the `LOCKED`/`mkdir`/`rmdir` directory-lock path at [land.sh:17, 21–24, 93–94](${TRANSFER_ROOT}/source/otto/ops/bootstrap/land.sh:93). Never unlink the replacement lock file.
- Delete the branch-name merge at [land.sh:464](${TRANSFER_ROOT}/source/otto/ops/bootstrap/land.sh:464), the duplicate staging SHA read at line 436, and the unconditional “local merge kept” push-failure path at lines 469–473.

**Plausible mistake:** resetting after a failed push solely because its command returned nonzero discards a merge the remote accepted. The lost-reply test proves remote containment before any reset; the first test catches the separate mistake of merging a branch that moved after its SHA was recorded.

**D19:** The existing assertions that `land.lock` does not exist in [test_bootstrap_gate.py:145](${TRANSFER_ROOT}/source/otto/tests/test_bootstrap_gate.py:145) and [test_bootstrap_gate.py:224](${TRANSFER_ROOT}/source/otto/tests/test_bootstrap_gate.py:224) must change: a persistent lock file remains after release. A written D19 decision should name this file and approve replacing those assertions with lock reacquisition and live-exclusion assertions. The remote-ahead refusal expectation at line 409 should remain.

**Row accuracy:** Its cited `land.sh` lines identify the defects, but line 115 only *logs* the tested SHA; it does not retain it, and line 436 reads HEAD again. I found no tracked `BOOTLAND` or `GITCUSTODY` record on `canon/main`, so the numbered GITCUSTODY evidence cannot be checked from this checkout. No files were changed and no tests were run.