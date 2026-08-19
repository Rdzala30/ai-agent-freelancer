"""AI entrypoint shim for ai.personalizer."""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from leadhunter.ai.personalizer import *  # noqa: F401, F403
from leadhunter.ai.personalizer import main

if __name__ == "__main__":
    main()
