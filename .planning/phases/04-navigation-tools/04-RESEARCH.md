# Phase 4: Navigation Tools - Research

**Date:** 2026-03-28
**Phase:** 04-navigation-tools
**Status:** Complete

## Research Goal

Determine how Phase 4 should be planned given the current codebase already contains filesystem-style knowledge-base navigation, broader explorer tooling, and chat integration. The planning target is not pure greenfield implementation; it is a clean execution slice that satisfies TOOL-01 and TOOL-02 with defensible tests and stable integration points.

## What Already Exists

### Navigation primitives already implemented

- `backend/app/services/knowledge_base.py` already implements:
  - path normalization and root handling via `normalize_kb_path()` and `resolve_path()`
  - folder/document visibility enumeration via `list_visible_folders()` and `list_visible_documents()`
  - `execute_ls()` with structured folder/document entries
  - `execute_tree()` with `depth`, `limit`, and `truncated` semantics
- The implementation already uses the Phase 1/2 decisions:
  - virtual roots `/global` and `/private`
  - private-root documents represented by `folder_id = NULL`
  - shared/private visibility inherited from the folder/document model

### Tool exposure already implemented

- `backend/app/services/explorer_agent.py` already defines `ls` and `tree` in `EXPLORER_TOOLS`.
- The explorer sub-agent already executes `execute_ls()` and `execute_tree()` through function-tool dispatch.
- `backend/app/services/chat.py` already routes filesystem-style knowledge-base requests into the explorer flow.

### Existing verification

- `backend/tests/test_prd_smoke.py` exercises knowledge-base tools, but the current explicit smoke assertion is for `grep`, `glob`, and `read`, not for direct `ls`/`tree` behavior.
- There is no dedicated regression test that locks down:
  - `/` root listing behavior
  - `/private` root document handling
  - `/global` visibility handling in tree output
  - truncation semantics for large trees
  - invalid-path error behavior for navigation tools

## Architecture Findings

### Recommended implementation direction

Keep Phase 4 centered on the existing Python service implementation in `backend/app/services/knowledge_base.py`.

Why:
- The current code already expresses the navigation contract in one place.
- The explorer/tool layer is already wired to those Python functions.
- Adding a database function now would introduce a second source of truth with no clear benefit for this repo’s current architecture.
- The roadmap’s phrase “Database function and Python service” should be treated as an initial plan hint, not a locked technical requirement.

### Existing contract shape

`ls` contract:
- input: `path`
- output: `{ path, entries[] }`
- entries distinguish `kind = folder | document`
- folder entries include path, scope, and folder ID
- document entries include path, document ID, and status

`tree` contract:
- inputs: `path`, `depth`, `limit`
- output: `{ path, depth, limit, truncated, output }`
- `output` is text optimized for agent consumption
- `truncated` is a first-class signal, not implicit in the text

### Integration boundary

Phase 4 should stop at “navigation tools are stable and consumable.” It should not absorb:
- Phase 5 content search behaviors
- Phase 6 read semantics
- Phase 7 explorer reasoning-loop behavior beyond consuming `ls`/`tree`

## Risks and Gaps

### 1. Roadmap and implementation drift

Risk:
- The roadmap says Phase 4 is not started, but the repo already contains `ls`/`tree` and downstream integration.

Planning consequence:
- Plans should include alignment and validation tasks, not assume a blank slate.

### 2. Missing direct regression coverage for `ls` and `tree`

Risk:
- Future changes to folder visibility, root semantics, or output shape could break navigation without any test catching it.

Planning consequence:
- At least one plan should add targeted tests for `execute_ls()` and `execute_tree()`.

### 3. Contract ambiguity between human-readable and machine-usable outputs

Risk:
- `ls` is structured; `tree` is textual plus metadata. That split is workable, but it must be treated as intentional and documented in the plan.

Planning consequence:
- The plan should preserve and verify both outputs explicitly rather than “refactor for consistency” without a defined target.

