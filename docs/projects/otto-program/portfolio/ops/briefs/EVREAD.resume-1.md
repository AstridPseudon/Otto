EVREAD scope grant and repair:

You may also edit `src/otto/portfolio/owner_bootstrap.py` to pass an owner-issued evidence read grant scoped to the evidence requested by this assessment. This is needed because the owner identity and grant are assembled there, while the assessment receives only the manager actor. Do not derive access from document maintenance, and do not run approval as the owner. Keep approval attributed to the manager and preserve refusal of direct/general manager reads. No running worker owns this file.

First verify the six completion selectors still reproduce on rebased canon. Implement the narrow grant handoff across `src/otto/portfolio/owner_bootstrap.py`, `src/herzchen/domains/assessment/module.py`, and `src/herzchen/content/reads.py` as needed, with tests in the two already-owned test files. Do not widen beyond the newly granted owner composition file and the original brief files. Run the original task check to completion with a long timeout:
`/opt/homebrew/bin/python3.11 -m pytest -q -p no:cacheprovider tests/test_completion_project_refresh.py tests/test_local_assessment_composition.py`

Report red and green evidence, prove approval remains manager-attributed, and show direct manager read still refused. Never run the whole approval as the owner. On Codex leave changes for the launcher to commit. Long test runs must run to completion; any sub-agent is `spawn_agent` with `model: "gpt-6-luna"`.
