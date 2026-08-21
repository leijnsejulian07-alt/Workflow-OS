from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from .production_assets import ProductionAssetManifest, evaluate_production_asset

_ALLOWED_MEDIA_TYPES = {"video/mp4", "video/webm", "image/png", "image/jpeg"}
_MAX_ASSET_BYTES = 2 * 1024 * 1024 * 1024
_MAX_TEXT = 5000


@dataclass(frozen=True)
class ProducerOutput:
    """Untrusted output emitted by an external/local media producer adapter."""

    relative_path: str
    media_type: str
    size_bytes: int
    sha256: str
    producer: str


@dataclass(frozen=True)
class TrustedProductionEvidence:
    """Evidence supplied by Workflow OS, never inferred from producer output."""

    opportunity_id: str
    campaign_id: str
    source_material_rights_verified: bool
    campaign_requirements_verified: bool
    disclosure_satisfied: bool
    qc_passed: bool


def _text(value: object, field: str, maximum: int = _MAX_TEXT) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    cleaned = value.strip()
    if not cleaned or len(cleaned) > maximum:
        raise ValueError(f"{field} must be 1..{maximum} characters")
    return cleaned


def _path(value: object) -> str:
    cleaned = _text(value, "relative_path", 500)
    pure = PurePosixPath(cleaned.replace("\\", "/"))
    if pure.is_absolute() or ".." in pure.parts:
        raise ValueError("relative_path must be relative and traversal-free")
    return cleaned


def _digest(value: object) -> str:
    cleaned = _text(value, "sha256", 64).lower()
    if len(cleaned) != 64 or any(ch not in "0123456789abcdef" for ch in cleaned):
        raise ValueError("sha256 must be a SHA-256 hex digest")
    return cleaned


def build_production_manifest(
    output: ProducerOutput,
    evidence: TrustedProductionEvidence,
) -> ProductionAssetManifest:
    """Join hostile producer metadata with independently trusted workflow evidence.

    Producer adapters are deliberately unable to self-assert rights, campaign
    compliance, disclosure, or QC. Those publication-critical facts must arrive
    through ``TrustedProductionEvidence`` owned by Workflow OS.
    """

    if not isinstance(output, ProducerOutput):
        raise ValueError("output must be ProducerOutput")
    if not isinstance(evidence, TrustedProductionEvidence):
        raise ValueError("evidence must be TrustedProductionEvidence")

    relative_path = _path(output.relative_path)
    producer = _text(output.producer, "producer", 200)
    digest = _digest(output.sha256)
    if output.media_type not in _ALLOWED_MEDIA_TYPES:
        raise ValueError("media_type is not allowed")
    if not isinstance(output.size_bytes, int) or isinstance(output.size_bytes, bool):
        raise ValueError("size_bytes must be an integer")
    if not 1 <= output.size_bytes <= _MAX_ASSET_BYTES:
        raise ValueError("size_bytes is outside allowed bounds")

    manifest = ProductionAssetManifest(
        opportunity_id=_text(evidence.opportunity_id, "opportunity_id", 200),
        campaign_id=_text(evidence.campaign_id, "campaign_id", 200),
        relative_path=relative_path,
        media_type=output.media_type,
        size_bytes=output.size_bytes,
        sha256=digest,
        producer=producer,
        source_material_rights_verified=evidence.source_material_rights_verified is True,
        campaign_requirements_verified=evidence.campaign_requirements_verified is True,
        disclosure_satisfied=evidence.disclosure_satisfied is True,
        qc_passed=evidence.qc_passed is True,
    )
    decision = evaluate_production_asset(manifest)
    if not decision.ready:
        raise ValueError(f"production manifest rejected: {decision.reason}")
    return manifest
