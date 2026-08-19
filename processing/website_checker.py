"""Processing entrypoint shim for processing.website_checker."""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from leadhunter.processing.website_checker import *  # noqa: F401, F403
from leadhunter.processing.website_checker import main

if __name__ == "__main__":
    main()
