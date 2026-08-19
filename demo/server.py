"""Demo server entrypoint shim for demo.server."""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from leadhunter.demo.server import *  # noqa: F401, F403
from leadhunter.demo.server import run_server

if __name__ == "__main__":
    run_server()
