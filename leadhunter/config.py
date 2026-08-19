"""Configuration loading.

Rules:
- Settings (timeouts, thresholds, flags) live in config.yaml — never in .env.
- Secrets (API keys, tokens, credentials) live in .env — never in config.yaml.
- Any config.yaml leaf can be overridden at runtime via LEADHUNTER_<PATH>
  env var (e.g. LEADHUNTER_LIMITS_MAX_LEADS_PER_RUN=5). Type is coerced
  from the YAML leaf type.
- Secrets are never required at import time. A module calls
  config.require_secret("GOOGLE_PLACES_API_KEY") only when it actually needs
  the key, so the pipeline runs fully in dry-run/template mode with no keys
  at all, and fails honestly (ConfigError) the moment a keyed integration is
  selected without its key.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from .errors import ConfigError

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.yaml"
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"

# Well-known secret names (values come ONLY from the environment / .env).
SECRET_NAMES: List[str] = [
    "ANTHROPIC_API_KEY",
    "OPENROUTER_API_KEY",
    "LLM_MODEL",
    "GOOGLE_PLACES_API_KEY",
    "SERPAPI_KEY",
    "SERPAPI_API_KEY",
    "APOLLO_API_KEY",
    "HUNTER_API_KEY",
    "WHATSAPP_BRIDGE_URL",
    "WHATSAPP_OWNER_CHAT_ID",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USER",
    "SMTP_PASS",
    "SMTP_TLS",
    "SMTP_FROM",
    "SMTP_FROM_NAME",
    "SENDER_NAME",
    "SENDER_EMAIL",
    "GMAIL_APP_PASSWORD",
    "WHATSAPP_TOKEN",
    "WHATSAPP_PHONE_NUMBER_ID",
    "DRY_RUN",
    "GOOGLE_CREDS_PATH",
    "GOOGLE_SHEET_ID",
    "GOOGLE_SHEETS_CREDS_FILE",
    "GOOGLE_SHEETS_SPREADSHEET_ID",
    "GOOGLE_SHEETS_RANGE",
    "DEMO_GH_REPO",
    "GITHUB_TOKEN",
]

ENV_OVERRIDE_PREFIX = "LEADHUNTER_"


def load_env_file(path: Path) -> None:
    """Load KEY=VALUE lines from a dotenv file into os.environ.

    Never overwrites an already-set environment variable. Real secrets come
    from the shell environment; .env is a convenience for local runs.
    """
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _coerce(value: Any, existing: Any) -> Any:
    """Coerce an env-var string to the type of the existing config leaf."""
    if isinstance(existing, bool):
        return str(value).strip().lower() in ("1", "true", "yes", "on")
    if isinstance(existing, int):
        try:
            return int(value)
        except ValueError:
            return existing
    if isinstance(existing, float):
        try:
            return float(value)
        except ValueError:
            return existing
    return value


class Config:
    """Typed-ish wrapper over the config.yaml tree with env overlays."""

    def __init__(self, raw: Dict[str, Any], config_path: Path):
        self.raw = raw
        self.config_path = config_path
        self._apply_env_overlay(raw)

    # ---- loading ---------------------------------------------------------

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> "Config":
        path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        if not path.exists():
            raise ConfigError(f"config file not found: {path}")
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls(raw, path)

    def _apply_env_overlay(self, node: Dict[str, Any], prefix: str = "") -> None:
        """Map LEADHUNTER_A_B_C onto the nested path a.b.c."""
        for key, value in list(node.items()):
            path = f"{prefix}.{key}" if prefix else key
            env_name = ENV_OVERRIDE_PREFIX + path.replace(".", "_").upper()
            if isinstance(value, dict):
                self._apply_env_overlay(value, path)
                continue
            if env_name in os.environ:
                node[key] = _coerce(os.environ[env_name], value)

    # ---- accessors -------------------------------------------------------

    def get(self, dotted_path: str, default: Any = None) -> Any:
        node: Any = self.raw
        for part in dotted_path.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    # ---- paths -----------------------------------------------------------

    @property
    def data_dir(self) -> Path:
        override = os.environ.get("LEADHUNTER_DATA_DIR")
        base = Path(override) if override else Path(self.get("app.data_dir", "./data"))
        if not base.is_absolute():
            base = self.config_path.parent / base
        return base.resolve()

    def ensure_dirs(self) -> None:
        for sub in ("", "logs", "reports", "demos", "outbox", "export", "demos"):
            (self.data_dir / sub).mkdir(parents=True, exist_ok=True)

    # ---- secrets ---------------------------------------------------------

    def get_secret(self, name: str) -> Optional[str]:
        if name not in SECRET_NAMES:
            raise ConfigError(f"unknown secret name: {name} (add it to SECRET_NAMES)")
        value = os.environ.get(name)
        return value.strip() if value and value.strip() else None

    def require_secret(self, name: str) -> str:
        value = self.get_secret(name)
        if not value:
            raise ConfigError(
                f"secret '{name}' is required for this operation but is not set. "
                f"Add it to {DEFAULT_ENV_PATH.name} or the shell environment."
            )
        return value

    def missing_secrets(self) -> List[str]:
        return [name for name in SECRET_NAMES if not self.get_secret(name)]

    def secrets_present(self) -> Dict[str, bool]:
        return {name: self.get_secret(name) is not None for name in SECRET_NAMES}
