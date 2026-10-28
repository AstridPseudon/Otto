**Commit:** `4145f22` remains the lab’s base commit. Changes are uncommitted for the launcher.

The requested pytest command passed: **25 passed**. The three regression checks failed against an archive of `4145f22`, then passed in the lab. `git diff --check` is clean.

Removed the project `sync-docs` command and three-way sync, its persisted digest baselines, portfolio apply’s project and shared-document sync, and the shared-document manifest, catalog, and tombstone copies. Vision’s shared-document reads now follow active DAT associations. Duplicate registration of a source folder is refused, including if its run ID changes.

Additional directly required source files edited outside the owned-file list:

- [cli.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/A6/src/otto/hostctl/cli.py): removed the project command and digest-baseline status fields.
- [register.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/A6/src/otto/hostctl/register.py): refuse duplicate folders and read activation documents from stored project documents.
- [portfolio_apply.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/A6/src/otto/hostctl/portfolio_apply.py): removed apply’s document-sync path.

No protected files changed. Nothing remains incomplete.