"""Run-local shared address; address grants no caller authority.
Kernel process-version/canonical admission authentication stays in the host.
"""
from pathlib import Path
import os,stat
ROOT=Path('/Users/hannahomalley/.codex/owner-services/otto-onboarding-20261010')
def native_caller_socket_path():
 for parent in (Path('/Users/hannahomalley'),Path('/Users/hannahomalley/.codex'),ROOT.parent,ROOT):
  current=parent.lstat()
  if not stat.S_ISDIR(current.st_mode) or stat.S_ISLNK(current.st_mode) or current.st_uid!=os.getuid():
   raise PermissionError('trusted owner socket parent differs: '+str(parent))
  if parent in (ROOT.parent,ROOT) and stat.S_IMODE(current.st_mode)!=0o700:
   raise PermissionError('private owner socket directory mode differs: '+str(parent))
 path=ROOT/'caller.sock'
 if len(os.fsencode(path))>103:raise ValueError('macOS Unix socket address exceeds103bytes')
 return path
