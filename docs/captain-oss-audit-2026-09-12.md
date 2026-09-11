# Captain OSS capability audit — 2026-09-12

Purpose: identify bounded capabilities Captain can adapt without introducing a second router/control-plane or weakening project/chat/repo/epoch isolation. No third-party code was installed or executed during this audit.

## LLMFlow-Search — ADAPT candidate

Source: `KazKozDev/llmflow-search`.

Useful capability: local/Ollama-oriented multi-step research with source admission, evidence challenge, citation verification, and PDF/report output. The valuable part for Captain is the evidence-verification workflow and provenance contract, not its LangGraph control loop.

Fit: medium-high for Captain research quality. Adapt the evidence ledger, claim-to-source verification and completeness checks behind Captain's existing research path. Do not add a second planning/router daemon.

Risks/cost: young project; MCP/web-search dependencies and remote content remain hostile input. Exact license, dependency tree, release activity and PDF pipeline must be re-checked before any code reuse. Laptop cost appears modest if Captain reuses its existing local model/router instead of duplicating model services.

Decision: ADAPT patterns first; no install.

## SandBase Harness — IDEA_ONLY / HOLD

Source: `sandbaseai/sandbase-harness`.

Useful capability: resumable sessions, sandboxed tools, credential policy, approvals, audit/replay and local console.

Fit: individual audit/replay and permission-policy patterns are relevant, but the runtime itself overlaps Captain's router, session, memory, credentials and control-plane responsibilities.

Risks/cost: Docker/Kubernetes/self-hosted worker surface is heavier than Captain's current laptop-first architecture; adopting wholesale would create duplicate authority and background infrastructure.

Decision: IDEA_ONLY. Borrow bounded audit/replay and approval UX patterns only.

## Tiz — IDEA_ONLY

Source: `smeso/tiz`.

Useful capability: per-tool sandbox access modes, project copies inside containers, internet isolation, package-management separation and confirmation gates for external side effects.

Fit: strong design reference for OpenBuilder's future execution sandbox. Particularly useful is splitting read/write/read-only/no-project-access and network permissions per tool.

Risks/cost: container runtime overhead and another agent loop. Must not replace Captain routing, Project State or task ownership.

Decision: IDEA_ONLY. Translate permission/sandbox patterns into Captain's own execution gate.

## Dome — HOLD

Source: `mhjmaas/dome`.

Useful capability: local-first microVM sandbox with checkpoints and TypeScript SDK.

Fit: conceptually excellent for safe code execution and rollback, but current positioning is macOS/Linux-first; direct use on the Windows laptop would imply WSL/VM complexity.

Risks/cost: very young/small project at review time; requires substantially more maturity/security evidence before trusted execution use.

Decision: HOLD; monitor, do not install.

## Daily conclusion

Highest-value near-term work remains inside Captain itself: enforce exact scope+epoch at every external context boundary, then add a provenance/evidence ledger to Captain research. For sandboxing, adapt Tiz-style least-privilege tool/network modes before considering a heavyweight external runtime. OpenViking remains a context-provider candidate only behind the new scoped external-context adapter and only if its backend can honor an exact Captain-supplied namespace.
