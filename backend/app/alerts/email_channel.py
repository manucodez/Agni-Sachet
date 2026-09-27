"""
SMTP email channel for tiered incident escalation.

Ported from the working escalation email in the SIH26162 reference
implementation (see docs/MERGE_NOTES.md), generalized from a
Gmail-app-password-only integration to any SMTP provider (settings.smtp_host
defaults to Gmail's since that's the easiest thing to set up with a free
account and an app password during a hackathon, but any SMTP relay works).

THREE PROPERTIES THIS MODULE GUARANTEES
------------------------------------------
These three properties are deliberately the same ones the alert dispatcher
in the SIH26162 "fully validated" reference implementation calls out
explicitly, because they're the actual failure modes that matter for an
alerting system, not abstract nice-to-haves:

1. Dispatch never happens by accident. `send_tier_email` is a no-op unless
   BOTH `settings.alert_dispatch_enabled` is True AND SMTP credentials are
   configured. A demo, a replay of historical data, or a CI test run can
   never page anyone, even if a .env file has stale-but-real SMTP creds
   left in it from a previous session.
2. A channel never silently succeeds. The return value is always one of
   the DispatchStatus values below — DISABLED and NOT_CONFIGURED are
   distinct from SENT, and both are distinct from FAILED (an exception
   during the actual SMTP conversation). Calling code logs and persists
   whichever one actually happened; nothing gets to assume "no exception
   raised" means "the email arrived."
3. Recipients are validated before anything is sent — an empty tier
   (no emails configured) is NOT_CONFIGURED, not a silently-empty send.
"""
from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass
from email.mime.text import MIMEText
from enum import Enum

from app.core.config import settings

logger = logging.getLogger(__name__)


class DispatchStatus(str, Enum):
    SENT = "sent"
    DISABLED = "disabled"  # alert_dispatch_enabled is False
    NOT_CONFIGURED = "not_configured"  # no recipients or no SMTP creds for this tier
    FAILED = "failed"  # attempted and the SMTP call raised


@dataclass(frozen=True)
class DispatchResult:
    status: DispatchStatus
    recipients: list[str]
    detail: str = ""


def build_incident_email_body(
    *, tier_label: str, predicted_class: str, risk_score: float, risk_tier: str,
    lat: float, lon: float, ack_url: str,
    nearest_responder_name: str | None, nearest_responder_distance_m: float | None,
) -> str:
    responder_line = (
        f"Nearest responder: {nearest_responder_name} (~{nearest_responder_distance_m / 1000:.1f} km)"
        if nearest_responder_distance_m is not None
        else "Nearest responder: none found within the search radius"
    )
    return (
        f"AGNI-SACHET INCIDENT ALERT — {tier_label}\n"
        f"{'-' * 50}\n"
        f"Classification: {predicted_class}\n"
        f"Risk tier: {risk_tier}  (score: {risk_score:.0f}/100)\n"
        f"Location: {lat:.5f}, {lon:.5f}  "
        f"(https://www.google.com/maps?q={lat:.5f},{lon:.5f})\n"
        f"{responder_line}\n\n"
        f"Acknowledge this incident: {ack_url}\n\n"
        "This is an automated alert from an academic hackathon prototype "
        "(Smart India Hackathon, Problem Statement 26162). Verify independently "
        "before acting — see docs/ARCHITECTURE.md for known model limitations."
    )


def send_tier_email(*, tier: int, subject: str, body: str) -> DispatchResult:
    recipients = settings.incident_tier_emails(tier)
    if not recipients:
        return DispatchResult(DispatchStatus.NOT_CONFIGURED, [], detail=f"no recipients configured for tier {tier}")

    if not settings.alert_dispatch_enabled:
        logger.info(
            "[DRY RUN] Would email tier %d (%s): %s — set ALERT_DISPATCH_ENABLED=true to actually send",
            tier, recipients, subject,
        )
        return DispatchResult(DispatchStatus.DISABLED, recipients)

    if not (settings.smtp_username and settings.smtp_password and settings.smtp_from_address):
        return DispatchResult(DispatchStatus.NOT_CONFIGURED, recipients, detail="SMTP credentials not set")

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from_address
    msg["To"] = ", ".join(recipients)

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
            server.starttls()
            server.login(settings.smtp_username, settings.smtp_password)
            server.sendmail(settings.smtp_from_address, recipients, msg.as_string())
        return DispatchResult(DispatchStatus.SENT, recipients)
    except Exception as exc:
        logger.exception("Tier %d email dispatch failed", tier)
        return DispatchResult(DispatchStatus.FAILED, recipients, detail=str(exc))
