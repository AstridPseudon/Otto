# D06 installed connected Evidence proof

This is candidate-workspace proof for D06/B06. It is not task acceptance,
owner-state publication, final Astra review, or project completion.

## Reproduction

Run from the adopted `integration-owner` workspace:

```sh
ASTRID_SOURCE_STATE=/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/runs/otto-evidence-lifecycle-20261009/controller/evidence/d06-managed-installation/source-state.json \
PYTHONPATH=/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/runs/otto-evidence-lifecycle-20261009/controller/runtime-source:/Users/hannahomalley/Developer/astrid-video/astrid-local/Astrid \
/opt/homebrew/bin/python3.11 tests/test_d06_installed_evidence_journey.py
```

Observed result: `Ran 1 test ... OK`.

The test uses the installed runtime package from `controller/runtime-source`,
the public managed-pack loader, the adopted managed pack, and a disposable
fixture `Store` under a temporary directory. It does not open or modify the
canonical operational Store.

## Identity and pins

- Source/runtime commit: `456c412e86eafb7b33a120327be727a9d43479bc`.
- Candidate and installed `herzchen/evidence/commands.py` SHA-256:
  `f7d5d459560d62a8c7cad30d1fc2b3a0afb7f5b5a006a680000f89d04e6caf84`.
- Managed source state:
  `controller/evidence/d06-managed-installation/source-state.json`, SHA-256
  `8d008340655907f05598a811625647d9d6d0a5b20c142ff6e16f9ce2d814bdaa`.
- Installed pack: `evidence` version `1.1.0`, host contract
  `herzchen.evidence.host.v1`.
- Pack source revision:
  `4abffbb0959e5dc92b2bdc306ca11ae81f77a649`.
- Pack tree SHA-256:
  `328a1827feae8f8a0ed4fc5cf765773ca68defaa87e2d4ef95c47aca41d4e30f`.
- Pack manifest SHA-256:
  `abfffa505a45c22fb5d7e86146fc10c018cbd6e4cfccb75ba05ef6b24457e459`.
- Selected resource digest set was resolved and compared before admission;
  selection digest:
  `4707ad35df28b47a4c9d8b5ba328efc481e9eda44577de3c518a3822e58b4da1`.
- Installed Otto skill SHA-256:
  `55016fd0930c1791e6d85a991c19cb863bd3e3d4cec064b890d2e6e5f3a95dd5`.
- Installed Evidence skill SHA-256:
  `bbdd205d6d49a25f6cf3abaebae1db49791f897830507c8355d39c2af218bd9a`.

The ten selected resource pins were:

```text
policies/provenance.json       21f9760df7280e89144c8246512b0e4f69e86dc25e2b36fd2c9062699e622bf3
presets/list.json              c576633b5b29952248710d4a19bbb7c7f19beae578b61246799e4c6f24a81c24
presets/read.json              d849128e269619f85efd0f6ffc74deef7ddf933b150bb61c95e4942434151c8a
presets/reclaim-apply.json    cd180c3160560a397437356436813a809d41538220e64459a186d592139b0220
presets/reclaim-preview.json  6ce66fa992bc1d441609cf745f7776c72c1f8ffa5c96c401f9b1312bcfc7cd44
presets/submit.json            966dc91be748182027fbc912888fd611e2fa51cc5e25e08a11198d2823e31f61
presets/version.json           0d51235ea3344b47005dd439bd3a00110ef8ca26b9b63329219758a5dbfbc4aa
schemas/evidence.json          41c67848aebb8f44d8f35563074b50b7a5feb0e689999cd91cb29847c3332fec
skill/SKILL.md                 bbdd205d6d49a25f6cf3abaebae1db49791f897830507c8355d39c2af218bd9a
templates/evidence.json        6b43aaecd04652edc5fb790e9f57656dffc2eba496e4eef79bace899c9694684
```

## Connected journey result

- Captured 1,048,576-byte text and 1,048,576-byte binary payloads through the
  installed `EvidenceCommandHandler` and the selected pack.
- Read offset `123`, capped at `64` bytes; returned `64` bytes with
  `verification=range-not-revalidated` and no full-payload hash.
- Cited exact revision pins, created a lazy `evidence/` checkout, and
  materialized one selected binary read-only. No `docs/` or `project.json`
  was materialized.
- Created a selected directory bundle with two included exact pins and a
  manifest inventory. The bundle asserts neither authority transfer nor
  exported-copy revocation.
- Reclaim preview/apply selected project history. Apply removed exactly
  `2,097,152` managed bytes and preserved two tombstones with decision history.
- One third payload remained present with held reason `shared-reference`.
- Disabling the workflow reported `data_preserved=true` and
  `new_workflow_admission=false` after the reclaim; existing records were not
  deleted by disable.

## Host identity and handles

The exact installed client used for read-only host inspection was:

```text
/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/bin/python3.9
/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/runs/otto-evidence-lifecycle-20261009/controller/manager_ctl.py
```

`whoami` and `effective-context` both returned read-only trusted binding
evidence for principal `otto-evidence-d06-worker-1`, assignment
`assignment-1b2b2e4a7e7a19f369ea74201cf9`, task `task-4c65ca3e4e31669a0d5ac5de15f7`,
project `project-1a0a32aa681b82db0da5c844cc07`, generation `1`, role `worker`,
and native session `01a123b8-e0f0-74f3-8ad1-8fc8b7badf34`. Their retained outer
request IDs were `1168576505884ccaac2df3f0f54235aa` and
`e0def679bb444d8c9ed203eb5f5bb4c5` respectively; both reported
`effects_started=false` and `provider_called=false`.

The delivered canonical manager context identifies representative manager
principal `otto-evidence-manager-1`, role `manager`, assignment
`assignment-7f8cdfbe280731995ade2adc8dff`, selected pack resource
`evidence-D01-managed-pack-correction-context-20261010-v1-selected-pack`, and
the same installed source commit. The leaf worker did not impersonate or
re-open the manager socket.

No child was delegated by this leaf, so there are no child/start/transport
handles to report. The current launch occurrence is the owner-delivered
logical key `evidence-D06-B06-worker-v1:launch`, schedule
`worker-17c55aae6ade46dff26e71b9e14f`, native session above, and owner delivery
physical session `01a123b8-e0f0-74f3-8ad1-8fc8b7badf34`.

## Limits and unresolved responsibility

This proof covers one disposable connected journey only. D01-D05 evidence is
reused rather than replayed; this run does not re-qualify their interruption
matrices or the configured final Astra review. The worker does not accept the
task, write owner state, adopt/install runtime, publish, push, deploy, or claim
project completion. Manager/owner responsibility remains to inspect this
candidate, reconcile the retained result, perform the configured assessment and
closeout, and report any remaining installed-proof gap.
