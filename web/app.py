"""Web Dashboard entrypoint shim for web.app."""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from leadhunter.web.app import app, run_server

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="LeadHunter AI Web Dashboard")
    parser.add_argument("--host", default="0.0.0.0", help="Host IP")
    parser.add_argument("--port", type=int, default=8000, help="Port")
    args = parser.parse_args()

    run_server(host=args.host, port=args.port)
