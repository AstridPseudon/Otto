# FAILEDFENCE resume 1 (xhard)

The landing was refused by D14: the brief says `Herzchen fleet and Otto capacity recovery`, while the candidate changes 106 lines under `src/otto` and none under `src/herzchen`. Read `${TRANSFER_ROOT}/portfolio/ops/runs/FAILEDFENCE/land.log` and the current lab diff.

The task outcome is Otto's manager recovery of a failed worker and its project capacity fence. The changed implementation is in Otto portfolio/owner wiring, so resolve the Layer declaration against PLAN.md D14 and make it accurately say `Otto product`; do not move Otto-specific policy into Herzchen to satisfy a label. Verify `tests/test_herzchen_boundary.py` and keep the focused capacity check green. Do not invent the missing TRIAGE worker-turn decision; the existing report correctly leaves `claude_adapter.py` unchanged.

Do not weaken tests or change task outcome. If inspection finds a genuine generic Herzchen mechanism in the diff, place only that reusable mechanism there and leave Otto policy/wiring in `src/otto`. Report the D14 resolution, exact changes, and all check results. Work only in `${ORIGINAL_HOME}/Developer/otto-claude-host/labs/FAILEDFENCE`; do not commit or push. Keep long tests running to completion.

Follow the Codex rules in `${TRANSFER_ROOT}/portfolio/ops/brief-template.md`: the launcher commits on exit; any sub-agent you start is `spawn_agent` with `model: "gpt-6-luna"`.
