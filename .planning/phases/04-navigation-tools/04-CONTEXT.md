# Phase 4: Navigation Tools - Context

**Gathered:** 2026-03-28
**Status:** Ready for planning
**Source:** Roadmap + existing implementation audit + supplemental Episode 4 PRD reference

<domain>
## Phase Boundary

Give the agent filesystem-style navigation over the knowledge base by adding `ls(path)` and `tree(path, depth?, limit?)` behavior that works against the folder/document hierarchy and respects the existing visibility model. This phase is limited to browsing structure; content search and document reading remain in later phases.

</domain>

<decisions>
## Implementation Decisions

### Navigation surface
- **D-01:** Phase 4 only covers `ls` and `tree`; `grep`, `glob`, `read`, and delegated document analysis remain out of scope for this phase even if they already exist elsewhere in the current codebase.
- **D-02:** Knowledge-base paths are filesystem-like and rooted at `/`, with `/global` and `/private` as the top-level scopes.
- **D-03:** Folder traversal uses the existing folder hierarchy and the same virtual-root convention established in earlier phases rather than creating persisted root-folder rows.

### Path and visibility semantics
- **D-04:** Path resolution must reject invalid roots and missing folder paths with explicit errors rather than falling back silently.
- **D-05:** Results must respect the existing folder/document visibility rules: users can see their private content plus globally visible content, and nothing outside that scope.
- **D-06:** `/` should enumerate the two knowledge-base roots; `/private` and `/global` should enumerate visible child folders, with private-root documents appearing under `/private`.

### Output behavior
- **D-07:** `ls` should return structured entries for folders and documents so downstream tooling can reason about paths, kinds, IDs, and statuses without reparsing prose.
- **D-08:** `tree` should return a hierarchical text rendering plus truncation metadata so the agent can browse large structures without overrunning context.
- **D-09:** Depth and limit controls are part of the contract for `tree`, and truncation is an expected, first-class behavior rather than an error.

### Integration expectations
- **D-10:** Navigation tooling should plug into the existing knowledge-base/explorer architecture rather than introducing a separate service surface or storage model.
- **D-11:** Tool descriptions and outputs should stay concise and agent-friendly, following the repo’s existing function-tool patterns.

### the agent's Discretion
- Exact JSON field naming beyond what the existing tool/explorer integration already expects.
- Whether a database function is still warranted, or whether the current Python-service implementation is the locked direction for Phase 4 execution planning.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Planning scope
- `.planning/ROADMAP.md` - Phase 4 goal, success criteria, and plan hints
- `.planning/REQUIREMENTS.md` - TOOL-01 and TOOL-02 requirements
- `.planning/STATE.md` - Current planning/session state

### Prior phase decisions
- `.planning/phases/01-folder-schema-core-apis/01-CONTEXT.md` - Folder model, scope rules, RLS, and virtual-root conventions
- `.planning/phases/02-document-folder-integration/02-CONTEXT.md` - Document placement and folder-aware document visibility
- `.planning/phases/03-ingestion-ui/03-CONTEXT.md` - UI-side path/selection expectations that already depend on folder semantics

### Existing implementation
- `backend/app/services/knowledge_base.py` - Current `ls`/`tree` path resolution and visibility logic
- `backend/app/services/explorer_agent.py` - Tool schemas and explorer integration points for `ls` and `tree`
- `backend/app/services/chat.py` - Main chat-router integration for the knowledge-base explorer flow
- `backend/app/services/folders.py` - Shared visibility clauses for folders/documents
- `backend/app/db/models.py` - Folder/document relationships that navigation traverses
- `backend/tests/test_prd_smoke.py` - Existing smoke coverage around knowledge-base tooling behavior

### Supplemental external reference
- `C:/Repo_VS_Code/Agentic-rag/_episode_src/ep4-skills-sandbox-video/PRD-Skills-Sandbox.md` - Supplemental reference for tool-oriented agent UX and tool registration patterns; not the source of Phase 4 scope

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `execute_ls()` and `execute_tree()` in `backend/app/services/knowledge_base.py`: existing navigation primitives that already encode root paths, child enumeration, and truncation behavior.
- `EXPLORER_TOOLS` in `backend/app/services/explorer_agent.py`: existing tool-definition pattern for function-call exposure.
- `looks_like_explorer_request()` and chat-side explorer routing in `backend/app/services/chat.py`: established integration path for filesystem-style questions.

### Established Patterns
- The backend uses Python service functions over SQLAlchemy models for knowledge-base tooling rather than database-stored procedures.
- Visibility is enforced through shared clauses and request-bound RLS context, not duplicated ad hoc per tool.
- Agent-facing tools return compact structured payloads that can be summarized in traces and reused by higher-level orchestration.

### Integration Points
- Phase 4 work connects primarily to `backend/app/services/knowledge_base.py`, then to `backend/app/services/explorer_agent.py`, and finally to `backend/app/services/chat.py`.
- Any validation should cover both direct tool behavior and the explorer/chat path that consumes these outputs.
- Existing search/read tools are already colocated with navigation logic, so planning should isolate only the `ls/tree` slice for this phase.

</code_context>

<specifics>
## Specific Ideas

- The desired user-facing behavior is “browse the knowledge base like a filesystem,” not “query a database table.”
- The Episode 4 PRD reinforces that tool contracts should be explicit and easy for the agent to discover/use, but it does not redefine Phase 4 scope.
- The current codebase already contains a broader knowledge-base tool stack than the roadmap suggests, so planning should account for retroactive alignment and potential hardening rather than assuming greenfield implementation.

</specifics>

<deferred>
## Deferred Ideas

- Content search by regex or filename pattern belongs to Phase 5.
- Full-document and line-range reading belongs to Phase 6.
- Explorer sub-agent orchestration concerns belong to Phase 7, except where Phase 4 must expose `ls/tree` cleanly for later consumption.

</deferred>

---

*Phase: 04-navigation-tools*
*Context gathered: 2026-03-28*
