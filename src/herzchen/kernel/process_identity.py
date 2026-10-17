"""Exact kernel process birth identity shared by process custody callers."""
from __future__ import annotations

import ctypes
from dataclasses import dataclass
from pathlib import Path
import sys


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    parent: int
    birth: tuple[int, ...]
    uid: int


def process_identity(pid: int) -> ProcessIdentity:
    """Read the kernel birth token; raise when the process cannot be identified exactly."""
    if type(pid) is not int or pid <= 0:
        raise PermissionError("invalid kernel process identity")
    if sys.platform == "darwin":
        # Public proc_pidinfo/PROC_PIDTBSDINFO from the macOS SDK proc_info.h.
        class BSDInfo(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint32) for name in
                ("flags", "status", "xstatus", "pid", "ppid", "uid", "gid",
                 "ruid", "rgid", "svuid", "svgid", "reserved")]
            _fields_ += [("comm", ctypes.c_char * 16), ("name", ctypes.c_char * 32)]
            _fields_ += [(name, ctypes.c_uint32) for name in
                ("nfiles", "pgid", "jobc", "tdev", "tpgid")]
            _fields_ += [("nice", ctypes.c_int32), ("seconds", ctypes.c_uint64),
                        ("micros", ctypes.c_uint64)]
        info = BSDInfo()
        library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        library.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64,
                                         ctypes.c_void_p, ctypes.c_int]
        size = library.proc_pidinfo(pid, 3, 0, ctypes.byref(info), ctypes.sizeof(info))
        if size != ctypes.sizeof(info) or info.pid != pid or info.status == 5 or info.flags & 4:
            raise PermissionError("kernel process is absent or exiting")
        return ProcessIdentity(pid, info.ppid, (info.seconds, info.micros), info.uid)
    if sys.platform.startswith("linux"):
        path = Path("/proc") / str(pid)
        raw = (path / "stat").read_text()
        fields = raw[raw.rindex(")") + 2:].split()
        if fields[0] in {"Z", "X"}:
            raise PermissionError("kernel process is exiting")
        return ProcessIdentity(pid, int(fields[1]), (int(fields[19]),), path.stat().st_uid)
    raise PermissionError("kernel peer process authentication is unsupported on this host")
