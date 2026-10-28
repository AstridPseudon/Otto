Implemented the CLI argument handling changes:

- Route and execution-control parsers now omit absent optional fields, so irrelevant null values aren’t forwarded.
- The service treats explicitly supplied null recovery fields as a recovery request and rejects incomplete requests, foreign fields, and fields used with the wrong operation.
- Added parser-to-launched-client-to-authenticated-service coverage for reroute, retry, read, recover, and resume, including missing and foreign fields.

The requested check passed: **29 passed, 11 subtests passed**. `git diff --check` also passed.

Only the three files listed above are modified. `ops/brief-template.md` was not present in this checkout; the brief’s restrictions were followed. No commit or push was made.