"""Outreach rate limiting module for LeadHunter AI.

Enforces hourly throttling for outbound email and WhatsApp communication:
- Max 10 emails per hour (configurable)
- Max 20 WhatsApp messages per hour (configurable)
"""

from __future__ import annotations

import time
from collections import deque
from typing import Any, Dict, Optional, Tuple

from ..config import Config


class RateLimiter:
    """Sliding-window hourly rate limiter for email and WhatsApp sends."""

    def __init__(
        self,
        config: Optional[Config] = None,
        max_emails_per_hour: int = 10,
        max_whatsapp_per_hour: int = 20,
    ):
        self.config = config
        if config:
            self.max_emails_per_hour = int(config.get("outreach.max_emails_per_hour", max_emails_per_hour))
            self.max_whatsapp_per_hour = int(config.get("outreach.max_whatsapp_per_hour", max_whatsapp_per_hour))
        else:
            self.max_emails_per_hour = max_emails_per_hour
            self.max_whatsapp_per_hour = max_whatsapp_per_hour

        self._email_timestamps: deque[float] = deque()
        self._whatsapp_timestamps: deque[float] = deque()
        self._window_seconds: float = 3600.0  # 1 hour

    def _purge_expired(self, queue: deque[float], now: float) -> None:
        while queue and (now - queue[0]) > self._window_seconds:
            queue.popleft()

    def can_send_email(self) -> Tuple[bool, str]:
        now = time.time()
        self._purge_expired(self._email_timestamps, now)
        current_count = len(self._email_timestamps)
        if current_count >= self.max_emails_per_hour:
            return False, f"Email hourly limit reached ({current_count}/{self.max_emails_per_hour} sent in last hour)"
        return True, f"OK ({current_count}/{self.max_emails_per_hour} used)"

    def record_email(self) -> None:
        self._email_timestamps.append(time.time())

    def can_send_whatsapp(self) -> Tuple[bool, str]:
        now = time.time()
        self._purge_expired(self._whatsapp_timestamps, now)
        current_count = len(self._whatsapp_timestamps)
        if current_count >= self.max_whatsapp_per_hour:
            return False, f"WhatsApp hourly limit reached ({current_count}/{self.max_whatsapp_per_hour} sent in last hour)"
        return True, f"OK ({current_count}/{self.max_whatsapp_per_hour} used)"

    def record_whatsapp(self) -> None:
        self._whatsapp_timestamps.append(time.time())

    def get_stats(self) -> Dict[str, Any]:
        now = time.time()
        self._purge_expired(self._email_timestamps, now)
        self._purge_expired(self._whatsapp_timestamps, now)
        return {
            "emails_sent_last_hour": len(self._email_timestamps),
            "max_emails_per_hour": self.max_emails_per_hour,
            "whatsapp_sent_last_hour": len(self._whatsapp_timestamps),
            "max_whatsapp_per_hour": self.max_whatsapp_per_hour,
        }
