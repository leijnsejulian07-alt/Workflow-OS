# Useful GitHub repositories and tutorials — reviewed shortlist

> **Language:** English · [Nederlands](BUILD_RESOURCES.nl.md)
>
> Updated 2026-10-12. **Reference and ADOPT/ADAPT/HOLD decisions only.** No third-party dependencies were imported, executed or installed by creating this page. Assess licenses, release pins, security, platform terms, Windows compatibility, memory and cost before any integration.

## Repositories and possible fit

| Repository | What it could improve | Decision | Boundary / next action |
| --- | --- | --- | --- |
| [GoogleChrome/lighthouse](https://github.com/GoogleChrome/lighthouse) | Deeper performance/SEO/best-practices reports for **Website Audit Factory** | **ADAPT (later)** | Node 22+ and Chrome/browser workload; benchmark separately, no automatic remote scanning |
| [dequelabs/axe-core](https://github.com/dequelabs/axe-core) | Accessibility checks in a rendered page rather than our limited HTML heuristics | **ADAPT (later)** | MPL-2.0; partial accessibility coverage is **not WCAG certification**, document limitations |
| [withastro/astro](https://github.com/withastro/astro) | Reusable static-first website templates and kits | **ADAPT** | MIT; compare with existing Python static builder; adopt only if actual product requirements need it |
| [FFmpeg/FFmpeg](https://github.com/FFmpeg/FFmpeg) | Existing clipping/transcoding media path | **ADAPT** | Keep bounded subprocesses and media input isolation; **LGPL/GPL depends on exact build** |
| [m-bain/whisperX](https://github.com/m-bain/whisperX) | Word-timing/diarization for creator repurposing | **HOLD** | BSD-2-Clause source, review model/transitive licenses; substantial CPU/RAM/model overhead |
| [n8n-io/n8n](https://github.com/n8n-io/n8n) | Customer-owned automation packs and reusable triggers | **HOLD for embedding/resale** | **Sustainable Use License, not OSI open source**; internal business use differs from embedding/hosting n8n for customers; separate agreement may be required |
| [alpacahq/alpaca-py](https://github.com/alpacahq/alpaca-py) | Maintained official Python SDK references for the distinct Alpaca paper route | **ADAPT research, PAPER ONLY** | Existing trading gates remain authoritative; avoid deprecated [archived old SDK](https://github.com/alpacahq/alpaca-trade-api-python); no live credentials or capital |
| [yt-dlp/yt-dlp](https://github.com/yt-dlp/yt-dlp) | Ingestion **only for customer-owned or authorized material** | **HOLD** | Platform terms/rights first; executable bundles have differing licenses, and YouTube support may require a JS runtime |
| [microsoft/playwright-python](https://github.com/microsoft/playwright-python) | Authorized product UI smoke tests and screenshot-based checks | **HOLD** | Apache-2.0; browser processes increase memory needs; no anti-bot bypass or unattended platform posting |
| [temporalio/sdk-python](https://github.com/temporalio/sdk-python) | Durable workflow patterns, recovery and versioning | **IDEA_ONLY / HOLD** | Adds a server/control plane; use existing SQLite durable worker until hard evidence justifies replacement |
| [PrefectHQ/prefect](https://github.com/PrefectHQ/prefect) | Workflow observability, retries and schedules | **IDEA_ONLY / HOLD** | Significant overlap with existing scheduler/HQ; no replacement without comparative proof |

**Decision rule:** ADAPT does **not** authorize immediate installation. For a weak local Windows runtime, a small, tested native Python function is often preferable to a full Node/browser/queue stack. The existing OSS registry remains the canonical integration-review record: [English](OSS_COMPONENT_REGISTRY.md) · [Nederlands](OSS_COMPONENT_REGISTRY.nl.md).

## YouTube: practical learning in recommended order

| Video | Creator / date | What to apply to Workflow OS |
| --- | --- | --- |
| [n8n Quick Start Tutorial: Build Your First Workflow](https://www.youtube.com/watch?v=4cQWJViybAQ) | **n8n**, 2025-06-20 | Understand triggers, items, conditions and how to trace executions; adapt only patterns, not more orchestration layers |
| [n8n Tutorial #5: Error Handling & Retry Logic](https://www.youtube.com/watch?v=PCs-i_JMCNM) | Kris Torrington, 2025-09-17 | Exception routes, retries and observability; **never retry uncertain external side effects blindly** |
| [Start Automating: Build Your First GitHub Action](https://www.youtube.com/watch?v=N7zd6tkqq04) | Real Python, 2025-07-06 | Maintain CI and local-first Python tests; do not enable unbudgeted paid GitHub Actions |
| [Make a Simple Trading Bot in MINUTES With Python & Alpaca](https://www.youtube.com/watch?v=b3VFMdjBfKA) | Nicholas Facciola, 2025-06-17 | Intro to **paper accounts only**; demo strategy is not proven profitable, and it needs walk-forward/holdout/ledger gates before even being evaluated |

Videos are **learning resources, not runnable code, verified profitability, or a grant of platform permissions**. Versions shown in videos may differ from current providers.

## Implementation order

1. Keep the existing OpenShorts→Whop **synthetic** worker proof, restart recovery, audit and payment reconciliation working; verify authorized Windows installation/scheduling when online.
2. Finish local Website Audit Factory accuracy/security validation using **no new dependency**. Assess Lighthouse/axe-core only if a measured capability gap remains.
3. Validate customer willingness to pay with clearly labeled opt-in sample reports; no unsolicited mass outreach, false compliance certificates or unauthorized website crawling.
4. Pilot one customer-hosted automation package or recurring monitoring product only after the current route is truly operational.
5. Keep trading research separate and paper-only.

Every future change in this document must update [the Dutch counterpart](BUILD_RESOURCES.nl.md) in the same PR.
