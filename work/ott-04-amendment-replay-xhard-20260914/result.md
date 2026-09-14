# OTT-04 amendment replay and interrupted-stage correction

Source commit `5332885d6dfba8af89c3f10d3311714d744b9c42`, tree
`66db6877fb490850bc05723d782fcee3eabbd722`, closes the C33 replay and
interrupted-stage defect.

The owner service now persists a shared decision manifest containing the
complete logical amendment before running any partial stage. Public Store
receipts then classify plan, assignment, and attention stages as committed or
replayed. The consumer still receives only the finite `apply_amendment` and
`read_views` JSON endpoints.

The installed observation proves:

- first amendment: four committed stages, four events, no dispatch;
- exact retry: all four stages replayed, zero events, unchanged views reported
  honestly, outcome `improvement-already-applied`;
- changed same-key input: `InputChangedError`, zero event and state delta;
- interruption after decision and plan: two persisted receipts;
- close/reopen recovery: decision and plan replayed, assignment and attention
  committed once, outcome `improvement-recovered`;
- one plan event, one route event, one attention event, zero dispatch events;
- owner, usage, and running input pins preserved.

Focused validation passed: three source tests and two installed real-product
tests. The installed invocation had `PYTHONPATH` and `PYTHONHOME` unset and
reported Otto and Herzchen origins from site-packages. Fresh Otto wheel SHA-256:
`f2fffb0d51a0e38a674dd04171d4df20a2bbca3a6bc21bbe84d043db1826aee4`.

No public capability gap remains for this bounded correction. The requested
`gpt-5.6-sol` model switch was not available inside the host-fixed active
thread; no substitute worker or review was launched, and this route deviation
is retained in the launch manifest and result metadata.
