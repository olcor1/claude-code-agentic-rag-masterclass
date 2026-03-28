# Coding Conventions

**Analysis Date:** 2026-03-28

## Naming Patterns

**Files:**
- Backend Python uses `snake_case.py` throughout `backend/app/`
- React pages use `PascalCase.tsx` in `frontend/src/pages/`
- Hooks use `use-*.tsx`, for example `frontend/src/hooks/use-auth.tsx`
- Utility and API files stay lowercase or kebab-case, for example `frontend/src/api/client.ts` and `frontend/src/lib/auth-session.ts`
- SQL migrations use ordered numeric prefixes such as `backend/migrations/008_knowledge_base_explorer.sql`

**Functions:**
- Python functions use `snake_case`, for example `stream_conversation_reply()` and `prepare_document_upload()`
- TypeScript functions and handlers use `camelCase`, for example `handleDeleteDocument`, `buildFolderMap`, and `streamConversationMessage`
- Async functions do not use a naming prefix beyond the verb that describes the operation

**Variables:**
- Python variables are `snake_case`
- TypeScript variables are `camelCase`
- Constants are `UPPER_SNAKE_CASE`, for example `WORKSPACE_SQL_ANALYTICS_PATTERN`, `API_BASE_URL`, and `AUTH_TOKEN_STORAGE_KEY`

**Types:**
- SQLAlchemy models and dataclasses use `PascalCase`, for example `Document`, `WorkspaceSQLResult`, and `RetrievedChunk`
- Frontend type aliases also use `PascalCase`, for example `Message`, `Citation`, and `FolderRecord`

## Code Style

**Formatting:**
- Python follows a Black-like/PEP 8 style even though no formatter config is committed
- TypeScript uses semicolons and double-quoted import strings consistently in the current files
- Tailwind utility strings are written inline in JSX rather than abstracted into styled component systems
- Python type hints are used heavily across services, schemas, and models

**Linting:**
- No ESLint, Prettier, Ruff, or Black config is committed
- Frontend enforcement is currently TypeScript-based via `npm run typecheck`
- Backend style is convention-driven rather than tool-enforced

## Import Organization

**Order:**
1. Standard library / platform modules
2. Third-party packages
3. Internal application imports such as `from app...` or `@/...`

**Grouping:**
- Both Python and TypeScript files usually separate import groups with blank lines
- Type-only frontend imports use `import type { ... }` when appropriate, as seen in `frontend/src/api/client.ts`
- Frontend code prefers the `@/*` alias for internal imports instead of long relative paths

**Path Aliases:**
- `@/*` maps to `frontend/src/*` via `frontend/tsconfig.json`
- Backend uses package-root imports like `from app.services.chat import ...`

## Error Handling

**Patterns:**
- Backend services raise `HTTPException` for user-facing domain errors, especially in `backend/app/services/documents.py` and `folders.py`
- Provider- and parser-level exceptions are translated into clearer application errors before reaching the API layer
- Long-running backend work tends to persist failure state onto models instead of letting exceptions disappear silently
- Frontend `request()` in `frontend/src/api/client.ts` throws `Error` objects after unpacking backend `detail` payloads

**Error Types:**
- Use explicit custom exception classes for parser/document concerns, for example `DocumentExtractionError` and `ParserDependencyError`
- Use persistent job/document status for ingestion failures
- Use SSE status and trace events for chat/tool progress rather than only final success/failure payloads

## Logging

**Framework:**
- Python `logging` is used sparingly, mainly around tracing setup in `backend/app/services/tracing.py`
- Frontend code does not establish a client-side logging framework

**Patterns:**
- Operational insight relies more on persisted state, traces, and `.dev-logs/` than on pervasive structured logging
- There is no repo-wide logger abstraction yet

## Comments

**When to Comment:**
- Comments are sparse and generally reserved for defensive notes such as `# pragma: no cover` or setup guards
- Most files rely on descriptive helper/function names instead of explanatory comments
- Existing code does not use verbose inline narration

**JSDoc/TSDoc:**
- Not common in the frontend code
- Python docstrings are also uncommon in the runtime modules

**TODO Comments:**
- No active `TODO`/`FIXME` convention showed up in `backend/app/`, `frontend/src/`, or the test directories during this mapping pass

## Function Design

**Size:**
- Small helper functions are common at the top of modules
- The notable exceptions are large orchestration files such as `backend/app/services/chat.py` and `frontend/src/pages/DashboardPage.tsx`

**Parameters:**
- Python favors explicit named parameters, often with keyword-only style in service functions
- TypeScript handlers often accept concrete typed objects or primitive arguments instead of deep option objects

**Return Values:**
- Backend services frequently return ORM models or dataclass payloads
- Frontend data helpers return parsed JSON payloads or feed streamed events into callbacks
- Guard clauses are common in both Python and TypeScript

## Module Design

**Exports:**
- Backend modules usually expose named functions, dataclasses, or models
- Frontend shared modules use named exports for components and helpers
- `frontend/src/App.tsx` is a rare default export; most other frontend modules are named-export based

**Barrel Files:**
- Python package barrels exist as `__init__.py`, for example `backend/app/api/__init__.py`
- Frontend barrel files are not a dominant pattern in this codebase

---
*Convention analysis: 2026-03-28*
*Update when patterns change*
