"""Automatic Cloudflare Tunnel manager for LeadHunter AI.

Creates an instant, 100% free, secure public HTTPS tunnel for local demo previews:
- Automatically starts cloudflared in the background
- Parses and captures the live public HTTPS trycloudflare.com URL
- Automatically replaces localhost links with live public HTTPS links
  when generating outreach copy, demo URLs, cold emails, and WhatsApp messages.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from ..log import get_logger

log = get_logger("tunnel_manager")

_TUNNEL_PROC: Optional[subprocess.Popen] = None
_ACTIVE_PUBLIC_URL: Optional[str] = None
_LOCK = threading.Lock()


def find_cloudflared_binary() -> Optional[str]:
    """Locate the cloudflared executable on the system."""
    candidates = [
        "/opt/homebrew/bin/cloudflared",
        "/opt/homebrew/opt/cloudflared/bin/cloudflared",
        "/usr/local/bin/cloudflared",
        shutil.which("cloudflared"),
    ]
    for c in candidates:
        if c and Path(c).is_file() and os.access(c, os.X_OK):
            return str(c)
    return None


def get_active_public_url() -> Optional[str]:
    """Return current active public tunnel URL in memory."""
    global _ACTIVE_PUBLIC_URL
    return _ACTIVE_PUBLIC_URL


def start_auto_tunnel(local_port: int = 8500, timeout: int = 20) -> Optional[str]:
    """Start cloudflared tunnel in background and wait for the public trycloudflare URL."""
    global _TUNNEL_PROC, _ACTIVE_PUBLIC_URL

    with _LOCK:
        if _ACTIVE_PUBLIC_URL and _TUNNEL_PROC and _TUNNEL_PROC.poll() is None:
            return _ACTIVE_PUBLIC_URL

        binary = find_cloudflared_binary()
        if not binary:
            log.warning("cloudflared binary not found; falling back to local URL")
            return None

        cmd = [binary, "tunnel", "--url", f"http://127.0.0.1:{local_port}"]
        log.info("Launching automatic Cloudflare tunnel: %s", " ".join(cmd))

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            _TUNNEL_PROC = proc

            # Read stderr/stdout stream to find the trycloudflare.com URL
            pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")
            start_time = time.time()
            found_url = None

            while time.time() - start_time < timeout:
                if proc.poll() is not None:
                    log.error("Cloudflare tunnel process terminated unexpectedly with code %d", proc.returncode)
                    break

                line = proc.stdout.readline() if proc.stdout else ""
                if line:
                    match = pattern.search(line)
                    if match:
                        found_url = match.group(0).strip()
                        break
                time.sleep(0.1)

            if found_url:
                _ACTIVE_PUBLIC_URL = found_url
                log.info("🌐 Live Cloudflare Public Tunnel established: %s", _ACTIVE_PUBLIC_URL)
                return _ACTIVE_PUBLIC_URL
            else:
                log.warning("Could not obtain trycloudflare URL within %ds timeout", timeout)
                return None

        except Exception as exc:
            log.error("Failed to start cloudflared tunnel: %s", exc)
            return None


def stop_auto_tunnel() -> None:
    """Terminate the active cloudflared tunnel process."""
    global _TUNNEL_PROC, _ACTIVE_PUBLIC_URL
    with _LOCK:
        if _TUNNEL_PROC:
            try:
                _TUNNEL_PROC.terminate()
                _TUNNEL_PROC.wait(timeout=3)
            except Exception:
                try:
                    _TUNNEL_PROC.kill()
                except Exception:
                    pass
            _TUNNEL_PROC = None
        _ACTIVE_PUBLIC_URL = None


def resolve_public_demo_base_url(
    config_url: Optional[str] = None,
    local_port: int = 8500,
    force_tunnel: bool = True,
) -> str:
    """Resolve the definitive public demo base URL for outgoing outreach:
    1. If config/env specifies a custom external domain (not localhost), use that.
    2. Otherwise, automatically launch/use the Cloudflare public tunnel.
    3. Fallback to localhost if tunneling fails.
    """
    # 1. Custom explicit non-localhost domain
    if config_url and "localhost" not in config_url and "127.0.0.1" not in config_url:
        return config_url.rstrip("/")

    env_url = os.environ.get("DEMO_BASE_URL")
    if env_url and "localhost" not in env_url and "127.0.0.1" not in env_url:
        return env_url.rstrip("/")

    # 2. Automatic Cloudflare Tunnel
    if force_tunnel:
        public_tunnel = start_auto_tunnel(local_port=local_port)
        if public_tunnel:
            return f"{public_tunnel.rstrip('/')}/preview"

    # 3. Fallback
    return f"http://localhost:{local_port}/preview"
