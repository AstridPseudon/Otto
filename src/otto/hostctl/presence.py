"""Owner-local macOS user-presence proof for task admission.

The prover receives no lane payload. Each call creates a fresh LocalAuthentication
context, forbids cached Touch ID reuse, and expires the pending evaluation.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
import platform
import subprocess
import tempfile


@dataclass(frozen=True)
class PresenceResult:
    status: str  # approved, declined, timeout, or unavailable

    @property
    def approved(self) -> bool:
        return self.status == "approved"


_SWIFT_PROBE = r'''
import Foundation
import LocalAuthentication
import Dispatch

let context = LAContext()
context.touchIDAuthenticationAllowableReuseDuration = 0
var availabilityError: NSError?
guard context.canEvaluatePolicy(.deviceOwnerAuthentication, error: &availabilityError) else {
    print("unavailable")
    exit(0)
}
let finished = DispatchSemaphore(value: 0)
var approved = false
guard let reason = ProcessInfo.processInfo.environment["OTTO_PRESENCE_REASON"], !reason.isEmpty else {
    print("unavailable")
    exit(0)
}
context.evaluatePolicy(.deviceOwnerAuthentication,
    localizedReason: reason) { success, _ in
    approved = success
    finished.signal()
}
if finished.wait(timeout: .now() + __SECONDS__) == .timedOut {
    context.invalidate()
    print("timeout")
} else {
    print(approved ? "approved" : "declined")
}
'''


class LocalAuthenticationProver:
    """Invoke Apple's device-owner authentication in the owner process's child."""

    def prove(self, *, reason: str, timeout_seconds: float = 30) -> PresenceResult:
        if (platform.system() != "Darwin" or not 0 < timeout_seconds <= 120
                or not isinstance(reason, str) or not reason or "\0" in reason):
            return PresenceResult("unavailable")
        source = _SWIFT_PROBE.replace("__SECONDS__", repr(float(timeout_seconds)))
        try:
            with tempfile.TemporaryDirectory(prefix="otto-presence-") as cache:
                env = dict(os.environ, SWIFT_MODULECACHE_PATH=cache, CLANG_MODULE_CACHE_PATH=cache,
                           OTTO_PRESENCE_REASON=reason)
                completed = subprocess.run(
                    ["/usr/bin/swift", "-module-cache-path", cache, "-"], input=source, text=True,
                    capture_output=True, timeout=timeout_seconds + 30, check=False, env=env,
                )
        except subprocess.TimeoutExpired:
            return PresenceResult("timeout")
        except OSError:
            return PresenceResult("unavailable")
        status = completed.stdout.strip().splitlines()[-1:] if completed.returncode == 0 else []
        return PresenceResult(status[0] if status and status[0] in
                              {"approved", "declined", "timeout", "unavailable"} else "unavailable")
