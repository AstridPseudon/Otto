# PERCH1: the cold-client save, and the staging admit (manager, 10:50Z)

Your commit d9eb886 is accepted as the base. Its scenario, assertions and faults are right. Two things remain, and this fix widens your files for them. A3 has landed, so `src/otto/portfolio/cli.py` no longer has a second writer, and you may now touch the files below. Nothing else in the brief changes.

## 1. The cold-client save (the row's acceptance: "a save through the socket from a cold shell works")

I checked your diagnosis in source and it holds: `src/otto/hostctl/portfolio.py:61-68` forwards only `status, documents, retire, sync-docs, apply, gate, prerequisite` to the owner, and validates every other command against `otto.portfolio.cli`'s parser, which has no `--portfolio`. `src/otto/hostctl/cli.py:859-866` takes the owner lane only when `args.portfolio` is set, and `save` never sets it.

Fix it with the smallest change that makes `ottoctl portfolio --portfolio P save FILE` reach the owner lane:
- add `save` to the forwarded set in `hostctl/portfolio.py`, and set `args.portfolio` from the parsed `--portfolio` for it (the same way `documents` and `retire` get their root);
- keep the `--help` and usage validation client-side for `save` as it is now (the client answers, the owner never parses).
- If `portfolio/cli.py`'s save parser needs a `--portfolio` option for this route, add it there and nowhere else in that file.

Then remove your `expectedFailure` marker on the cold-client test. It must pass for real.

## 2. Staging admits a portfolio (your second gap)

Add the admission step to `ops/bootstrap/staging.sh` (or to the canary's stage 1 setup, whichever is the single place staging is brought up). Derive the portfolio id from the same source the test fixture uses, not a guess, and add an assertion that the admission is in place before the save step runs. This must not change stage 0's behaviour: `perch.sh 0` still passes on its own.

## Checks

- The check command in your brief, unchanged. It must show the cold-client test passing, not xfail.
- A seeded fault for the new client route: a save with a mistyped portfolio id is refused with that id named, and the owner is untouched.
- Commit to `lab/PERCH1`, and report the commit, the red-then-green run, and the routes or files you changed in addition to your list.

Don't run `perch.sh` against the live machine. The landing gate runs stage 1 on staging.
