"""Tunnel manager entrypoint shim for utils.tunnel_manager."""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from leadhunter.utils.tunnel_manager import *  # noqa: F401, F403
