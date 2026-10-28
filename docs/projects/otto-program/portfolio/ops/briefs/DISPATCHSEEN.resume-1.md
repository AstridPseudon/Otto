# DISPATCHSEEN resume 1

The landing passed the focused check and all 16 sweep files, but the post-sweep custody census refused it:

`orphan service run(s) after sweep: pid 34580 home /private/tmp/st5/home`

Investigate which task-owned service/run this is, why it remains after sweep, and fix the task or its tests so the run is cleaned up. Preserve the landing gate's census coverage; do not weaken or bypass it. Do not kill or manipulate an unrelated live owner. Keep changes within the task's outcome and lab exclusions. Re-run the task's own check command from the brief and report the root cause and cleanup evidence. The existing launch and focused regressions are already committed; inspect the current lab after the required rebase before changing anything.

Do not touch files owned by any running task. No worker is running now.
