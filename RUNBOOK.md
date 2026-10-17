# Bootstrap landing runbook

## Staging evidence at landing

The landing gate runs `ops/bootstrap/perch.sh` only for the stage numbers listed in
`$OPS_DIR/stages-gated`. The file contains stage numbers separated by whitespace. If
the file does not exist, the gate defaults to stages `0 1`. It does not run `all` or
every stage automatically. The orchestrator adds a stage to `stages-gated` after that
stage has passed; a stage whose scenario is not ready does not block every landing.

For each selected stage, `land.sh` invokes `perch.sh <stage> --fake` on the tested
commit. This is fake diagnostic `stage-run` evidence: the harness worker is fake, makes
real commits in its lab, and uses no model. The gate records the diagnostic report and
checks that it names the tested commit. It does not establish that a real model reviewed
the stage. The separately required real-model stage review must be completed and
recorded on its own; a passing fake diagnostic cannot stand in for that review.

Keep the real-worker requirement for any stage whose acceptance requires real worker
execution. `--fake` exercises the diagnostic harness, not a real worker. A real worker
run is separate evidence and must be present before claiming that requirement passed.
