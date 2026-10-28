## Design

1. [tests/test_bootcfg.py](${TRANSFER_ROOT}/source/otto/tests/test_bootcfg.py) (new) → write the failing fresh-install test below first. It uses the supported `ottoctl install --create` path and makes no configuration edits.
2. [config.py:64](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/config.py:64) → have `new_installation` record `owner_composition.kind = "product-service"` with absolute `src`, `cwd`, `stdout`, and `stderr`. Use the source tree containing the executing `otto` and `herzchen` packages; set `cwd` to that `src` so Python’s first import location agrees with `PYTHONPATH`. Keep the exact venv interpreter path in `python`; resolving its symlink could discard venv behavior.
3. [cli.py:216](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/cli.py:216) → derive and check those package paths during `install`, then prevalidate the composition with `launchd_definition`. After Store creation or attachment, persist the installation and use the existing `write_launchd_definition` to publish `home/launchd/org.otto.owner.plist`. Report success and write the install receipt only when both artifacts exist. A publication failure must leave no claim that managed launch was installed.
4. [owner.py:112](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/owner.py:112) → create private `logs` and `launchd` directories with the other installation directories. Put stdout and stderr under `home/logs`.
5. [supervision.py:290](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/supervision.py:290) → retain the existing direct product argv and launchd policy. At [line 301](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/supervision.py:301), require `cwd` and both log paths to be absolute as well as `src`; the current check only requires them to be strings. `KeepAlive: {SuccessfulExit: False}` already expresses retry after an unsuccessful exit and no retry after an orderly stop.
6. [cli.py:845](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/cli.py:845) → select the product only for an explicit `product-service` composition. Before opening the Store, verify the running interpreter and imported `otto`/`herzchen` source match the installation pins. Preserve the explicit `shared-project-services` route for installations still awaiting cutover; refuse a missing or unknown selection.
7. [docs/host-onboarding.md:14](${TRANSFER_ROOT}/source/otto/docs/host-onboarding.md:14) → document the generated plist, its source and log paths, and how the operator loads it. Add the already-required `--operator` argument to the example.

## Failing test to write first

**File:** `tests/test_bootcfg.py`  
**Name:** `BootConfigTests.test_fresh_install_writes_launch_for_its_own_source`

```python
import os
import plistlib
import subprocess
import sys
from pathlib import Path

import herzchen
import otto

from otto.hostctl import config as host_config
from otto.hostctl.supervision import launchd_definition
from tests.test_hostctl_cli import HostctlFixture, OPERATOR


ENTRY = "import sys; from otto.hostctl.cli import main; sys.exit(main())"


class BootConfigTests(HostctlFixture):
    def test_fresh_install_writes_launch_for_its_own_source(self):
        code, result = self._ottoctl(
            "install", "--store", self._store_path(),
            "--authority", "otto-test-owner-v1",
            "--owner", "otto-test-owner", "--operator", OPERATOR,
            "--credential-ref", "otto-test-owner-credential", "--create")
        self.assertEqual(code, 0, result)

        config = host_config.load(Path(self.home))
        src = Path(otto.__file__).resolve().parent.parent
        self.assertEqual(Path(herzchen.__file__).resolve().parent.parent, src)
        self.assertEqual(config["python"], str(Path(sys.executable).absolute()))
        selected = config["owner_composition"]
        self.assertEqual(
            {key: selected[key] for key in
             ("kind", "src", "cwd", "stdout", "stderr")},
            {"kind": "product-service", "src": str(src), "cwd": str(src),
             "stdout": str(Path(self.home) / "logs" / "owner.stdout.log"),
             "stderr": str(Path(self.home) / "logs" / "owner.stderr.log")})

        path = Path(self.home) / "launchd" / "org.otto.owner.plist"
        self.assertEqual(
            path.read_bytes(),
            launchd_definition(config, label="org.otto.owner"))
        launch = plistlib.loads(path.read_bytes())
        self.assertEqual(
            launch["ProgramArguments"],
            [config["python"], "-c", ENTRY, "--home", self.home,
             "service", "run"])
        self.assertEqual(launch["WorkingDirectory"], str(src))
        self.assertEqual(launch["EnvironmentVariables"]["PYTHONPATH"], str(src))
        self.assertEqual(launch["StandardOutPath"], selected["stdout"])
        self.assertEqual(launch["StandardErrorPath"], selected["stderr"])
        self.assertEqual(launch["KeepAlive"], {"SuccessfulExit": False})

        env = dict(os.environ, **launch["EnvironmentVariables"])
        probe = subprocess.run(
            [config["python"], "-c",
             "import otto, herzchen; print(otto.__file__); "
             "print(herzchen.__file__)"],
            cwd=launch["WorkingDirectory"], env=env,
            text=True, capture_output=True, check=True)
        self.assertEqual(
            [str(Path(line).resolve()) for line in probe.stdout.splitlines()],
            [str((src / "otto" / "__init__.py").resolve()),
             str((src / "herzchen" / "__init__.py").resolve())])
```

On `canon/main`, the test fails at `config["owner_composition"]`. Add process-level checks using this **persisted plist**: launch and observe READY; force an unsuccessful exit, relaunch from the same definition, and verify a later generation, the same home/source, and one Store holder while a competing start is refused. Then request `service stop`, verify exit 0 and closed status, and verify the plist’s successful-exit policy leaves it stopped. Timeouts in these checks should detect hangs, never define success.

## Delete and decision points

- Delete the implicit “missing composition means product” fallback at [cli.py:849](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/cli.py:849). Fresh installs then use one selected product path; the old wrapper remains reachable only through its explicit legacy selection until cutover.
- **Plausible mistake:** writing a syntactically valid plist whose `PYTHONPATH` or working directory selects another checkout, or whose argv selects the wrapper. The first test checks persisted values and actual import resolution; the process checks exercise that same plist after recovery.
- **Existing test assertions changed:** none proposed, so no D19 decision is needed. If implementation changes an existing assertion, [land.sh:131](${TRANSFER_ROOT}/source/otto/ops/bootstrap/land.sh:131) requires a written D19 decision naming that test file.

## Row corrections on `canon/main`

`service run` already starts the product when `owner_composition` is **absent** ([cli.py:849](${TRANSFER_ROOT}/source/otto/src/otto/hostctl/cli.py:849)); it is `launchd_definition` that refuses the fresh install. The “absent on canon/main” comment in [test_compose.py:55](${TRANSFER_ROOT}/source/otto/tests/test_compose.py:55) is stale. No separate product-edition selector appears on `canon/main`: this design qualifies the launch against the exact executing package paths and interpreter, while a byte-immutable edition would require its own source qualification. `BOOTCFG`, `OWNERCLAIM`, and “INSTALLCUTOVER 4” are task references, not named records found in this tree.