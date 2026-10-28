Cause: `OwnerService.call` returned `held` before checking presence when dispatch was active, consuming the operator request. Retrying it meant another presence check.

The owner poll now keeps admission requests queued until dispatch closes. If dispatch opens between the poll check and admission, it retains the same request and key for a later poll. Presence verification and the operator write remain in the owner.

Added regressions for admission after dispatch, exactly one presence check and log entry, and declined presence leaving the Store unchanged.

Focused check: **17 passed, 1 skipped**. `git diff --check` passed. No additional files were changed.