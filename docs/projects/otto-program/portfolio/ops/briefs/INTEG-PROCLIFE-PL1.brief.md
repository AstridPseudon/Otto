# Brief: INTEG-PROCLIFE-PL1 (xhard, 0.75 focused days)

**Outcome:** Correct generic fleet custody birth identity to use an exact kernel identity and preserve uncertainty when unavailable; integrate commit `964120e` without losing escapee discovery or safe signalling.

**Why it matters:** A PID may be reused within the display-time precision of the current identity. Custody must never signal an unrelated process after reuse.

**Your lab:** created by the launcher from current `canon/main`; work only there.

**Layer:** Herzchen fleet. New code belongs in `src/herzchen/fleet/`.

**Files you own:** `src/herzchen/fleet/custody.py`, `tests/test_fleet_custody.py`.

**Other files:** You may edit only additional files directly required by this outcome; report each and why.

**Do not touch:** `ops/bootstrap/perch.sh`, `ops/bootstrap/perch_report.py`, `tests/test_perch_report.py` (INVARIANTS); all files of running workers PINALL and INVARIANTS; `production/`, Stores, `~/.otto`, `~/.codex`, Codex projects/vision/Native5, or anything outside this lab.

**Build on what exists:** `src/herzchen/fleet/custody.py` already records `Proc.birth` in census and matches known process members by birth; inspect the existing birth identity representation and its callers before changing it.

**Your check.** Keep the focused fleet custody tests green and preserve all current assertions. Run changed test files with no env prefix: `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_fleet_custody.py`.

**Check command:** `/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_fleet_custody.py`

**Regression at the level the friction appears:** Same-second PID reuse must not match or receive a signal; unavailable kernel identity must retain uncertainty.

**Invariant:** A recorded process identity denotes that exact process lifetime.
**Plausible mistake:** Treating display-time precision as birth identity.

**Working rules:** Never stash or check out another commit. Don't run `ottoctl`; never pass it `--help`. Never wait or poll. Run tests to completion. The landing gate runs outside the sandbox where needed. On Codex, leave work for the launcher to commit; don't work around read-only `.git`. Any sub-agent uses `spawn_agent` with `model: "gpt-6-luna"`.