### 4. Private-root and shared-root edge cases

Risk:
- The trickiest behaviors live at the virtual roots:
  - root `/`
  - `/private` with `folder_id = NULL` documents
  - `/global` with shared folders/documents

Planning consequence:
- Tests and acceptance criteria should emphasize root and cross-user visibility cases first.

### 5. Broader explorer stack fragility

Risk:
- `ls` and `tree` are consumed by a larger explorer loop. Contract changes can silently destabilize the sub-agent even if the helpers still “work.”

Planning consequence:
- One plan should verify tool-definition compatibility and explorer/chat integration assumptions after any navigation changes.

## Supplemental PRD Takeaways

From `C:/Repo_VS_Code/Agentic-rag/_episode_src/ep4-skills-sandbox-video/PRD-Skills-Sandbox.md`:

- Tool contracts should be explicit and discoverable.
- Tool descriptions should be concise and oriented around when to use them.
- Tool-driven agent workflows benefit from structured outputs and lightweight summaries.

How this affects Phase 4:
- Keep `ls` and `tree` descriptions crisp and agent-facing.
- Preserve metadata that higher-level orchestration can consume without brittle parsing.
- Treat navigation-tool outputs as stable contracts for later agent features.

How this does **not** affect Phase 4:
- Skills, code execution, import/export, and persistent tool memory are not part of the Phase 4 roadmap scope.

## Recommended Plan Shape

### Plan A: Navigation service semantics and coverage

Goal:
- Lock down `ls` and `tree` behavior in `backend/app/services/knowledge_base.py`

Should cover:
- root-path handling
- `/global` and `/private` semantics
- folder/document entry enumeration
- depth/limit/truncation behavior
- explicit errors for invalid paths
- direct test coverage for `execute_ls()` and `execute_tree()`

### Plan B: Tool-contract and integration alignment

Goal:
- Ensure the existing `ls`/`tree` tool exposure remains stable for explorer/chat consumers

Should cover:
- `EXPLORER_TOOLS` definitions for `ls`/`tree`
- execution wiring in `backend/app/services/explorer_agent.py`
- assumptions in `backend/app/services/chat.py`
- any doc or trace summary updates needed so the contract is obvious and durable

## File-Level Guidance For Planner

High-priority files:
- `backend/app/services/knowledge_base.py`
- `backend/app/services/explorer_agent.py`
- `backend/app/services/chat.py`
- `backend/tests/test_prd_smoke.py`

Potential secondary files:
- `.planning/ROADMAP.md` only if the execution plan intentionally includes roadmap/state reconciliation
- `.planning/REQUIREMENTS.md` only if the execution plan intentionally aligns status markers

## Validation Architecture

### Existing infrastructure

- Framework: Python `unittest`
- Config file: none
- Quick run command: `python -m unittest backend.tests.test_prd_smoke.PRDSmokeTests.test_knowledge_base_tools_support_grep_glob_and_read -v`
- Full suite command: `python -m unittest backend.tests.test_prd_smoke -v`
- Estimated runtime: ~10-20 seconds for the full smoke file in local dev

### Validation strategy for this phase

- Add direct `ls`/`tree` assertions to backend smoke coverage or a dedicated backend test module.
- Use quick runs for the exact navigation tests while implementing.
- Use the full backend smoke run after each plan wave.
- Keep validation backend-only for this phase; frontend browser tests are not required because Phase 4 is an agent-tool contract, not a visible UI feature.

## Research Conclusion

## RESEARCH COMPLETE

Phase 4 should be planned as a two-slice hardening/alignment phase around already-existing `ls`/`tree` functionality:
- one slice to formalize and test navigation semantics in `knowledge_base.py`
- one slice to verify and preserve the explorer/chat tool contract that consumes those primitives

The key planning risk is not lack of code; it is implementation drift, missing direct regression coverage, and ambiguity about which existing behaviors are now locked.
