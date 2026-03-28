# Phase 2: Document-Folder Integration - Discussion Log (Backfill)

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md. This log records the implementation audit used to backfill them.

**Date:** 2026-03-28
**Phase:** 02-document-folder-integration
**Mode:** backfill
**Areas analyzed:** Document placement model, Content storage and re-ingestion, Visibility and shared behavior

## Assumptions Presented

### Document placement model

| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Documents are folder-aware through nullable `folder_id`, with `NULL` representing private root. | Confident | `backend/migrations/008_knowledge_base_explorer.sql`, `backend/app/db/models.py`, `frontend/src/pages/DashboardPage.tsx` |
| Folder moves and document moves are separate update flows. | Confident | `backend/app/api/folders.py`, `backend/app/api/documents.py`, `backend/app/services/documents.py` |

### Content storage and re-ingestion

| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Full extracted markdown is stored on the document record after successful processing. | Confident | `backend/app/services/documents.py`, `backend/app/db/models.py` |
| Re-upload behavior is hash-based and skips unchanged content. | Confident | `backend/app/services/documents.py`, `backend/tests/test_prd_smoke.py` |
| Failed re-ingestion preserves previously successful content. | Confident | `backend/app/services/documents.py` |

### Visibility and shared behavior

| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Document visibility inherits from ownership or placement inside a global folder. | Confident | `backend/migrations/008_knowledge_base_explorer.sql`, `backend/app/services/folders.py`, `backend/tests/test_prd_smoke.py` |
| Global folders currently behave as shared write targets for document placement. | Likely | `backend/app/services/folders.py`, `backend/app/services/documents.py` |
| Document delete is owner-only and blocked during active ingestion. | Confident | `backend/app/services/documents.py`, `backend/app/api/documents.py` |

## Corrections Made

No live corrections. Context was backfilled from code review and existing tests.

## Open Interpretation Notes

- The global-folder shared-write behavior is implemented, but the roadmap text does not state explicitly whether that policy is intentional or merely acceptable.
- No matched todos for Phase 2.
