# OSS Component Registry

This registry is the evidence gate for third-party components considered by Workflow OS. A registry entry is not permission to install or deploy a component. Versions/commits must be pinned and reviewed before integration.

## Decision labels

- **ADOPT** — preferred component after evidence-based comparison.
- **ADAPT** — reuse a bounded part or integrate behind a replaceable adapter.
- **IDEA_ONLY** — patterns may inform our design; do not import code.
- **HOLD** — potentially useful later; current cost/risk/overlap is too high.
- **REJECT** — unsuitable for the current architecture or constraints.

## Current registry

| Component | Source | Decision | License / obligations | Intended purpose | Security / operational notes | Update and replacement boundary |
| --- | --- | --- | --- | --- | --- | --- |
| LiteLLM | BerriAI/litellm | ADAPT | Core MIT; enterprise features are separate. Preserve notices for redistributed code. | Provider-gateway benchmark baseline. | High-trust path for prompts/credentials; enable only approved providers, redact logs, least-privilege keys. | Pin reviewed release/container digest. All calls remain behind our provider-router interface so it can be replaced. |
| OmniRoute | diegosouzapw/OmniRoute | ADAPT | MIT at current review; re-check at pin time. | Challenger for quota-aware multi-provider routing/fallback. | Do not enable cookie/proxy/bypass-style provider paths. Treat gateway and credentials as a security boundary. | Benchmark against LiteLLM before production; pin exact reviewed commit/release; same provider-router boundary. |
| AutoClip | artbyjazi/autoclip | ADAPT | Re-check LICENSE at exact pin before importing. | Shared clipping-production engine candidate. | Media and campaign assets are hostile input; isolate FFmpeg/media processing and enforce rights ledger before render/publish. | Adapter around clip jobs; no campaign/business logic inside engine. |
| WhisperX | m-bain/whisperX | HOLD | Re-check transitive model/dependency licenses before use. | Word alignment/diarization. | Resource-heavy; model downloads and media are untrusted inputs. | Prefer AutoClip's optional integration; integrate separately only if benchmark proves a gap. |
| MoneyPrinterTurbo | harry0703/MoneyPrinterTurbo | IDEA_ONLY | Re-check repository and dependency licenses before any reuse. | Media-controller/design patterns for generated short video. | Large media/model/provider surface; avoid duplicating clipping stack. | No production dependency; copy no code unless separately reviewed and registered. |
| ffmpeg-python | kkroening/ffmpeg-python | REJECT | Apache-2.0 at historical review; verify if reconsidered. | Legacy FFmpeg wrapper. | Adds abstraction without solving hostile-input or process isolation. | Prefer direct FFmpeg argument arrays with shell disabled behind our media-runner boundary. |
| PocketBase | pocketbase/pocketbase | HOLD | MIT; pre-1.0 compatibility/migration risk remains relevant. | Lightweight backend/admin/storage candidate. | Would introduce a second backend/control plane if adopted now. | Keep current lightweight storage/HQ until PocketBase clearly removes more code than it adds. |
| Windmill | windmill-labs/windmill | HOLD | Mixed licensing/use terms; legal review required for intended deployment. | Heavy-job/workflow platform. | Significant infra/control-plane overlap with n8n and Workflow HQ. | Revisit only if n8n cannot meet a proven durable/heavy-job requirement. |
| Inngest | inngest/inngest | HOLD | Current licensing requires legal review; do not assume permissive terms. | Durable event orchestration. | Adds another orchestration plane and operational surface. | Revisit only on demonstrated durability gap. |
| browser-use | browser-use/browser-use | HOLD | Re-check exact release/license before integration. | Browser automation last-resort adapter. | Highest hostile-input exposure; sandbox, no secrets, network allowlist, download blocking and hard resource limits required. | Browser adapter is optional and replaceable; official API/plain HTTP remains preferred. |
| Crawl4AI | unclecode/crawl4ai | ADAPT | Re-check exact release/license before integration. | Controlled discovery/crawling where permitted. | Remote HTML is data, never instructions; SSRF, size, redirect, MIME and rights/ToS gates mandatory. | Keep behind discovery-source interface; disable per source without affecting Opportunity Manager. |
| Astro | withastro/astro | ADAPT | MIT; preserve required notices for redistributed code. | Static Website-in-a-Box generation. | Static output reduces runtime/support burden; generated content still needs rights/privacy/brand QA. | Template/build adapter; deployment provider and customer domain remain independent. |
| shadcn/ui | shadcn-ui/ui | ADAPT | MIT for project code; individual bundled assets/components must retain applicable notices. | Website-in-a-Box component/template primitives. | Avoid importing unnecessary dependency surface. | Copy/adapt only reviewed components into template layer; replaceable per template. |
| Infisical | Infisical/infisical | HOLD | Core/enterprise boundaries must be checked at exact version. | Central secrets management candidate. | A secrets platform is itself high-trust infrastructure and may be excessive on one weak laptop. | Prefer OS/native isolated secret storage until central secret lifecycle needs justify it. |
| Payload | payloadcms/payload | HOLD | MIT core at current review; verify exact version. | Admin/backend candidate. | Duplicates Workflow HQ if adopted prematurely. | Revisit only if HQ CRUD/admin burden becomes material. |
| Trivy | aquasecurity/trivy | ADOPT | Apache-2.0; preserve notices where applicable. | Repository/dependency/container/IaC security scanning. | Scanner supply chain is a boundary; pin trusted action SHA/version and keep findings fail-safe rather than auto-fixing blindly. | CI security adapter; can be replaced without application changes. |
| OpenHands | All-Hands-AI/OpenHands | HOLD | Re-check exact release/license and hosted-service terms. | Exception/on-demand code maintenance. | Never continuous production operator; no unrestricted production secrets/write access. | Development-only adapter and human/owner-triggered exceptions. |
| ECC | affaan-m/ECC | ADAPT | MIT at current review; verify exact commit. | Controlled development engineering harness. | Hooks/MCP/scripts are high privilege; review and pin before pilot; no production secrets or unrestricted push. | Development-only; removable without runtime dependency. |
| AgentShield | affaan-m/agentshield | ADAPT | MIT at current review; verify exact commit. | Agent/MCP/hooks/secrets/permissions security scanning. | Validate false positives; prefer CLI/SARIF boundary over internal APIs; pin reviewed version. | Development/CI scanner adapter; complementary to Trivy, not runtime authorization. |
| Cockatiel | connor4312/cockatiel | ADAPT | MIT at current review; verify exact release. | Lightweight retry/timeout/circuit-breaker/bulkhead primitives for shared adapters. | Do not double-stack retries with n8n/provider SDKs; bounded policies only. | Resilience wrapper around shared HTTP/provider adapters; replaceable library. |
| OpenTelemetry JS | open-telemetry/opentelemetry-js | ADAPT | Apache-2.0; preserve notices. | Vendor-neutral traces/metrics feeding Workflow HQ. | Instrument selectively; redact PII/secrets; avoid a heavyweight second observability control plane. | Telemetry API boundary; exporters remain modular and optional. |

## Integration gate

Before changing any entry to production **ADOPT** or installing an **ADAPT** candidate, record: exact pinned version/commit/digest; current license and attribution requirements; maintenance/release evidence; tests/security advisories; transitive dependency and supply-chain review; Windows/Node/Python compatibility; measured CPU/RAM/storage impact; privacy and provider/platform ToS impact; integration effort versus current implementation; rollback procedure; and the interface that permits replacement.

No component may weaken hostile-input isolation, rights/compliance gates, idempotency, secrets isolation, owner-attention limits, or fail-closed behavior.