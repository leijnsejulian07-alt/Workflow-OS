# Captain OSS scan — 2026-09-02

This is a research record, not permission to install or execute third-party code.

## New candidate: Singulary

- Source: `sammwyy/singulary` (GitHub), reviewed 2026-09-02.
- Claimed license: MIT; re-check exact commit and dependency licenses before any reuse.
- Capability: self-hosted app-builder with isolated Docker workspaces, code/file editing, runtime/debug loops, live application execution and snapshots/rollback.
- Captain fit: **ADAPT / reference candidate**, not a replacement orchestrator. Potentially useful behind Captain for builder-pane runtime, preview and reversible workspace patterns.
- Control-plane fit: acceptable only if Captain remains the sole user-facing router/orchestrator and Singulary is reduced to a bounded builder/sandbox adapter.
- Isolation requirement: every workspace/session/preview/snapshot call must carry Captain `chat_id + project_id + repo_scope` scope and current Project State epoch; unscoped or stale calls fail closed.
- Security: Docker/socket access, dependency installation, generated-code execution, network egress and secrets are high-trust boundaries. Never pass host secrets by default; use disposable workspaces, network/resource limits and explicit connector permissions.
- Laptop cost: potentially meaningful because Docker plus dev servers can consume substantial RAM/CPU/storage. Benchmark locally before adoption and keep it optional/off by default.
- Paid-provider risk: BYOK/provider integrations must never auto-enable or silently spend. Prefer existing/free/local providers where compatible.
- Maintenance check: repository was discoverable and active in the 2026-09-02 scan; exact release cadence/security advisories still require pin-time review.
- Decision: **HOLD for local benchmark, ADAPT patterns only today**. Do not install during fallback operation.

## Relevant official architecture reference

OpenAI's 2026 Agents SDK sandbox design explicitly separates the agent harness from compute/sandbox execution. That separation matches Captain's desired single-control-plane architecture: Captain can remain authoritative for project state, permissions and orchestration while a replaceable sandbox performs bounded execution. Treat this as an architecture reference; it is not permission to activate paid APIs.

## Next validation

When the Captain laptop is available, compare a minimal Singulary builder-runtime pilot against the existing/Open Builder path on: startup RAM, idle RAM, first-preview latency, disk growth, Windows reliability, rollback fidelity, network isolation, workspace deletion, scope propagation, and whether Captain can operate it without introducing a second router/daemon.
