Removed the five `MacWriteScope.preflight` patches and their paired `wrap` patches, restoring the hostctl tests’ original structure. The manager-loop fake and all other requested changes remain. No `patch(...MacWriteScope.preflight...)` calls remain in either hostctl file; the manager-loop fake’s synthetic scope override remains.

I did not rerun `test_hostctl_cli.py` or `test_hostctl_serve.py`, as requested. The other six listed files passed individually, and `git diff --check` passed.

Current HEAD is `6fcf447b64cc1f338b0685341b90c6ca9fe00acd`; the two hostctl-file restorations are uncommitted for the launcher.