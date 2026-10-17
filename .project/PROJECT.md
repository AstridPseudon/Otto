# HARNESS3: progress

Base: canon/main 163925e. Log: `<UTC> | <TASK> | merged <sha> | +a/-b | tests run | notes`

## Log

2026-10-17 19:42 UTC | H35 | merged 6e310ed4b5c1c87330cd7671df92aadd24fdd508 | +75/-0 | git diff --check; 11 documented paths exist; no tests (docs) | cold Luna attempts both ~2 min, all four prompts correct

## Questions for the orchestrator

- H31 requires choosing a real third CLI and supplying authentic protocol evidence. No surveyed third CLI is installed on PATH (gemini/opencode/aider/goose/amp/cursor-agent/qwen); please choose/provide the CLI and evidence before H32 can proceed.
- The literal goal “no host name appears outside `herzchen/fleet/hosts`” conflicts with named profile, admission, native verifier, usage-accounting and protocol data. The baseline is 220 named lines in 38 source files outside that package. H34 will remove executable host-specific branches; decide whether the broader identifier/data migration is in scope.

## Blocked tasks

- H31 is blocked until the orchestrator selects a real third CLI and supplies authentic launcher/protocol evidence.
- H32, H33 and H34 are blocked by that dependency chain; H36 is blocked by H33/H34 and also needs live benchmark evidence.

## Needs the gate

- H32: native CLI launcher and write-fence probe (not run; H31 is blocked).
- H33: native CLI probe and actual owner/staging journey, including any checks requiring `sandbox-exec`, `ps` or a staging owner (not run; H32 is blocked).
- H36: nine authentic same-task runs with acceptance and usage receipts (not run; H33/H34 are blocked).

These checks were not attempted, so there were no sandbox failures to report. H35 needed no gate and no tests; its documentation check and cold-agent acceptance passed.

## Final Astra review

Astra reviewed `git diff 163925e...proj/harness3`. It found no H35 documentation defect and confirmed the +75/-0 task merge. It identified missing blocked/gate status in this progress file and a duplicate Questions heading. I accepted both findings and recorded the blocked tasks and unrun gate checks above; no implementation changes were suggested.
