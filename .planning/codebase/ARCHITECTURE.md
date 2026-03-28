# Architecture

**Analysis Date:** 2026-03-28

## Pattern Overview

**Overall:** Local-first full-stack monolith with a React SPA frontend, a FastAPI backend, PostgreSQL/pgvector persistence, and backend-managed agentic orchestration

**Key Characteristics:**
- Thin HTTP route layer over service modules in `backend/app/api/*.py`
- Stateful product data lives in PostgreSQL, but request handling stays stateless outside the database and local upload directory
- SSE is the main live-update mechanism for both chat streaming and ingestion-job status
- Agentic behavior is implemented as backend service orchestration, not as a separate worker service or external orchestration platform
- Row-level visibility is enforced by setting per-session Postgres variables in `backend/app/db/session.py`

## Layers

**Frontend Presentation Layer:**
- Purpose: Render auth, chat, ingestion, folder tree, citations, and agent traces
- Contains: React pages and small UI primitives in `frontend/src/pages/*.tsx` and `frontend/src/components/ui/*.tsx`
- Depends on: Frontend data layer and Tailwind styling
- Used by: Browser users through `frontend/src/main.tsx`

**Frontend Data/Auth Layer:**
- Purpose: Manage bearer token state and call backend endpoints
- Contains: `frontend/src/api/client.ts`, `frontend/src/api/types.ts`, `frontend/src/hooks/use-auth.tsx`, and `frontend/src/lib/auth-session.ts`
- Depends on: Fetch API and browser `localStorage`
- Used by: React pages such as `frontend/src/pages/AuthPage.tsx` and `frontend/src/pages/DashboardPage.tsx`

**API Layer:**
- Purpose: Map HTTP requests to application services
- Contains: Route modules in `backend/app/api/auth.py`, `conversations.py`, `documents.py`, and `folders.py`
- Depends on: FastAPI dependency injection, schemas, and service functions
- Used by: Frontend `fetch` calls and SSE subscriptions

**Service/Orchestration Layer:**
- Purpose: Implement business logic for auth, ingestion, retrieval, chat, KB tools, redaction, tracing, and web fallback
- Contains: `backend/app/services/*.py`
- Depends on: ORM models, provider clients, and utility modules
- Used by: API layer and background task entry points

**Persistence Layer:**
- Purpose: Model and query durable workspace data
- Contains: SQLAlchemy models in `backend/app/db/models.py`, session wiring in `backend/app/db/session.py`, and migrations in `backend/migrations/*.sql`
- Depends on: PostgreSQL + pgvector
- Used by: Nearly every backend service

## Data Flow

**Authentication Request:**

1. The browser submits credentials from `frontend/src/pages/AuthPage.tsx`
2. `frontend/src/api/client.ts` sends `POST /auth/register` or `POST /auth/login`
3. `backend/app/api/auth.py` calls `backend/app/services/auth.py`
4. Passwords are hashed/verified and JWTs are created in `backend/app/core/security.py`
5. The frontend stores the bearer token in `localStorage` through `frontend/src/hooks/use-auth.tsx`

**Document Ingestion:**

1. The user uploads a file from the ingestion view in `frontend/src/pages/DashboardPage.tsx`
2. `frontend/src/api/client.ts` posts multipart form data to `/documents/upload`
3. `backend/app/api/documents.py` saves the file and calls `prepare_document_upload()` in `backend/app/services/documents.py`
4. FastAPI `BackgroundTasks` runs `process_document()` for parsing, chunking, embedding, metadata extraction, and chunk persistence
5. The frontend subscribes to `/documents/{id}/status/stream` and updates local state from SSE events

**Chat Request:**

1. The dashboard posts to `/conversations/{id}/messages/stream`
2. `backend/app/services/chat.py` persists the user message, creates an agent trace, and runs hybrid retrieval
3. The same service may optionally invoke workspace SQL, KB explorer tools, document sub-agents, redaction, and web fallback
4. Prompt assembly happens inside `chat.py`, then tokens stream back as SSE
5. The final assistant message, citations, and trace are persisted to `messages`

