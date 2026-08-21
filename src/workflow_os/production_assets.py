from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import PurePosixPath

_ALLOWED_MEDIA_TYPES = {"video/mp4", "video/webm", "image/png", "image/jpeg"}
_MAX_ASSET_BYTES = 2 * 1024 * 1024 * 1024
_MAX_TEXT = 5000


@dataclass(frozen=True)
class ProductionAssetManifest:
    opportunity_id: str
    campaign_id: str
    relative_path: str
    media_type: str
    size_bytes: int
    sha256: str
    producer: str
    source_material_rights_verified: bool
    campaign_requirements_verified: bool
    disclosure_satisfied: bool
    qc_passed: bool


@dataclass(frozen=True)
class ProductionAssetDecision:
    ready: bool
    reason: str
    asset_key: str | None


def _clean_text(value: str, field: str, *, maximum: int = _MAX_TEXT) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    cleaned = value.strip()
    if not cleaned or len(cleaned) > maximum:
        raise ValueError(f"{field} must be 1..{maximum} characters")
    return cleaned


def _validate_relative_path(value: str) -> str:
    path = _clean_text(value, "relative_path", maximum=500)
    pure = PurePosixPath(path.replace("\\", "/"))
    if pure.is_absolute() or ".." in pure.parts:
        raise ValueError("relative_path must be relative and traversal-free")
    return path


def _validate_digest(value: str) -> str:
    digest = _clean_text(value, "sha256", maximum=64).lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError("sha256 must be a SHA-256 hex digest")
    return digest


def evaluate_production_asset(manifest: ProductionAssetManifest) -> ProductionAssetDecision:
    """Fail-closed handoff gate from production to submission.

    This boundary does not render, upload, fetch remote media, or infer rights. It
    only accepts a deterministic asset manifest after production has completed and
    all evidence required for downstream publication is explicit.
    """

    if not isinstance(manifest, ProductionAssetManifest):
        return ProductionAssetDecision(False, "invalid manifest type", None)

    try:
        opportunity_id = _clean_text(manifest.opportunity_id, "opportunity_id", maximum=200)
        campaign_id = _clean_text(manifest.campaign_id, "campaign_id", maximum=200)
        relative_path = _validate_relative_path(manifest.relative_path)
        producer = _clean_text(manifest.producer, "producer", maximum=200)
        digest = _validate_digest(manifest.sha256)
        if manifest.media_type not in _ALLOWED_MEDIA_TYPES:
            raise ValueError("media_type is not allowed")
        if not isinstance(manifest.size_bytes, int) or isinstance(manifest.size_bytes, bool):
            raise ValueError("size_bytes must be an integer")
        if not 1 <= manifest.size_bytes <= _MAX_ASSET_BYTES:
            raise ValueError("size_bytes is outside allowed bounds")
    except ValueError as exc:
        return ProductionAssetDecision(False, str(exc), None)

    evidence = (
        (manifest.source_material_rights_verified, "source material rights are not verified"),
        (manifest.campaign_requirements_verified, "campaign requirements are not verified"),
        (manifest.disclosure_satisfied, "required disclosure is not satisfied"),
        (manifest.qc_passed, "production QC has not passed"),
    )
    for condition, reason in evidence:
        if condition is not True:
            return ProductionAssetDecision(False, reason, None)

    canonical = "\n".join(
        [
            opportunity_id,
            campaign_id,
            relative_path,
            manifest.media_type,
            str(manifest.size_bytes),
            digest,
            producer,
        ]
    ).encode("utf-8")
    asset_key = f"asset:{hashlib.sha256(canonical).hexdigest()}"
    return ProductionAssetDecision(True, "production asset evidence verified", asset_key)
