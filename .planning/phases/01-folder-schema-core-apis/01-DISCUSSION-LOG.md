# Phase 1: Folder Schema & Core APIs - Discussion Log (Backfill)

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md. This log records the implementation audit used to backfill them.

**Date:** 2026-03-28
**Phase:** 01-folder-schema-core-apis
**Mode:** backfill
**Areas analyzed:** Folder model, Access and ownership, Validation and lifecycle

## Assumptions Presented

### Folder model

| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Folders are implemented as an adjacency list with `parent_id` and virtual scope roots. | Confident | `backend/migrations/008_knowledge_base_explorer.sql`, `backend/app/db/models.py`, `backend/app/services/knowledge_base.py` |
| Scope is limited to `private` and `global`, and scope must match across parent-child links. | Confident | `backend/migrations/008_knowledge_base_explorer.sql`, `backend/app/schemas/folder.py`, `backend/app/services/folders.py` |
| Sibling folder names are case-insensitively unique within the relevant ownership boundary. | Confident | `backend/migrations/008_knowledge_base_explorer.sql` |

### Access and ownership

| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Global folders are visible to everyone, while private folders are owner-scoped. | Confident | `backend/migrations/008_knowledge_base_explorer.sql`, `backend/app/services/folders.py`, `backend/tests/test_prd_smoke.py` |
| Folder mutation is owner-only. | Confident | `backend/app/services/folders.py`, `backend/app/api/folders.py` |

### Validation and lifecycle

| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Folder cycles and invalid parent links are prevented at the database level. | Confident | `backend/migrations/008_knowledge_base_explorer.sql` |
| Folder delete cascades into descendants and attached documents. | Confident | `backend/migrations/008_knowledge_base_explorer.sql`, `backend/app/db/models.py` |

## Corrections Made

No live corrections. Context was backfilled from code review and existing tests.

## External Signals

- No matched todos for Phase 1.
- Existing roadmap state is stale relative to the implementation and should be reconciled separately.
