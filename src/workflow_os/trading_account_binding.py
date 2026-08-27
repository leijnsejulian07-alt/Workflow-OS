from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

ACCOUNT_BINDING_POLICY_VERSION = "trading-account-binding/1"


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _bounded_text(value: object, *, name: str, max_len: int = 160) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} is required")
    text = value.strip()
    if not text or len(text) > max_len:
        raise ValueError(f"{name} is required and bounded")
    return text


@dataclass(frozen=True)
class TradingAccountBindingEvidence:
    provider: str
    program: str
    account_id: str
    account_owned_by_owner: bool
    funded_activation_verified: bool
    kyc_aml_verified: bool
    payout_verification_complete: bool
    credential_binding_verified: bool
    credential_scope: str
    production_enable_approved: bool
    checked_at: str
    evidence_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TradingAccountBindingDecision:
    decision: str
    reasons: tuple[str, ...]
    may_prepare_live_execution: bool
    account_id: str
    policy_version: str = ACCOUNT_BINDING_POLICY_VERSION

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["reasons"] = list(self.reasons)
        return data


def normalize_account_binding_evidence(raw: dict[str, Any]) -> TradingAccountBindingEvidence:
    provider = _bounded_text(raw.get("provider"), name="provider")
    program = _bounded_text(raw.get("program"), name="program")
    account_id = _bounded_text(raw.get("account_id"), name="account_id")
    credential_scope = _bounded_text(raw.get("credential_scope"), name="credential_scope")

    checked = _timestamp(raw.get("checked_at"))
    if checked is None:
        raise ValueError("checked_at must be timezone-aware")

    digest = raw.get("evidence_sha256")
    if not isinstance(digest, str) or len(digest) != 64 or digest.lower() != digest:
        raise ValueError("evidence_sha256 is invalid")
    try:
        int(digest, 16)
    except ValueError as exc:
        raise ValueError("evidence_sha256 is invalid") from exc

    bool_fields = (
        "account_owned_by_owner",
        "funded_activation_verified",
        "kyc_aml_verified",
        "payout_verification_complete",
        "credential_binding_verified",
        "production_enable_approved",
    )
    for field in bool_fields:
        if not isinstance(raw.get(field), bool):
            raise ValueError(f"{field} must be boolean")

    return TradingAccountBindingEvidence(
        provider=provider,
        program=program,
        account_id=account_id,
        account_owned_by_owner=raw["account_owned_by_owner"],
        funded_activation_verified=raw["funded_activation_verified"],
        kyc_aml_verified=raw["kyc_aml_verified"],
        payout_verification_complete=raw["payout_verification_complete"],
        credential_binding_verified=raw["credential_binding_verified"],
        credential_scope=credential_scope,
        production_enable_approved=raw["production_enable_approved"],
        checked_at=checked.isoformat(),
        evidence_sha256=digest,
    )


def assess_account_binding(
    evidence: TradingAccountBindingEvidence,
    *,
    expected_provider: str,
    expected_program: str,
    now: datetime | None = None,
    max_evidence_age: timedelta = timedelta(days=1),
) -> TradingAccountBindingDecision:
    """Fail-closed binding gate. This never emits or dispatches an order."""
    if max_evidence_age <= timedelta(0) or max_evidence_age > timedelta(days=30):
        raise ValueError("max_evidence_age must be > 0 and <= 30 days")
    observed_now = now or datetime.now(timezone.utc)
    if observed_now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    observed_now = observed_now.astimezone(timezone.utc)
    checked = datetime.fromisoformat(evidence.checked_at).astimezone(timezone.utc)

    reasons: list[str] = []
    if evidence.provider != expected_provider or evidence.program != expected_program:
        reasons.append("PROVIDER_OR_PROGRAM_IDENTITY_MISMATCH")
    if checked > observed_now + timedelta(minutes=5):
        reasons.append("ACCOUNT_EVIDENCE_FROM_FUTURE")
    if observed_now - checked > max_evidence_age:
        reasons.append("ACCOUNT_EVIDENCE_STALE")
    if not evidence.account_owned_by_owner:
        reasons.append("ACCOUNT_OWNERSHIP_NOT_VERIFIED")
    if not evidence.funded_activation_verified:
        reasons.append("FUNDED_ACCOUNT_NOT_ACTIVATED")
    if not evidence.kyc_aml_verified:
        reasons.append("KYC_AML_NOT_VERIFIED")
    if not evidence.payout_verification_complete:
        reasons.append("PAYOUT_VERIFICATION_NOT_COMPLETE")
    if not evidence.credential_binding_verified:
        reasons.append("LEAST_PRIVILEGE_CREDENTIAL_BINDING_NOT_VERIFIED")
    if evidence.credential_scope.upper() not in {"TRADE_ONLY", "ORDER_EXECUTION_ONLY"}:
        reasons.append("CREDENTIAL_SCOPE_NOT_LEAST_PRIVILEGE")
    if not evidence.production_enable_approved:
        reasons.append("PRODUCTION_ENABLE_NOT_OWNER_APPROVED")

    if reasons:
        return TradingAccountBindingDecision(
            decision="HOLD",
            reasons=tuple(reasons),
            may_prepare_live_execution=False,
            account_id=evidence.account_id,
        )

    return TradingAccountBindingDecision(
        decision="PREPARE_ONLY",
        reasons=(),
        may_prepare_live_execution=True,
        account_id=evidence.account_id,
    )
