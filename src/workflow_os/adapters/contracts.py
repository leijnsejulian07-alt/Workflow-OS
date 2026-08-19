"""Fail-closed contracts shared by revenue opportunity source adapters.

Adapters discover and normalize evidence only. They do not publish, submit,
pay, message, deploy, or bypass access controls. External side effects belong
behind the SideEffectLedger/reconciliation boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Protocol, Sequence
from urllib.parse import urlparse


class AccessMode(str, Enum):
    OFFICIAL_API = "official_api"
    PUBLIC_HTTP = "public_http"
    AUTHORIZED_ACCOUNT = "authorized_account"


@dataclass(frozen=True)
class SourcePolicy:
    source_platform: str
    allowed_hosts: frozenset[str]
    access_mode: AccessMode
    max_response_bytes: int = 1_048_576
    max_redirects: int = 3
    requires_rights_evidence: bool = True

    def __post_init__(self) -> None:
        if not self.source_platform.strip():
            raise ValueError("source_platform is required")
        if not self.allowed_hosts:
            raise ValueError("at least one allowed host is required")
        if self.max_response_bytes <= 0 or self.max_response_bytes > 10_485_760:
            raise ValueError("response bound must be within 1 byte and 10 MiB")
        if self.max_redirects < 0 or self.max_redirects > 5:
            raise ValueError("redirect bound must be between 0 and 5")

    def allows_url(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            return False
        host = parsed.hostname.lower().rstrip(".")
        return host in {item.lower().rstrip(".") for item in self.allowed_hosts}


@dataclass(frozen=True)
class DiscoveryRecord:
    source_platform: str
    campaign_id: str
    title: str
    canonical_url: str
    observed_at: str
    raw_evidence_sha256: str
    fields: Mapping[str, object]


class OpportunitySourceAdapter(Protocol):
    """Read-only discovery boundary.

    Implementations must use a reviewed transport that enforces HTTPS host
    allowlists, SSRF/private-address blocking, redirect/size/MIME/time limits,
    bounded retries, and no execution of remote code. Returned records are
    still untrusted until Opportunity Manager validation succeeds.
    """

    policy: SourcePolicy

    def discover(self) -> Sequence[DiscoveryRecord]:
        ...


# Capabilities that a discovery adapter is never allowed to perform directly.
FORBIDDEN_DISCOVERY_SIDE_EFFECTS = frozenset(
    {
        "publish",
        "submit",
        "send_message",
        "send_email",
        "send_sms",
        "place_call",
        "pay",
        "purchase",
        "deploy",
        "create_account",
        "solve_captcha",
        "bypass_access_control",
    }
)
