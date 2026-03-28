# Phase 2: Document-Folder Integration - Context

**Gathered:** 2026-03-28 (backfilled from existing implementation)
**Status:** Ready for planning

<domain>
## Phase Boundary

Connect documents to folders so uploads, moves, and later explorer tooling operate against a hierarchical knowledge base. This phase covers folder assignment, document moves, folder moves, and storing full extracted markdown alongside chunks.

</domain>

<decisions>
## Implementation Decisions

### Document placement model
- **D-01:** Documents carry a nullable `folder_id`; `NULL` represents the user's private root rather than a special folder row.
- **D-02:** Upload requests accept an optional `folder_id`, and the target folder is resolved before the document record is created or updated.
- **D-03:** Folder moves are performed by updating a folder's `parent_id`; document moves are performed by updating the document's `folder_id`.

### Content storage and re-ingestion
- **D-04:** Successful ingestion stores full extracted markdown on `Document.full_markdown` in addition to chunk rows.
- **D-05:** Upload identity is keyed by `source_key`, with content hashing used to detect unchanged re-uploads and skip unnecessary re-indexing.
- **D-06:** Changed re-uploads replace chunks, increment document versioning, and preserve the last successful content if a later re-ingestion fails.

### Visibility and shared behavior
- **D-07:** Document visibility is based on ownership or placement in a global folder; private-root and private-folder documents remain owner-scoped.
- **D-08:** Uploading or moving a document into a visible global folder is currently allowed for any authenticated user; writes into another user's private folders are explicitly forbidden.
- **D-09:** Document deletion remains owner-only and is blocked while ingestion is running.

### the agent's Discretion
- Whether future hardening should narrow global-folder write access or leave the current shared-write model in place.
- Whether move and upload flows need dedicated API-contract tests in addition to service and smoke coverage.

</decisions>

<specifics>
## Specific Ideas

- Full searchable/readable content is the extracted markdown text produced by the ingestion pipeline, not raw uploaded bytes.
- The current implementation already handles re-index and unchanged-upload behavior, so planning should treat those as locked behaviors rather than optional enhancements.

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Planning scope
- `.planning/ROADMAP.md` - Phase 2 goal, success criteria, and planned sub-areas
- `.planning/REQUIREMENTS.md` - FOLDER-04, DOC-01, DOC-02, and DOC-03 definitions

### Database and models
- `backend/migrations/008_knowledge_base_explorer.sql` - `documents.folder_id`, `documents.full_markdown`, folder hierarchy trigger, and document/chunk RLS updates
- `backend/app/db/models.py` - `Document.folder_id`, `Document.full_markdown`, and document-folder relationships
- `backend/app/schemas/document.py` - Document response and move request contract

### Service and API behavior
- `backend/app/services/documents.py` - Upload preparation, full-markdown persistence, re-index behavior, delete protection, and document move logic
- `backend/app/services/folders.py` - Folder target resolution and shared/private write rules
- `backend/app/api/documents.py` - Upload, list, move, delete, and status endpoints
- `backend/app/api/folders.py` - Folder move surface through folder patching

### Current verification
- `backend/tests/test_prd_smoke.py` - Existing smoke coverage for global visibility, unchanged re-uploads, knowledge-base behavior, and status streaming

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `prepare_document_upload()` in `backend/app/services/documents.py`: central entry point for folder-aware upload and dedupe behavior.
- `process_document()` in `backend/app/services/documents.py`: already writes full markdown, chunks, metadata, and ingestion state.
- `DocumentMoveRequest` and `move_document_for_user()` provide a stable move contract for both UI and future tools.

### Established Patterns
- Uploads land in local storage first, then background ingestion persists durable document state.
- Versioning and last-ingestion result are first-class parts of the document lifecycle, not UI-only decorations.
- Ownership is checked in service code even though RLS also protects the tables.

### Integration Points
- Folder-aware uploads already flow through `/documents/upload`.
- Document move behavior is already consumed by the dashboard UI and by later KB explorer logic.
- `full_markdown` is already read by grep and read tooling in later phases, so this phase is a dependency already exercised by the codebase.

</code_context>

<deferred>
## Deferred Ideas

- Visual folder management and upload UX belong to Phase 3.
- Filesystem-style browse/search/read tools belong to Phases 4 through 7.

</deferred>

---

*Phase: 02-document-folder-integration*
*Context gathered: 2026-03-28*
