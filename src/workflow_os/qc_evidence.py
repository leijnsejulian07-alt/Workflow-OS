from __future__ import annotations

from dataclasses import dataclass

from .adapters.ffprobe_media_qc import MediaQCResult, probe_media_qc
from .production_handoff import ProducerOutput, TrustedProductionEvidence


@dataclass(frozen=True)
class BoundMediaQC:
    """Technical QC result cryptographically bound to one producer output."""

    source_sha256: str
    source_size_bytes: int
    result: MediaQCResult


def run_bound_media_qc(
    workspace_root: str,
    source: ProducerOutput,
    **probe_kwargs: object,
) -> BoundMediaQC:
    """Run technical QC and bind the result to the exact producer evidence."""

    if not isinstance(source, ProducerOutput):
        raise ValueError("source must be ProducerOutput")
    result = probe_media_qc(workspace_root, source, **probe_kwargs)
    return BoundMediaQC(
        source_sha256=source.sha256,
        source_size_bytes=source.size_bytes,
        result=result,
    )


def build_trusted_production_evidence(
    source: ProducerOutput,
    qc: BoundMediaQC,
    *,
    opportunity_id: str,
    campaign_id: str,
    source_material_rights_verified: bool,
    campaign_requirements_verified: bool,
    disclosure_satisfied: bool,
) -> TrustedProductionEvidence:
    """Create Workflow OS-owned evidence only when QC matches the exact asset.

    Technical QC never grants rights, campaign compliance, disclosure, or
    publication authority. Those inputs remain independent and must be explicit.
    """

    if not isinstance(source, ProducerOutput):
        raise ValueError("source must be ProducerOutput")
    if not isinstance(qc, BoundMediaQC):
        raise ValueError("qc must be BoundMediaQC")
    if qc.source_sha256 != source.sha256 or qc.source_size_bytes != source.size_bytes:
        raise ValueError("QC evidence does not match producer output")
    if qc.result.passed is not True:
        raise ValueError(f"technical QC did not pass: {qc.result.reason}")
    if source_material_rights_verified is not True:
        raise ValueError("source material rights are not verified")
    if campaign_requirements_verified is not True:
        raise ValueError("campaign requirements are not verified")
    if disclosure_satisfied is not True:
        raise ValueError("disclosure requirements are not satisfied")

    return TrustedProductionEvidence(
        opportunity_id=opportunity_id,
        campaign_id=campaign_id,
        source_material_rights_verified=True,
        campaign_requirements_verified=True,
        disclosure_satisfied=True,
        qc_passed=True,
    )
