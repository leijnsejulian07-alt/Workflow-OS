# Captain OSS audit — 2026-09-11

Scope: late daily follow-up audit requested for Ruflo, Freebuff, OpenViking, Scientific Agent Skills and the community Anthropic Cybersecurity Skills library. This note is evidence for future integration decisions only. It grants no permission to install, execute, authenticate, or send project data to third-party services.

## Architectural gate

Captain remains the only user-facing control plane and authority for routing, Project State, memory, connectors, permissions and UI. Any candidate must sit behind a bounded adapter and must not weaken `chat_id + project_id + repo_scope + state_epoch` isolation. No candidate may silently use a paid/hosted API, copy secrets, or gain broad filesystem/network authority.

## Ruflo (`ruvnet/ruflo`) — IDEA_ONLY / HOLD

Potential value: orchestration/swarm patterns, workflow decomposition, memory/indexing ideas, MCP/tool catalog patterns and sandbox concepts.

Fit concerns: Ruflo is itself a large orchestration/control-plane stack and therefore overlaps Captain's router, orchestration, memory and agent authority. The repository is very large, which increases dependency and review cost on the current Windows laptop. A recent hands-on community audit also disputes several headline orchestration claims and reports that some swarm behavior is prompt simulation rather than true subprocess orchestration. Treat that report as community evidence, not definitive proof, but it is sufficient to block blind installation.

Decision: do not install Ruflo wholesale. Reuse only independently verified design patterns after source-level inspection. Any future code reuse requires exact commit/license/dependency review and a focused benchmark against Captain's existing runtime.

## Freebuff / Codebuff (`CodebuffAI/freebuff`) — ADAPT candidate

Potential value: repo-aware coding agent loops, code-map/file discovery, implementation/review agents and the Codebuff SDK as a possible builder backend behind Captain.

Fit concerns: Freebuff is a TypeScript/Bun monorepo and local development expects Docker plus environment configuration, which is non-trivial laptop overhead. Its hosted service documentation states that prompts, messages, traces, code, files and repository data are processed by the service, with additional model/data-use conditions for some providers. That makes direct cloud use inappropriate as a default for private Captain projects.

Decision: audit the SDK/runtime boundary only. Prefer local/self-controlled execution and a narrow Captain adapter. Captain must remain owner of Project State, memory, provider routing and permissions. Do not enable hosted repository access by default.

## OpenViking (`volcengine/OpenViking`) — ADAPT candidate, isolation proof required

Potential value: navigable memory/knowledge/skill context, hierarchical context representations and explainable retrieval/provenance patterns. This aligns well with Captain's need for stronger context retrieval without replacing the visible Captain experience.

Fit concerns: OpenViking must not become a parallel source of truth. Before any pilot, prove that every read/write can be hard-bound to Captain's full authority tuple and current Project State epoch, and that stale-epoch or cross-project retrieval fails closed. Resource cost, background indexing and Windows compatibility must be measured locally.

Decision: investigate a read-only context adapter first. Captain Project Memory remains canonical. Promotion beyond read-only requires explicit epoch-isolation regressions and rollback tests.

## Scientific Agent Skills (`K-Dense-AI/scientific-agent-skills` and mirrors) — ADAPT selectively

Potential value: roughly 138+ research/scientific skills covering scientific databases, analysis packages and reproducible research workflows. The open skill format is a good architectural fit because Captain can discover a skill without adding another daemon or router.

License note: the repository is MIT, but upstream explicitly warns that individual skills can carry their own license metadata and requirements. Therefore repository-level MIT status is not enough for bulk import.

Decision: build/select a per-skill import gate rather than copying the whole catalog. Validate each chosen skill's license, dependencies, network/API behavior and provenance. Lazy-load only when relevant to a task.

## Community Anthropic Cybersecurity Skills (`mukul975/Anthropic-Cybersecurity-Skills`) — HOLD / allowlist only

Potential value: hundreds of structured defensive-security, DFIR, threat-intelligence, cloud-security and secure-development skills in an open agent-skills format. The project is community-created and explicitly not affiliated with Anthropic.

Risk: the catalog also contains offensive and dual-use techniques. A bulk import would unnecessarily expand Captain's high-risk capability surface and dependency/instruction attack surface.

Decision: never bulk-enable. If later needed, import only narrowly reviewed defensive skills under a capability allowlist, with normal authorization/safety gates and no implicit access to credentials, networks or production systems. Repository reports Apache-2.0; exact skill/dependency review is still required.

## Priority after this audit

1. OpenViking: prototype only a read-only, epoch-bound retrieval adapter after the local laptop is reachable.
2. Freebuff/Codebuff: inspect the SDK/code-map boundary for the OpenBuilder plan-build-test-review loop; avoid hosted repo data by default.
3. Scientific Agent Skills: implement generic skill discovery/import metadata before adding individual skills.
4. Ruflo: mine only verified patterns; no install while architecture overlap and claim-verification concerns remain.
5. Cybersecurity catalog: keep disabled except explicitly reviewed defensive skills.

## Local verification still required

This audit was written while B31077499 was unreachable. Nothing here is locally installed or locally verified. On reconnection, reconcile this note into the local Captain knowledge/checkpoint, then run the normal Doctor/router/OpenBuilder regressions before treating any future adapter as integrated.