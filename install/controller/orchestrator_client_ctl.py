"""Installed first-use Otto orchestration client; never opens the Store."""
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
if HERE.name=='prepared':HERE=HERE.parent
sys.path.insert(0,str(HERE/'runtime-source'))
from otto.portfolio.orchestrator_client import main
if __name__=='__main__':raise SystemExit(main())
