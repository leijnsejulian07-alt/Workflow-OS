from __future__ import annotations

from dataclasses import dataclass

from .production_assets import ProductionAssetManifest, evaluate_production_asset
from .submissions import SubmissionAsset, SubmissionRequest


@dataclass(frozen=True)
class ProductionSubmissionContext:
    source_platform: str
    campaign_url: str
    destination_url: str
    caption: str
    account_authorized: bool
    machine_submission_verified: bool = False
    zero_touch_execution_enabled: bool = False


def build_submission_request(
    manifest: ProductionAssetManifest,
    context: ProductionSubmissionContext,
) -> SubmissionRequest:
    """Build a submission request only from a production asset that already passed QC.

    This is a pure handoff boundary: it performs no rendering, network access,
    credential resolution, upload, or rights inference. Rejected production assets
    never become submission requests. Execution authority is enforced by the
    reservation/execution control plane rather than inferred here.
    """

    decision = evaluate_production_asset(manifest)
    if not decision.ready:
        raise ValueError(f"production asset is not submission-ready: {decision.reason}")
    if not isinstance(context, ProductionSubmissionContext):
        raise ValueError("context must be ProductionSubmissionContext")

    return SubmissionRequest(
        opportunity_id=manifest.opportunity_id.strip(),
        source_platform=context.source_platform,
        campaign_url=context.campaign_url,
        destination_url=context.destination_url,
        caption=context.caption,
        asset=SubmissionAsset(
            path=manifest.relative_path,
            media_type=manifest.media_type,
            size_bytes=manifest.size_bytes,
            sha256=manifest.sha256.lower(),
        ),
        rights_verified=True,
        account_authorized=context.account_authorized is True,
        disclosure_satisfied=True,
        campaign_requirements_verified=True,
    )
