# Phase 1: Folder Schema & Core APIs - Context

**Gathered:** 2026-03-28 (backfilled from existing implementation)
**Status:** Ready for planning

<domain>
## Phase Boundary

Give users and agents a nested folder structure for organizing documents, with API support for create, rename, delete, and visibility rules for shared versus private folders. This phase defines the folder model and access rules; document placement and markdown storage are handled by later phases.

</domain>

<decisions>
## Implementation Decisions

### Folder model
- **D-01:** Folders use an adjacency-list schema with nullable `parent_id`; `/private` and `/global` are virtual roots rather than persisted root-folder rows.
- **D-02:** The only supported folder scopes are `private` and `global`, and a child folder must match its parent's scope.
- **D-03:** Folder names are unique among siblings case-insensitively, with uniqueness partitioned by scope and owner.

### Access and ownership
- **D-04:** Global folders are visible to all authenticated users; private folders are visible only to their owner.
- **D-05:** Folder mutation is owner-only: create under parent, rename, move, and delete all require ownership of the folder hierarchy being changed.
- **D-06:** Parent selection for writes is validated in the service layer and reinforced by database constraints and RLS.

### Validation and lifecycle
- **D-07:** Folder hierarchy validity is enforced in the database with cycle prevention and self-parent checks, not only in application code.
- **D-08:** Deleting a folder cascades to nested folders and linked documents through foreign keys and ORM relationships.

### the agent's Discretion
- Exact HTTP error wording beyond the current conflict and not-found semantics.
- Whether future planning should add API-level tests for folder CRUD endpoints or keep verification at the service/RLS layer.

</decisions>

<specifics>
## Specific Ideas

- Backfill is based on the live implementation rather than a greenfield design pass.
- The current product model treats roots as path prefixes (`/private`, `/global`) instead of actual folder records.

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Planning scope
- `.planning/ROADMAP.md` - Phase 1 goal, success criteria, and dependency boundary
- `.planning/REQUIREMENTS.md` - FOLDER-01, FOLDER-02, FOLDER-03, and FOLDER-05 definitions

### Database and access model
- `backend/migrations/008_knowledge_base_explorer.sql` - Folder table, hierarchy trigger, uniqueness rules, and RLS policies
- `backend/app/db/models.py` - `Folder` ORM shape and delete relationships
- `backend/app/db/session.py` - Request-scoped RLS context injection pattern

### API contract and service behavior
- `backend/app/schemas/folder.py` - Folder request and response schema contract
- `backend/app/services/folders.py` - Folder visibility, ownership, parent validation, and CRUD service logic
- `backend/app/api/folders.py` - HTTP surface for folder CRUD

### Current verification
- `backend/tests/test_prd_smoke.py` - Existing smoke coverage for RLS and global folder visibility

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `Folder` model in `backend/app/db/models.py`: already includes parent/child relationships and document backrefs.
- `visible_folder_clause()` and `get_optional_parent_for_write()` in `backend/app/services/folders.py`: established helpers for visibility and safe parent selection.
- `FolderCreateRequest`, `FolderUpdateRequest`, and `FolderResponse` in `backend/app/schemas/folder.py`: stable schema layer for API reuse.

### Established Patterns
- Thin FastAPI routers delegate to service modules rather than embedding business logic in route handlers.
- Authorization is enforced twice: Postgres RLS via request context and service-layer ownership checks.
- Structural integrity is pushed into the database through unique indexes and a trigger, not trusted to the client.

### Integration Points
- Folder routes are mounted through `backend/app/api/__init__.py`.
- Any new folder-aware behavior should reuse the same session/RLS binding from `backend/app/db/session.py`.
- Later document and KB-tool work already assumes this folder schema and root-path convention.

</code_context>

<deferred>
## Deferred Ideas

- Document placement, file moves, and stored markdown belong to Phase 2.
- Folder browsing/search/read tools belong to Phases 4 through 7.

</deferred>

---

*Phase: 01-folder-schema-core-apis*
*Context gathered: 2026-03-28*
