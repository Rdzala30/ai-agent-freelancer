"""Discovery entrypoint shim for discovery.serpapi_search."""

import os
import sys
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from leadhunter.discovery.serpapi_search import *  # noqa: F401, F403
from leadhunter.discovery.serpapi_search import main

if __name__ == "__main__":
    main()
