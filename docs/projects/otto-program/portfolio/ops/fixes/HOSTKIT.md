# HOSTKIT: one fix before landing (resume message)

The program was paused after you finished 43a743d; it's resuming now. Your work is good: Claude and Codex are behind one contract in `src/herzchen/fleet/hosts`, and Herzchen imports nothing from Otto. Before it lands it needs one fix. Re-read `.brief.md`, and the "XHARD only: you lead, Haiku executes" section of `~/Developer/otto-program/ops/brief-template.md`: from now on, delegate the execution to the `haiku-worker` sub-agent.

**0. Rebase first.** `canon/main` has moved to 9739a29 (or later). It now has HOLD, TOOLING, TOOLING2, and SL9–SL12 from another session (Store leanness); SL12 changed `src/herzchen/command_ports.py`. Rebase `lab/HOSTKIT` onto the current `canon/main` and commit the resolution.

**1. Take Otto's vocabulary out of the fleet (PLAN.md D14).** The fleet is meant for any product that runs agents, so it can't carry Otto's names, roles or policies. Otto passes them in, and the fleet takes neutral parameters. Today, in `src/herzchen/fleet`:
- `hosts/claude.py:26`: `MANAGER_TOOLS` is Otto's manager role. Make it an allowed-tools set the caller passes in.
- `hosts/claude.py:18`: the parser schema id `otto.claude-code-2.1.293.stream-json.v1`. Use a fleet id, or let the caller name it.
- `hosts/codex.py:32`: the profile `otto-native-caller`. The caller passes it.
- `hosts/codex.py:99`: the Megado edition defaults. These are Otto's policy; Otto supplies them.
- `hosts/contract.py:30` and `:97`: token variables must be `OTTO_*`. Take the prefix as a parameter.
Otto's side (under `src/otto`) supplies today's values, so behaviour is unchanged. Your invariant still holds: no host's sandbox or session flags change.

**2. Make the boundary test check names as well as imports.** Extend `tests/test_herzchen_boundary.py`: parse each file under `src/herzchen/fleet` with `ast`, and fail on any string constant (docstrings excluded) or identifier that contains `otto` or `megado`, case-insensitively. Comments and docstrings may still mention them. Show it failing on the current code first, then passing.

**Your check:** your three named tests; `tests/test_herzchen_boundary.py`; and every test file that imports a module you changed, each run on its own, twice. Commit to `lab/HOSTKIT`, don't push, and report: the commits, the runs, the net lines by layer (`git diff --stat canon/main...lab/HOSTKIT -- src/herzchen src/otto`), and anything you couldn't finish.
