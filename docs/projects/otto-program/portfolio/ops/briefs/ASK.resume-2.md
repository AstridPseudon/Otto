# ASK resume: repair landing failures

The previous landing was interrupted by a signal. Read `ops/runs/ASK/land.log` for the remaining `NEW failure` entries and repair them within ASK's already approved scope and the existing lab. Keep the invariant: an answer resumes exactly the asking session; a paused task never dispatches. Re-run the relevant focused checks. Do not attempt a landing or change the task scope; report what remains if a failure is unrelated or cannot be fixed within scope.
