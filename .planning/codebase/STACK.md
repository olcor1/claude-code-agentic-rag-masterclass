# Technology Stack

**Analysis Date:** 2026-03-28

## Languages

**Primary:**
- Python 3.x - Backend application code under `backend/app/`, migration bootstrap in `backend/scripts/init_db.py`, and smoke tests in `backend/tests/test_prd_smoke.py`
- TypeScript 5.9 - Frontend SPA code under `frontend/src/`

**Secondary:**
- SQL - PostgreSQL schema and feature evolution in `backend/migrations/*.sql`
- CSS/Tailwind utility classes - Frontend styling in `frontend/src/index.css` and inline class strings
- PowerShell - Local developer automation in `start-dev.ps1`

## Runtime

**Environment:**
- Python ASGI application via FastAPI and `uvicorn[standard]` from `backend/requirements.txt`
- Browser-based React SPA bundled by Vite from `frontend/package.json`
- PostgreSQL 16 + pgvector via `docker-compose.yml`
- Optional OCR runtime requirements such as Tesseract CLI for scanned PDFs via `backend/app/services/document_parser_ocr.py`

**Package Manager:**
- Python packages installed from `backend/requirements.txt` into a local virtualenv; no `pyproject.toml` or Poetry config is present
- npm for the frontend, with lockfile `frontend/package-lock.json`

## Frameworks

**Core:**
- FastAPI 0.116.1 - HTTP API, dependency injection, and SSE endpoints in `backend/app/main.py` and `backend/app/api/*.py`
- SQLAlchemy 2.0.43 - ORM and query layer in `backend/app/db/models.py` and `backend/app/db/session.py`
- React 19.1.1 - Frontend UI in `frontend/src/App.tsx` and `frontend/src/pages/*.tsx`
- Vite 7.1.3 - Frontend dev server and build pipeline in `frontend/package.json`
- Tailwind CSS 3.4.17 - Design tokens and utility classes in `frontend/tailwind.config.ts`

**Testing:**
- Python `unittest` - Smoke/integration coverage in `backend/tests/test_prd_smoke.py`
- Manual checklist - Browser and ingestion verification in `tests/manual-smoke-checklist.md`

**Build/Dev:**
- TypeScript 5.9.2 - Type checking via `frontend/package.json`
- PostCSS + Autoprefixer - Tailwind processing in `frontend/postcss.config.js`
- Docker Compose - Local database bootstrap in `docker-compose.yml`

## Key Dependencies

**Critical:**
- `openai==1.99.9` - Chat completions, metadata extraction, workspace SQL generation, and sub-agent orchestration in `backend/app/services/chat.py`, `metadata.py`, `workspace_sql.py`, `sub_agents.py`, and `explorer_agent.py`
- `sqlalchemy==2.0.43` + `psycopg[binary]==3.2.13` - Database access and session management in `backend/app/db/session.py`
- `pgvector==0.3.6` - Vector similarity storage and retrieval in `backend/app/db/models.py` and `backend/app/services/retrieval.py`
- `docling==2.79.0` - Document parsing for PDF/DOCX/HTML flows in `backend/app/services/document_parser.py` and `document_parser_ocr.py`
- `presidio-analyzer`, `presidio-anonymizer`, and `spacy` - PII detection and anonymization in `backend/app/services/redaction.py`

**Infrastructure:**
- `langsmith==0.4.13` - Optional tracing wrapper in `backend/app/services/tracing.py`
- `bcrypt==5.0.0` + `pyjwt==2.10.1` - Password hashing and JWT auth in `backend/app/core/security.py`
- `clsx` + `tailwind-merge` - Frontend class composition in `frontend/src/lib/cn.ts`
- `lucide-react` - Frontend icon system in `frontend/src/pages/DashboardPage.tsx`

## Configuration

**Environment:**
- Root `.env` is the primary backend runtime config source, loaded by `backend/app/core/config.py`
- Sample backend variables live in `.env.example`; frontend API base URL is also exposed through `VITE_API_BASE_URL`
- Important runtime knobs include `DATABASE_URL`, `JWT_SECRET`, `LLM_BASE_URL`, `LLM_CHAT_MODEL`, `LLM_EMBED_MODEL`, `WEB_SEARCH_*`, `PDF_OCR_*`, and `LANGSMITH_*`
- Browser auth state is client-managed and stored in `localStorage` via `frontend/src/hooks/use-auth.tsx`

**Build:**
- `frontend/tsconfig.json` sets strict TypeScript mode and the `@/*` path alias
- `frontend/tailwind.config.ts` defines the custom color palette and fonts
- `docker-compose.yml` provisions local PostgreSQL + pgvector

## Platform Requirements

**Development:**
- Local PostgreSQL with pgvector, usually started through `docker compose up -d`
- Python environment capable of installing the backend requirements from `backend/requirements.txt`
- Node.js + npm for `frontend/package.json`
- A local or remote OpenAI-compatible chat and embeddings endpoint configured via `.env`
- Optional OCR tooling such as Tesseract when scanned PDFs need OCR fallback

**Production:**
- No production deployment manifests are committed
- The current codebase assumes one Python API host, one static/frontend host, and one PostgreSQL database
- README guidance suggests local-first development; any hosted deployment would need its own environment-variable and storage strategy

---
*Stack analysis: 2026-03-28*
*Update after major dependency changes*
