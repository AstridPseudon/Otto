I fixed the manager journey’s package import, the native capture timestamp comparison, and the historical report lookup in status reads. No test assertions were changed.

**Green evidence:** the admitted-abort capture test passed, and all three `test_d03_status_reads.py` tests passed.

**Still red or unverified:** completion tests now reach an evidence-read failure: the manager cannot verify a private, owner-maintained source document. The shared assessment API uses the same actor for evidence reads and approval, so the current Otto wiring cannot grant the owner’s read access while retaining the manager’s approval identity. The normal/XHARD dispatch test exceeded the 30-second command window; I stopped it under the lab rule. I also haven’t completed the full focused suite or confirmed the project-folder result.

The work is uncommitted, and I have not rebased. **May I extend the file scope to the shared Herzchen assessment/content read path to separate owner-authorized evidence reads from manager approval, or is there an expected Otto-level adapter for this case?**