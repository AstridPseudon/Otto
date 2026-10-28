Native caller bindings are now constructed from serialized owner state on the owner thread before the useful Claude transport starts. The prepared binding registers the exact child synchronously before stdin is written. This replaces the late, potentially unowned binding construction path.

The barrier-controlled regression test checks concurrent preparation, owner thread affinity, exactly one binding per child, and binding before transport and input. The gateway’s owner-binding checks remain in place.

I also edited [claude_cli.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/OBSOWNER/src/otto/agents/claude_cli.py:480), outside the owned file list, because the required timeout test exposed a cleanup path that could leave its stand-in child alive when the process census was unavailable.

**Checks:** 28 tests and 9 subtests passed; `git diff --check` passed. Changes are left uncommitted.