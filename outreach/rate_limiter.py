"""Rate limiter entrypoint shim for outreach.rate_limiter."""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from leadhunter.outreach.rate_limiter import *  # noqa: F401, F403
