Task: OPERATOR-ADMIT.

Make the presence prompt name what is being approved: pass a reason built owner-side from the validated task ref's id and the revision (first 12 characters), e.g. 'Admit Otto task <id> at revision <rev>', into `LocalAuthenticationProver.prove(reason=…)` and its `localizedReason`; escape it for the Swift string literal (or pass it via an environment variable rather than splicing it into the source). Add one test that the injected prover receives that reason. Run the brief's check.