**Knowledge-Base Explorer Request:**

1. `chat.py` detects filesystem-like requests through `looks_like_explorer_request()`
2. `backend/app/services/explorer_agent.py` runs a tool loop over `ls`, `tree`, `grep`, `glob`, `read`, and `analyze_document`
3. Tool primitives come from `backend/app/services/knowledge_base.py`
4. Deep file synthesis is delegated to `backend/app/services/sub_agents.py`

**State Management:**
- Frontend state is local component state plus auth token in `localStorage`
- Backend state is database-backed, with transient upload files in `backend/uploads/`
- Request-scoped auth/RLS context is injected into SQLAlchemy sessions in `backend/app/db/session.py`

## Key Abstractions

**Workspace Entities:**
- Purpose: Model the durable user workspace
- Examples: `User`, `Conversation`, `Message`, `Folder`, `Document`, `IngestionJob`, `DocumentChunk` in `backend/app/db/models.py`
- Pattern: ORM entities with relationships and Pydantic response schemas

**RetrievedChunk:**
- Purpose: Carry merged retrieval metadata from vector, keyword, RRF, and reranking stages
- Examples: `backend/app/services/retrieval.py`
- Pattern: dataclass used as a rich retrieval result object

**Agent Trace:**
- Purpose: Represent visible agent reasoning and tool steps for the UI
- Examples: `backend/app/services/agent_trace.py` and `frontend/src/api/types.ts`
- Pattern: nested JSON tree persisted on `Message.agent_trace`

**Explorer/Sub-Agent Results:**
- Purpose: Encapsulate delegated document or KB exploration outputs
- Examples: `ExplorerResult` in `backend/app/services/explorer_agent.py`, `SubAgentAnalysis` in `backend/app/services/sub_agents.py`
- Pattern: dataclass payloads fed back into the main chat answer

## Entry Points

**Backend API:**
- Location: `backend/app/main.py`
- Triggers: ASGI server startup and incoming HTTP requests
- Responsibilities: create the FastAPI app, configure CORS, warm tracing/redaction resources, and register routers

**Frontend App:**
- Location: `frontend/src/main.tsx`
- Triggers: Vite/browser boot
- Responsibilities: mount the React root and render `frontend/src/App.tsx`

**Database Bootstrap:**
- Location: `backend/scripts/init_db.py`
- Triggers: manual developer setup
- Responsibilities: apply SQL migrations and provision the restricted application role

**Local Infrastructure:**
- Location: `docker-compose.yml`
- Triggers: local Docker startup
- Responsibilities: run PostgreSQL with pgvector

## Error Handling

**Strategy:** Services handle domain and provider errors close to the source, then expose either `HTTPException`, persistent job status, or SSE status events

**Patterns:**
- Upload/parser failures are translated to user-facing HTTP errors in `backend/app/services/documents.py`
- Long-running ingestion failures are captured on `Document` and `IngestionJob` records instead of crashing the request path
- Chat orchestration failures are surfaced as trace/status updates where possible; the service tries to degrade through tool-selection heuristics rather than fail early
- Frontend HTTP helpers centralize non-OK handling in `frontend/src/api/client.ts`

## Cross-Cutting Concerns

**Authentication:**
- JWTs are created in `backend/app/core/security.py`
- Request user resolution happens in `backend/app/services/auth.py`
- Postgres visibility is reinforced by session context in `backend/app/db/session.py`

**Validation:**
- FastAPI request/response schemas live in `backend/app/schemas/*.py`
- Frontend payload typing lives in `frontend/src/api/types.ts`

**Tracing and Privacy:**
- Optional LangSmith tracing wraps major chains in `backend/app/services/tracing.py`
- PII redaction/deanonymization flows are implemented in `backend/app/services/redaction.py`

**Search and Ranking:**
- Hybrid retrieval is implemented in `backend/app/services/retrieval.py`
- KB filesystem-like search lives in `backend/app/services/knowledge_base.py`

---
*Architecture analysis: 2026-03-28*
*Update when major patterns change*
