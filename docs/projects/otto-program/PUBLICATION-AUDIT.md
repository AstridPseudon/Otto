# Publication audit

Scanned 4,235 unique reachable source blobs for private key blocks, GitHub/provider tokens and AWS access-key patterns: no matches. Independent Luna audit of branch-only commits found no new credential files, raw session transcripts, databases or local operational dumps. New control-package files passed the same pattern scan. This is a bounded audit, not a proof that every possible secret format is absent.

Already-published main includes synthetic probe transcripts, test canaries and machine paths. Some unlanded code also contains host-path defaults. Exact source/history is preserved, without rewriting shared history. These portability issues remain visible; no account credential is intentionally included. Public control files replace the source machine home prefix and omit operational session JSON/raw logs. The private ZIP retains selected original paths and checks.

Publication destination: existing AstridPseudon/Otto GitHub repository, its existing visibility unchanged. Only dated transfer refs and the handover branch are written; no main/default ref is updated.
