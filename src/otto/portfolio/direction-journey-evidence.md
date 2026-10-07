# D06 candidate connected journey and installed evidence limits

Observed 2026-10-07. Worker assignment
`assignment-54e6ee4465885e0a9cdf6651404a@rev-2`, generation 1;
task `task-8fc2e94e82b7dd2f8aec85fc24d4@rev-1` (D06/B06);
project `project-7b9c5c6ab5edeb83d28f5559684d@rev-2`.
Principal `otto-direction-worker-xhard-1`; owner-delivered native session
`01a117b2-2eda-76a1-8d28-7323f9716244`;
logical request `direction-d06-xhard-implementation-v1:launch`.
The delivered role configuration selects `gpt-6.1-sol` / high. These are
delivered identity/model pins, not an independent provider telemetry audit.

## Disposition

Candidate verification is passing. **B06 is not complete:** the installed
client/service has no per-agent authenticated caller ingress or direction
commands. Worker authority permits candidate changes/tests and read-only
inspection, not live Store mutation, runtime adoption, service restart, provider
dispatch, task acceptance or project settlement. Root/manager must complete the
installed evidence and terminal operations. No installed connected journey,
second live authenticated adapter, or actual useful delegated native work is
claimed by these tests.

## Exact source and installed pins

Candidate root:
`/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/runs/otto-project-operating-setup-20261005/work/integration-owner`.
HEAD `5febd933c87d4ef9b9698550e1841d455810cda9`, branch
`otto-project-operating-setup-20261005`; existing D01–D05 dirt was included and
preserved. `git remote -v` returned no remotes. HEAD alone does not identify
the dirty candidate.

For the final 53-test run, all 134 `src/**/*.py` files were hashed. SHA-256 of
the sorted path-to-file-SHA-256 mapping, encoded with
`json.dumps(mapping, sort_keys=True, separators=(',', ':'))`, was
`cc8eca043f1c91813d51e38738383c9d6dbe34c0655bcfa6ff3c13e05c1fe7e7`.
Paths use the `src/` prefix relative to the candidate root. This Markdown
report is excluded from that executable-source manifest.

| D06 changed path | SHA-256 at final verification |
| --- | --- |
| `src/otto/portfolio/direction.py` | `8b822afb37c03c3b4794651da1a11a7a84a89682657e22a03976efbde3ca4a44` |
| `src/otto/portfolio/manager_application.py` | `7967d1c9d01bc228b1e3f316eb2ed8c2dca02e8114f3bf09e7ff5c396d375cb2` |
| `src/otto/portfolio/tests/test_direction_journey.py` | `00b4f449980bdc99611d65eb76d8317d1e5fb555823dce635fd1935eb1b60f8a` |

Controller root:
`/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/runs/otto-direction-agent-context-20261007/controller`.
Its `runtime-manifest.json` SHA-256 was
`bd31bbd9001a75fffd5b67e10094a0be396f8c014e1e2c4a7df40a04c7608e58`;
the manifest names source commit `5febd933c87d4ef9b9698550e1841d455810cda9`.
Read-only comparison of every manifest hash found **zero mismatches** across
121 installed runtime files, three installed entrypoints and 21 immutable
pack files. This verifies disk bytes, not which code an already running
process has loaded.

Installed entrypoint SHA-256 values:

- `manager_ctl.py`: `9622da0cc6ef096132e6dfc45cb9db23c3b3bf0e215e3b7a49f959a80f8459c4`.
- `operating_service.py`: `b99c0bccb86b3bac2afa243a3aead37dab73cc4e615e8341033ab0adff2a9462`.
- `s06_root_reply.py`: `1dac54d8bd522b71a446c0ec1a3657596247746bb82fab7bae93a976c0de5860`.

Adopted resource pins retained from the gateway brief:

- Selected pack `direction-bootstrap-20261007-v1-selected-pack@rev-1`,
  content SHA-256 `7fe1450c369314700e4b8e5236f4ca76ec5dfa2a259e1b1efc1483c793b13832`;
  pack source `f0f326eb98131d425dc7a735169725f9e172eede`.
- Role configuration `direction-bootstrap-20261007-v1-role-configuration@rev-1`,
  content SHA-256 `c2ae74011514006dc852285492157fa49de7b16ddd3fd5df89a29fc969abf11c`.
- Run contract `direction-bootstrap-20261007-v1-run-yaml@rev-1`,
  content SHA-256 `6a37c63e2c47ad81b42b85b03a34a8427dcdcdde16e5b64fa67ccb643c59ba79`.
- Point-of-use guide `direction-bootstrap-20261007-v1-point-of-use-guide@rev-1`,
  file SHA-256 `8b6ecaf629f8e18e7000c2b11ae69df4e1a886a398bdf35413d6f7ba97a93a87`.

