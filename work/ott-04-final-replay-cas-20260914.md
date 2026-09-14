# OTT-04 final replay/CAS correction — 2026-09-14

The shipped owner engine now treats the caller-supplied `expected_version` as
part of the complete logical replay identity. It no longer derives the replay
precondition from the historical receipt. Source correction commit:
`54c3776b1dc466656df527724db5daa0b60f9dca`, tree
`624b6fc0ea97e169d2d216e536644a2463d848e7`.

The bounded sequence is recorded in the raw source and installed observations:

- A creates version 1 with expected version 0.
- B legitimately updates to version 2 with expected version 1.
- A with exact original input and expected version 0 replays historical result
  version 1 / `rev-1`, with zero event delta; fresh live state remains version 2.
- A with unchanged record but expected version 99 raises typed
  `InputChangedError`, with zero event delta and live version 2.
- A with changed record remains `InputChangedError`; a stale new key remains
  `StateConflictError`; both have zero event delta.

Fresh wheel: `work/ott-04-correction-20260914/dist-final2/otto_local_candidate-0.0.0-py3-none-any.whl`
SHA-256: `1284ef086294fabd7afd539938cf3fecc9bd2581d02d403edce61886936440e3`.
Accepted Herzchen wheel SHA-256 remains
`2681daaeb673cd636050c3805977a01a670ed6bcfc113fe9d85903af5eeae9bc`.

Validation is limited to the affected continuity surface: source `8 passed`;
installed real-product selection `2 passed`, return code 0, with
`PYTHONPATH` and `PYTHONHOME` unset. Same-process installed origins are in
`logs/installed-focused-final2.txt`. Raw JSON and hashes are catalogued in
`ott-04-final-replay-cas-20260914.json`.

Earlier implementation, 53/53 campaign, receipts, observations, and the
previous correction commits remain historical and were not rewritten.
