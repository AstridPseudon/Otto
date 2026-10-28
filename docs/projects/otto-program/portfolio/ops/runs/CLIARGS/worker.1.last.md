Resolved the test file’s import conflict, preserving the canon `HostOwnerService` assertions and CLIARGS argument-forwarding coverage. The resume check uses the authenticated `route retry` path, consistent with canon’s owner-only restriction on direct native resume.

The requested check passed: **31 passed, 11 subtests passed**. `git diff --check` passed, and the file has no conflict markers.

`git status` still shows the test file as `UU`: staging failed because the worktree’s Git index is outside the permitted lab path. The file content is resolved, but the launcher will need to stage it. No commit or rebase completion was attempted.