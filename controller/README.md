# Controller adoption artifact

`launch_manager_once.patch` is a review diff for the existing operational source
at `../controller/launch_manager_once.py` relative to the manager worktree.
There is no runnable controller copy in this directory.

Before adoption, stop the owner service gracefully and confirm it has released
custody. Apply the diff to that existing controller and install the matching
committed runtime source, including `complete_task_from_command`. Restart only
through the existing owner service lifecycle. This change does not accept any
result, complete a task, launch a provider, or alter an unknown occurrence.

The diff was prepared against operational file SHA256:
`14152db8782de2cd5db0a62bd86b2a34d8fc22ffff149b56d8cee6073632306d`.
If that source changes, reconcile the diff before adoption.