Pack/skill reads used `controller/selected-pack-source/` and its relative
references. Editable candidate pack paths were not used as adopted resources.
Gateway brief SHA-256:
`f7f3cad3a8b3c56e380705cf4ccbb74b543ca961d52295667b394b34b29f6856`.

## Changes and focused verification

`direction.py` now permits exact recovery of an already committed composed
scope/assignment update after the assignment pin advances. It requires both
retained boundary receipts and the exact assignment target; existing scope and
Work ports still validate request digests and actors. A new request against the
stale pin is rejected; a changed resource retry returns a replay conflict
without mutation. Current CAS/generation/status fences remain for new effects.

`manager_application.py` now accepts the typed subject passed by the history
facade, reads occurrence context refs from Due, and returns the exact retained
brief and its native evidence digest. It does not read the latest document to
substitute for old delivered context. Native user-message bytes are represented
by their retained digest evidence; this projection does not promise full raw
transcript text.

Exact final command, from the candidate root:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD/src:$PWD" \
  /Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/bin/python3.9 \
  -m unittest -q \
  src.otto.portfolio.tests.test_direction_bindings \
  src.otto.portfolio.tests.test_direction_resolution \
  src.otto.portfolio.tests.test_direction_invocation \
  src.otto.portfolio.tests.test_caller_context \
  src.otto.portfolio.tests.test_direction_surface \
  src.otto.portfolio.tests.test_direction_journey
```

Result: **53 tests in 10.585 seconds, OK, exit 0**. This includes the three
new D06 connected tests; the earlier 50-test baseline and focused three-test
runs overlap and are not additional unique coverage. `git diff --check` passed.

## Evidence coverage

| Scenario | Observed proof | Limit |
| --- | --- | --- |
| Inspect unbound; bind retry and changed identity | Owner-bound surface; no changed Store counts on same binding or rejected identity change | Disposable Store |
| Prepare, substantive delivery, useful delegation | Real application/gateway/native parser with fabricated native input; existing manager worker composition publishes one inspected result | Provider, host admission and repair commands are fixtures; no live work |
| Draft without adoption | Latest advances; scope and assignment stay pinned; continuation prompt excludes draft content | Candidate composition |
| Explicit update and future preparation | Scope differs from assignment until Work adoption; refreshed mandate; prepare then owner reopen delivers exact new revision | Existing queued assignment boundary, not arbitrary running-assignment adoption |
| Exact request recovery | Committed update recovers after reopen; tampered retry and stale new request do not mutate; completed occurrence recovery adds no provider call | Canonical fixture ports |
| Replacement and reused display name | Same enduring responsibility/document; new session and generation; old binding and copied generation/session fail | Fixture native evidence |
| Same payload, independent caller contexts | Shared real candidate file dispatcher returns separate principal/assignment/direction; copied caller principal fails; child target authorized only for manager | Host explicitly injects trusted bindings; filenames are not authentication |
| Second adapter contract | Stub Unix connection receives the same canonical resolution as file ingress | Contract variant only, no second live authenticated transport |
| History after update/replacement | Four original manager occurrences retain refs, exact old brief, matching digest and native evidence | Delivered-render digest evidence, not raw transcript storage |
| Unknown effect | Draft, reopen and recovery preserve original gateway attempt and scope adoption; exactly one provider-fixture call | No live UNKNOWN was touched or replayed |
| Role/error parity | Retained D01–D05 tests cover worker, manager, orchestrator, enabled/disabled advisor, missing inputs, unauthorized scope, spoofed sessions and conflicting pins | These remain isolated fixtures |

## Installed operation and operational-help request

The actual installed command executed was:

```sh
/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/bin/python3.9 \
  /Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/runs/otto-direction-agent-context-20261007/controller/manager_ctl.py --help
```

Exit 0. Its listed commands include operating-setup and help, but no whoami,
effective-context or direction operations. Read-only source inspection found
`operating_service.py` constructs `ExecutionHost` without a caller binding
reader/resolver. The installed runtime snapshot predates the retained candidate
direction/caller modules. No live command was submitted to file IPC: doing so
would write controller request state, outside this worker mandate. No Store was
opened in the controller; no service was restarted.

**Operational help to the assigned manager/root:** provide the supported
installed identity-bearing ingress and coherent candidate adoption, preserving
canonical Store, resource/generation/mandate pins, review counters and uncertain
effects. A runtime copy alone is insufficient: the host must resolve two
independent authenticated caller contexts outside JSON/prompt/name fields and
expose the maintained operations. If no trusted binding is available, assign
the remaining host-composition correction to its accountable owner; do not
interpret injected fixture bindings as completion of D03 or B06.

Return condition: actual installed receipts for both callers submitting the
same payload, spoof/cross-caller denials before effects, binding/delivery/useful
work/draft/update/continuation/replacement/recovery/history, preparation across
authorized adoption/restart, exact received resource/native evidence and
supported task/project terminal records. The worker returns candidate evidence
only. Task/project settlement and acceptance remain manager/root responsibility.
