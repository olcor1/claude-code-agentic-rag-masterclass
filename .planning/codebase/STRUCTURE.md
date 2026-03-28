# Codebase Structure

**Analysis Date:** 2026-03-28

## Directory Layout

```text
claude-code-agentic-rag-masterclass/
├── .agent/                  # Episode/module planning notes
├── .claude/                 # Claude command config and local settings
├── .dev-logs/               # Local runtime logs and temporary debug artifacts
├── .planning/               # GSD project docs plus codebase map
│   ├── codebase/            # Generated codebase reference documents
│   └── research/            # Project research artifacts
├── backend/                 # FastAPI app, DB migrations, smoke tests, uploads
│   ├── app/                 # API routes, services, db models, schemas, utilities
│   ├── migrations/          # Ordered PostgreSQL migrations
│   ├── scripts/             # DB bootstrap utilities
│   ├── tests/               # Python smoke/integration tests
│   └── uploads/             # Local uploaded documents
├── frontend/                # Vite + React client
│   ├── src/api/             # HTTP client and API-facing types
│   ├── src/components/ui/   # Reusable UI primitives
│   ├── src/hooks/           # Auth/session hooks
│   ├── src/lib/             # Shared frontend helpers
│   └── src/pages/           # Auth and dashboard screens
├── tests/                   # Manual smoke checklist
├── ollama/                  # Local model configuration artifacts
├── docker-compose.yml       # Local PostgreSQL + pgvector service
├── start-dev.ps1            # Local dev startup helper
└── README.md                # Project overview and setup notes
```

## Directory Purposes

**backend/app/**
- Purpose: All runtime backend code
- Contains: `api/`, `core/`, `db/`, `schemas/`, `services/`, and `utils/`
- Key files: `backend/app/main.py`, `backend/app/db/models.py`, `backend/app/services/chat.py`
- Subdirectories: routes in `api/`, persistence in `db/`, business logic in `services/`

**backend/migrations/**
- Purpose: Database evolution
- Contains: numbered `.sql` migration files such as `001_init.sql` through `009_pii_redaction_registry.sql`
- Key files: `007_row_level_security.sql`, `008_knowledge_base_explorer.sql`, `009_pii_redaction_registry.sql`
- Subdirectories: none

**backend/tests/**
- Purpose: Automated smoke/integration testing for backend behavior
- Contains: `test_prd_smoke.py`
- Key files: `backend/tests/test_prd_smoke.py`
- Subdirectories: none

**frontend/src/pages/**
- Purpose: Top-level screens
- Contains: `AuthPage.tsx` and `DashboardPage.tsx`
- Key files: `frontend/src/pages/DashboardPage.tsx` is the main authenticated workspace screen
- Subdirectories: none currently

**frontend/src/api/**
- Purpose: Frontend/backend contract layer
- Contains: `client.ts` and `types.ts`
- Key files: `frontend/src/api/client.ts` wraps fetch and SSE parsing; `frontend/src/api/types.ts` mirrors backend payloads
- Subdirectories: none

**frontend/src/components/ui/**
- Purpose: Small presentational building blocks
- Contains: `button.tsx`, `card.tsx`, `input.tsx`, `textarea.tsx`, `badge.tsx`
- Key files: these are styling primitives rather than feature components
- Subdirectories: none

**.planning/**
- Purpose: GSD project memory for this repo
- Contains: `PROJECT.md`, `REQUIREMENTS.md`, `ROADMAP.md`, `STATE.md`, and now `codebase/`
- Key files: `PROJECT.md`, `ROADMAP.md`
- Subdirectories: `codebase/`, `research/`

## Key File Locations

**Entry Points:**
- `backend/app/main.py` - FastAPI application entry point
- `frontend/src/main.tsx` - React application entry point
- `backend/scripts/init_db.py` - migration/bootstrap entry point
- `start-dev.ps1` - local orchestration helper

**Configuration:**
- `.env.example` - sample backend env contract
- `backend/app/core/config.py` - typed settings loader
- `frontend/tsconfig.json` - TypeScript compiler settings and `@/*` alias
- `frontend/tailwind.config.ts` - design tokens and Tailwind config
- `docker-compose.yml` - local Postgres container config

**Core Logic:**
- `backend/app/services/chat.py` - main chat orchestration
- `backend/app/services/documents.py` - upload, ingest, delete, move, status streaming
- `backend/app/services/retrieval.py` - hybrid retrieval and reranking
- `backend/app/services/knowledge_base.py` - filesystem-like KB tool primitives
- `backend/app/services/explorer_agent.py` - KB explorer tool loop

**Testing:**
- `backend/tests/test_prd_smoke.py` - automated smoke coverage
- `tests/manual-smoke-checklist.md` - manual verification steps

**Documentation:**
- `README.md` - repo overview and local setup
- `PRD.md` - feature/product scope from the masterclass
- `.planning/PROJECT.md` - current project scope inside GSD

## Naming Conventions

**Files:**
- Backend Python modules use `snake_case.py` such as `workspace_sql.py` and `document_parser_ocr.py`
- React pages use `PascalCase.tsx` such as `AuthPage.tsx` and `DashboardPage.tsx`
- Frontend hooks use `use-*.tsx`, for example `use-auth.tsx`
- SQL migrations are numeric-prefixed and ordered: `001_init.sql`, `008_knowledge_base_explorer.sql`

**Directories:**
- Backend directories are noun-based and lowercase: `api/`, `db/`, `schemas/`, `services/`
- Frontend directories are lowercase feature buckets: `api/`, `hooks/`, `lib/`, `pages/`

**Special Patterns:**
- `__init__.py` marks Python packages throughout `backend/app/`
- UI primitives live in `frontend/src/components/ui/`
- No dedicated frontend feature folders beyond the large page files yet

## Where to Add New Code

**New Backend Route:**
- Definition: `backend/app/api/`
- Business logic: `backend/app/services/`
- Request/response models: `backend/app/schemas/`
- Persistence changes: `backend/migrations/` and `backend/app/db/models.py`

**New Retrieval or Agent Tool:**
- Primary code: `backend/app/services/`
- If it needs an HTTP surface: wire it from `backend/app/api/`
- Tests: extend `backend/tests/test_prd_smoke.py` or add a new backend test module

**New Frontend Feature:**
- API contract changes: `frontend/src/api/client.ts` and `frontend/src/api/types.ts`
- Screen-level behavior: `frontend/src/pages/`
- Shared styling primitive: `frontend/src/components/ui/`
- Shared helper: `frontend/src/lib/`

**New Test Coverage:**
- Backend automated coverage: `backend/tests/`
- Frontend automated coverage: no established location yet; introduce a test runner first, then keep tests near `frontend/src/` or under a new `frontend/tests/`

## Special Directories

**backend/uploads/**
- Purpose: Runtime file storage for uploaded source documents
- Source: created and managed by `backend/app/services/documents.py`
- Committed: only `.gitkeep`; actual uploads are gitignored

**.dev-logs/**
- Purpose: Local runtime logs from developer scripts
- Source: local runs, not application logic
- Committed: effectively local artifact territory; not part of the runtime contract

**.planning/codebase/**
- Purpose: Generated codebase map for GSD
- Source: this mapping workflow
- Committed: yes, intended reference material

---
*Structure analysis: 2026-03-28*
*Update when directory structure changes*
