# Phase 3: Ingestion UI - Context

**Gathered:** 2026-03-28 (backfilled from existing implementation)
**Status:** Ready for planning

<domain>
## Phase Boundary

Provide a visual ingestion workspace where users can browse the folder hierarchy, distinguish shared from private locations, manage folders from the UI, and upload files into the currently selected folder.

</domain>

<decisions>
## Implementation Decisions

### Workspace layout
- **D-01:** The ingestion experience is implemented as an `activeView="ingestion"` workspace inside `DashboardPage.tsx`, not as a separate route or standalone page module.
- **D-02:** The folder tree is split into two visible root sections: private root and shared space.
- **D-03:** The selected folder drives the upload target, the current-folder inventory panel, and the folder-management controls.

### Folder interactions
- **D-04:** Users can create child folders from the currently selected folder context, or create root folders when no folder is selected.
- **D-05:** Rename, move, and delete controls are available in the selected-folder panel, with owner-only checks enforced in the UI before API calls.
- **D-06:** Global folders are visually distinguished with a globe icon and a "Shared" label; private folders use a neutral icon treatment and "Private" labeling.

### Document interactions
- **D-07:** File uploads are folder-targeted; if no folder is selected, uploads go to private root.
- **D-08:** Document cards expose location, move controls, delete controls, and ingestion-status badges from the same workspace.
- **D-09:** The UI subscribes to document status SSE updates so folder-aware ingestion progress is reflected live.

### the agent's Discretion
- Whether to later extract the ingestion view into dedicated feature components or keep the current single-page composition.
- Whether future planning should add end-to-end browser tests for the ingestion workspace.

</decisions>

<specifics>
## Specific Ideas

- The UI is functionally complete but still lives mostly inside one large page file; the planner should treat component extraction as maintainability work, not missing core functionality.
- The visual language already treats shared space as a first-class concept rather than a backend-only flag.

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Planning scope
- `.planning/ROADMAP.md` - Phase 3 goal, UI success criteria, and planned sub-areas
- `.planning/REQUIREMENTS.md` - UI-01, UI-02, UI-03, and UI-04 definitions

### Frontend contract and behavior
- `frontend/src/api/types.ts` - Folder and document client-side data shapes
- `frontend/src/api/client.ts` - Folder fetch/create/update/delete, document upload, and document move API calls
- `frontend/src/pages/DashboardPage.tsx` - Current ingestion workspace, folder tree, folder controls, and upload targeting behavior

### Shared UI primitives
- `frontend/src/components/ui/button.tsx` - Existing button styling primitive
- `frontend/src/components/ui/card.tsx` - Existing card layout primitive
- `frontend/src/components/ui/input.tsx` - Existing input primitive
- `frontend/src/components/ui/badge.tsx` - Existing badge primitive used for state labeling

### Current backend dependencies
- `backend/app/api/folders.py` - Folder CRUD endpoints consumed by the UI
- `backend/app/api/documents.py` - Upload, move, delete, and status endpoints consumed by the UI

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `FolderTreeNode` in `frontend/src/pages/DashboardPage.tsx`: existing recursive tree renderer for nested folders.
- `DocumentCard` in `frontend/src/pages/DashboardPage.tsx`: existing inventory card for move/delete/status interactions.
- Shared primitives in `frontend/src/components/ui/`: already provide the styling foundation used by the ingestion workspace.

### Established Patterns
- Frontend state is local React state with derived maps via `useMemo`; there is no separate state library.
- Workspace refreshes use `Promise.all` over conversations, documents, and folders to keep the dashboard synchronized.
- Live ingestion progress is handled with SSE and local reconciliation of updated document payloads.

### Integration Points
- Upload target is passed through `uploadDocument(token, file, sourceKey, selectedFolderId)`.
- Folder selection feeds document filtering, folder move options, and panel state in one place.
- The same document and folder records shown in chat-side inventory are reused inside the ingestion workspace.

</code_context>

<deferred>
## Deferred Ideas

- Search within the folder tree and keyboard navigation are tracked as v2 UI requirements.
- Drag-and-drop folder reordering remains out of scope for this phase.

</deferred>

---

*Phase: 03-ingestion-ui*
*Context gathered: 2026-03-28*
