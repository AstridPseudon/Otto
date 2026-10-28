Automatic retained workers now reach `app.start` without a manager occurrence; `admit_execution` remains the launch gate. Manager-prepared workers still require a verified manager Due. Known pre-effect failures record a reason and release the dispatch token, while uncertain attempts remain fenced. The fake owner pump test confirms that B starts after A completes, unadmitted C never starts, and a failed A does not stall B.

**Red/green:** The manager-occurrence regression failed on canon before the edit, and the known-failure regression failed against canon’s dispatcher binding. The required check now passes: **46 passed, 16 skipped**. The adjacent owner-pump check passes **2 tests**; `git diff --check` is clean.

**Commit:** None, as instructed. The lab remains at `589d184888ffbd8e25f61eb9fa7eb7a40e19ec3d` with edits only in the four owned files, ready for the launcher.

**Incomplete:** A real staging run needs the launcher’s committed snapshot. Also, after an asynchronous pre-effect failure, a *later revision of the same alias* remains held by its active Due; safely reusing that alias needs a separate canonical no-effect custody disposition.