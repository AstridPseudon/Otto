The lab commit `2b0fbd7` is already based on `canon/main` `8edc104a`. I reproduced the reported `AttributeError` at the historical ROSTERPIN merge.

I changed only [tests/test_rosterpin.py](${ORIGINAL_HOME}/Developer/otto-claude-host/labs/ROSTERPIN/tests/test_rosterpin.py:78): D is assigned, then an actual owner start is attempted and refused at admission. A still reaches the provider. The historical failing case now passes, and the requested focused check reports **8 passed**.

Commit `5c8696d` is in the ignored lab-local Git store at `build/rosterpin-git`. **Blocker:** the sandbox cannot write the linked worktree’s Git metadata outside the lab, so the original `lab/ROSTERPIN` branch remains at `2b0fbd7`. With Git metadata write access, attach the existing commit from this lab using:

```sh
git fetch build/rosterpin-git lab/ROSTERPIN
git reset --mixed FETCH_HEAD
```