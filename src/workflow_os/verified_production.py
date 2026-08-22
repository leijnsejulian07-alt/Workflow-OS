from __future__ import annotations

from dataclasses import dataclass

from .production_assets import ProductionAssetManifest
from .production_handoff import ProducerOutput, build_production_manifest
from .qc_evidence import BoundMediaQC, build_trusted_production_evidence, run_bound_media_qc


@dataclass(frozen=True)
class VerifiedProductionResult:
    """One producer output promoted through technical QC and trusted evidence."""

    source: ProducerOutput
    qc: BoundMediaQC
    manifest: ProductionAssetManifest


def verify_production_output(
    workspace_root: str,
    source: ProducerOutput,
    *,
    opportunity_id: str,
    campaign_id: str,
    source_material_rights_verified: bool,
    campaign_requirements_verified: bool,
    disclosure_satisfied: bool,
    **probe_kwargs: object,
) -> VerifiedProductionResult:
    """Promote one exact producer output into a trusted production manifest.

    This is a bounded Workflow OS-owned handoff. Technical QC is run against
    the exact ProducerOutput, then bound to its SHA-256 and size. Nontechnical
    evidence remains independent and must be explicitly supplied as true.
    Producer adapters cannot grant rights, campaign compliance, disclosure,
    publication authority, or account authorization through this function.
    """

    if not isinstance(source, ProducerOutput):
        raise ValueError("source must be ProducerOutput")

    qc = run_bound_media_qc(workspace_root, source, **probe_kwargs)
    trusted = build_trusted_production_evidence(
        source,
        qc,
        opportunity_id=opportunity_id,
        campaign_id=campaign_id,
        source_material_rights_verified=source_material_rights_verified,
        campaign_requirements_verified=campaign_requirements_verified,
        disclosure_satisfied=disclosure_satisfied,
    )
    manifest = build_production_manifest(source, trusted)
    return VerifiedProductionResult(source=source, qc=qc, manifest=manifest)
