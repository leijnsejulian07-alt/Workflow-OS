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

## Ruflo — IDEA_ONLY / selective ADAPT

Source: `ruvnet/ruflo`.

Useful capability: mature multi-agent orchestration patterns, specialized agents, memory, MCP tooling, routing, benchmarks and security-oriented coordination. Upstream remains active and published updated architecture material in September 2026.

Fit: selected swarm/coordination, evaluation and security patterns may help Captain, but Ruflo is itself a broad orchestration/control plane with routing and memory. Adopting it wholesale would violate Captain's single-control-plane requirement.

Risks/cost: large dependency/tool surface and substantial overlap with Captain router, memory and orchestration. Treat MCP/tool execution as high privilege. Do not run `init` or start its daemon on the production laptop without a separate bounded review.

Decision: IDEA_ONLY by default; selectively ADAPT isolated patterns or libraries only after exact-version review.

## Freebuff / Codebuff SDK — ADAPT candidate

Source: `CodebuffAI/freebuff` and the underlying Codebuff SDK.

Useful capability: repo-aware coding agents, parallel isolated workspaces, browser-backed application testing, code finding/maps, review agents, hosted sandboxes/previews, and an embeddable SDK/runtime.

Fit: high for Captain's builder subsystem if the narrow SDK/code-map/review pieces can sit behind Captain Project State and router. The hosted Freebuff products are not required for this value.

Risks/cost: current upstream documentation says prompts, messages, traces, code/files and repository data are processed to provide the service, with model-specific data-use notices; hosted/free access also has limits and advertising. Local development uses Bun plus Docker. Never silently send Captain repositories to Freebuff Cloud or opt into a model/provider with training/data-use terms.

Decision: ADAPT the local SDK/code-map/review patterns only; hosted/cloud path remains disabled unless the user explicitly connects/enables it in Captain Settings.

## OpenViking — HOLD for scoped adapter benchmark

Source: `volcengine/OpenViking`.

Useful capability: unified filesystem-like organization of memories, resources and skills with tiered context retrieval, plus integrations with agent frameworks and MCP-style consumers.

Fit: potentially high for Captain context/memory discovery, but Captain memory remains the persistent source of truth. OpenViking may only act as a replaceable external context/index adapter.

Risks/cost: Captain must prove exact `chat_id + project_id + repo_scope + state_epoch` namespace isolation, revocation after epoch changes, deletion semantics and secret handling before any migration/import. It must not become a second memory authority.

Decision: HOLD until an isolated benchmark proves Captain-supplied namespace and epoch enforcement; no install.

## Scientific Agent Skills — ADAPT catalog

Source: `ts387/claude-scientific-skills` / Scientific Agent Skills.

Useful capability: 138 research/scientific skills using the open Agent Skills format, including literature/scientific-database workflows and specialist scientific methods.

Fit: high as an optional catalog because skills can be discovered progressively and loaded only when relevant, without adding another router or daemon.

Risks/cost: each imported skill is third-party instructions and may reference external tools, APIs or databases. Captain must record source/commit/license, expose per-skill enable/disable, never auto-enable paid providers, and run tool-requiring steps through existing permissions/execution gates.

Decision: ADAPT via a generic allowlisted skill-catalog adapter; do not bulk-install or eagerly load all skills.

## Anthropic Cybersecurity Skills (community project) — HOLD / defensive allowlist

Source: `mukul975/Anthropic-Cybersecurity-Skills` and mirrors/forks. Despite the name, upstream explicitly states it is independent and not affiliated with Anthropic.

Useful capability: a large Agent Skills-format cybersecurity knowledge catalog mapped to multiple security frameworks.

Fit: useful for secure coding, defensive reviews, forensics and authorized security work, but the catalog also contains offensive/dual-use techniques.

Risks/cost: never treat the repository name as an Anthropic endorsement. Do not bulk-enable. Active/offensive actions require Captain's normal authorization and tool gates; skills that invoke external targets or destructive tooling remain disabled by default.

Decision: HOLD wholesale import. Future adapter may allowlist defensive secure-coding/audit skills with provenance and explicit per-skill enablement.

## Strix — HOLD as optional security-validation subsystem

Source: `usestrix/strix`.

Useful capability: autonomous security assessment of applications/APIs/repos with finding validation and a potential build -> scan -> fix -> rescan loop.

Fit: potentially valuable after Captain's normal build/test/review loop, but only as an explicitly enabled security step on an authorized target/repository.

Risks/cost: Docker/provider overhead is non-trivial for the laptop; security scanning is high privilege and may touch external targets. An open August 2026 upstream issue reports provider-policy incompatibility around prompts requesting chain-of-thought-style reasoning on Azure/OpenAI-backed models, so provider prompt compatibility must be audited before integration. Never automatically run scans against third-party/live systems.

Decision: HOLD. Benchmark in an isolated local demo repo only after scope, authorization, provider and resource controls are in place.

## Daily conclusion

Highest-value near-term work remains inside Captain itself: enforce exact scope+epoch at every external context boundary and improve provenance/evidence quality without adding a second control plane. The continuity branch now extends the scoped research evidence ledger with claim-level relationships (`supports`, `challenges`, `context`) and secret-free coverage counts so Captain can detect when a conclusion has never been challenged while keeping those signals inside the exact project/repo/epoch authority wall.

For builder capability, Freebuff/Codebuff is the strongest new bounded integration candidate, but only through a narrow local adapter. Ruflo is primarily a pattern/library source because its full control plane overlaps Captain. OpenViking remains a context-provider candidate behind scoped external-context boundaries. Scientific Agent Skills is a strong generic skill-catalog candidate. Cybersecurity Skills and Strix remain opt-in/high-trust security capabilities, not default runtime dependencies.