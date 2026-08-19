"""Demo URL generator entrypoint shim for demo.url_generator."""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from leadhunter.demo.url_generator import *  # noqa: F401, F403
from leadhunter.demo.url_generator import main

if __name__ == "__main__":
    main()
