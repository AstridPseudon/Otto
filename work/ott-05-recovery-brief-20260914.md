# OTT-05 corrective continuation brief

This is the controlled continuation of the existing OTT-05 worker thread
`01a0a181-e38c-7c01-a655-ca5eb3d191ab`. The previous turn was stopped after
an observed manager-status polling loop before any product source or test was
written. Preserve its launch receipt and manifest; do not start another
worker or treat the prior turn as implementation evidence.

## Route and custody

Use the existing isolated checkout, with the requested route explicitly
`gpt-5.6-luna` and `model_reasoning_effort=high`:

`/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Otto-ott05-worker`

The accepted metadata base is commit
`7316b55e679bb391075d90f66a48078b0dd8f31a` and tree
`c3a1058500c02103b137a3a1f9b1baa123cd4ba4`. The current worktree has only
the untracked input manifest and launch artifacts; verify this with Python and
argv-based subprocess calls. Do not use zsh variables named `path` or `status`.

Read and verify, before editing:

- Original released brief: `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/ott-05-implementation-brief-v2-20260914.md`, SHA-256 `86b6fc9755f20d84bf7580a2a520f2f6f00e738f0a3d7481bd874aa266650977`.
- Worker manifest: `work/ott-05-input-manifest-20260914.json`.
- Accepted Herzchen source: checkout
  `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/.otto/portfolios/otto-herzchen-delivery/local/repos/Herzchen-gf01-consumer-separation-worker`, commit `b68d8f59712275229c24757664ca30d807d39e4a`, tree `ee1614fc37fdd096fb9640702e124e28a391d170`.
- Accepted Herzchen wheel SHA-256:
  `2681daaeb673cd636050c3805977a01a670ed6bcfc113fe9d85903af5eeae9bc`.
- Accepted current Otto product source: commit
  `5332885d6dfba8af89c3f10d3311714d744b9c42`, tree
  `66db6877fb490850bc05723d782fcee3eabbd722`, wheel SHA-256
  `f2fffb0d51a0e38a674dd04171d4df20a2bbca3a6bc21bbe84d043db1826aee`.
- Accepted evidence commit/tree:
  `6f9099ba54e5b866c1f4c0ea5f6b17405748b6aa` /
  `c6120ad219a2eae4a3f39fa441c679f6be4fab41`.
- Accepted Otto profile SHA-256:
  `9d277b810adcbeac445d5aff2fc31a8052cfa99b844696e11412a90d11744726`.
- P01 amendment:
  `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/periodic01-adopted-process-amendment-20260914.md`, SHA-256 `d5e6f6ee114913a31f8fce4fed7a1f835f089e0859ccd5ce7941e9f094951503`.
- Public API preflight:
  `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/ott05-public-api-preflight.md`, SHA-256 `81bd26d3daa76fa4ff307c1aeb194992df7d56eb82947e29488225d080c793dd`.
- Catalog:
  `/Users/hannahomalley/Documents/Codex/2026-09-13/can-x20/work/package/otto_herzchen_delivery_v11_2/plan/catalog.json`, SHA-256 `075f0301129f57e46003d518372747df4a68e6e086e5a63a1200ae333b53b013`.
- Adopted extraction map:
  `.otto/portfolios/otto-herzchen-delivery/plan/extraction-map.json`, SHA-256 `bea51be5e6721e20a21e6befc0cd75dd340af103f722f0d154a671721520e413`.

Record a versioned reconciliation artifact with the actual final manifest
hash and the stopped-worker status. Preserve the original launch receipt
unchanged.

## Execute implementation now

Stop polling manager/session/PID state. Inspect the accepted public Otto and
Herzchen APIs from the preflight, then make the first substantive product edit
under the allowed paths. Implement OTT-05, “repo/integration responsibility
and process profiles,” for criteria C20, C21, C27 and C31. The required
product paths are `src/otto/engineering/`, `profiles/otto/operating.md`, and
`tests/otto/test_release_records.py`; narrow package exports are allowed only
when documented by the manifest. Evidence belongs under worker `work/`.

The engineering boundary must provide typed, persisted records for stable
repository identity, remotes/target identity, baseline and target heads,
exact source-set entries, candidate/decision references, owner and separated
authority, selected process profile, and receipts/events. Reuse accepted
transaction/receipt/event and candidate/decision patterns, but do not claim
that existing work or host APIs are repository semantics.

Keep candidate selection, required checks, merge/source promotion, package
publication, and deployment as separate commands, authorities, rights and
receipts. Merge must not imply publication or deployment. Enforce expected
head/version/token and changed-source-set checks. Duplicate logical keys must
replay the original result; changed same-key input must produce a typed
conflict with zero unintended delta. Unknown runner outcomes and partial
promotion must remain visible and recoverable by the same owner, with
completed and pending steps explicit. No second scheduler, queue, allowance,
repository owner, auto-promotion, auto-publication or auto-deployment.

Represent hourly and 12-hour behavior as selected profile data while preserving
the accepted operating profile. Keep owner, check, promotion, publication and
deployment rights distinct, with no duplicate repository custodian.

## Required representative proof

Before broad tests, build/install a disposable candidate environment with the
current Otto wheel and accepted Herzchen wheel. Run the representative path
against installed site-packages, with both `PYTHONPATH` and `PYTHONHOME`
unset. Record module origins from that same invocation. The path must create
and read a repository/source-set candidate, record a required check and
manager decision, expose stale-head or partial-promotion behavior, and show
that publication/deployment remain separately unperformed. Use real shipped
public APIs and typed records; fixture-only or injected fake release success
does not satisfy this task.

Then run affected source and installed tests only. Include exact commands,
return codes, environment, origin paths, wheel hashes, source/evidence
commit/tree identities, candidate/check/merge/promotion/publication/deployment
observations, stale/changed/duplicate/partial/unknown/no-auto-publication
cases, rights mapping and unresolved gaps. Return separate source and
evidence commits/trees and a factual completion report. Do not edit Herzchen,
control/database, package seed, extraction map, or any other project source;
do not run reviews, gates, remote writes, publication, deployment, AST
transfer, INT-04 or OTT-06 rehearsal.

Do not finish with another status report. Finish with product edits, tests and
receipts, or a concrete public API blocker tied to an exact source symbol.
