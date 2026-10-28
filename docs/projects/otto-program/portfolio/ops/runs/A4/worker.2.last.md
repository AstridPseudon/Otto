Fixed the registration dependency regression in `register.plan()`. Rebuilding parsed fields from bundle files had discarded the supplied `run` record, including portfolio apply’s in-memory `card_dependencies`. The plan now reparses task fields while preserving that run record. The generated-view authority guard remains unchanged.

**Checks**

- Focused card-dependency regression: **1 passed**.
- Exact bundle-and-serve check: **29 passed, 4 skipped, 3 failed, 2 subtests passed**. The three failures are manager-start tests blocked by `sandbox_apply: Operation not permitted`; the worker loop cannot reach its dispatch assertions here.
- `git diff --check`: passed.

Only `src/otto/hostctl/register.py` is modified. The fix is commit-ready on `lab/A4`; I did not commit or push.