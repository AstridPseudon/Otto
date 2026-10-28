# D19 decision: PYSTUB, tests/test_tools.py, tests/test_fleet_custody.py (the orchestrator, 17 Oct 2026)

**Decision: LAND.** No Opus call was made.

- `tests/test_tools.py`: the MCP grant's pin used to equal `[realpath(sys.executable)]`. It now equals that plus, for a framework Python stub (Homebrew's `bin/python3.11`), its own `Python.app/Contents/MacOS/Python` re-exec target. That is the row's change: the fence must admit the interpreter's re-exec target by literal path, or the child dies at launch (`posix_spawn … Undefined error: 0`, reproduced with `sandbox-exec` on 17 Oct). The worker's version compared the pin with the output of the function under test; I rewrote it (52d40cd) to spell the expected paths out.
- `tests/test_fleet_custody.py`: new cases only (literal policy expansion, a worker launched with Homebrew Python under the real fence, an unpinned executable still denied); 22 passed outside the sandbox.
