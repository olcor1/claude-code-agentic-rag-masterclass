# Codebase Concerns

**Analysis Date:** 2026-03-28

## Tech Debt

**Frontend dashboard orchestration in one file:**
- Files: `frontend/src/pages/DashboardPage.tsx`
- Issue: The main authenticated screen is 1610 lines and mixes chat UX, ingestion UX, folder management, metadata filters, SSE handling, citations, and agent-trace rendering
- Why: New capabilities accumulated directly inside the primary workspace page
- Impact: UI changes are high-risk and difficult to test in isolation
- Fix approach: Split into focused hooks/components such as chat pane, folder tree, ingestion panel, citation list, and trace viewer

**Backend chat orchestration in one service:**
- Files: `backend/app/services/chat.py`
- Issue: A single 813-line module owns retrieval, workspace SQL routing, explorer delegation, sub-agent dispatch, web fallback, prompt construction, SSE, and persistence
- Why: Feature growth stayed inside one orchestration file
- Impact: Small behavior changes can regress unrelated chat flows
- Fix approach: Separate routing heuristics, prompt building, tool execution, and SSE serialization into smaller modules

**Duplicate document parser entry points:**
- Files: `backend/app/services/document_parser.py`, `backend/app/services/document_parser_ocr.py`, `backend/app/services/documents.py`
- Issue: Two parser implementations exist, but runtime ingestion currently imports only `document_parser_ocr.py`
- Why: OCR-capable parsing was added without removing the earlier parser module
- Impact: Future edits can land in the wrong parser path and silently do nothing in production
- Fix approach: Consolidate on one parser module or clearly mark the legacy one as deprecated/non-runtime

**README and runtime implementation drift:**
- Files: `README.md`, `backend/app/services/auth.py`, `backend/app/services/documents.py`, `backend/app/db/session.py`
- Issue: Top-level docs still describe Supabase Auth/Storage patterns, while the running code uses local JWT auth, direct PostgreSQL access, and filesystem uploads
- Why: The local scaffold evolved faster than the overview documentation
- Impact: New contributors can make incorrect architecture assumptions before reading the code
- Fix approach: Refresh `README.md` so auth, storage, and setup instructions match the current implementation

## Known Bugs

**Local PostgreSQL port mismatch:**
- Files: `.env.example`, `backend/app/core/config.py`, `docker-compose.yml`
- Symptoms: The sample/default DB URL targets `localhost:55432`, but Docker Compose exposes `55632`
- Trigger: Fresh local setup that copies `.env.example` and starts the compose stack without manual edits
- Workaround: Change `DATABASE_URL` to `localhost:55632` or change the compose port mapping
- Root cause: Environment defaults and local infra config drifted apart
- Blocked by: Nothing

## Security Considerations

**JWT stored in localStorage:**
- Files: `frontend/src/hooks/use-auth.tsx`, `frontend/src/lib/auth-session.ts`, `backend/app/core/security.py`
- Risk: Any XSS issue in the frontend would expose bearer tokens
- Current mitigation: The app is positioned as a local-first workspace and clears sessions on 401 events
- Recommendations: Move to httpOnly cookies and add stronger browser hardening if this app is exposed beyond trusted local usage

**Web fallback can transmit raw prompt text externally:**
- Files: `backend/app/services/chat.py`, `backend/app/services/web_search.py`, `backend/app/services/redaction.py`
- Risk: When redaction is disabled, web fallback may send sensitive prompt text to DuckDuckGo or Tavily
- Current mitigation: `WEB_SEARCH_ENABLED` can be disabled and redaction can anonymize outgoing queries
- Recommendations: Require explicit opt-in for web fallback on sensitive workspaces or enable redaction by default before external calls

## Performance Bottlenecks

**Per-request workspace SQL snapshot rebuild:**
- Files: `backend/app/services/workspace_sql.py`
- Problem: Each eligible analytics question rebuilds an in-memory SQLite mirror from the current Postgres workspace state
- Measurement: No benchmark is committed; cost grows with document, conversation, and message counts
- Cause: The design favors a constrained SQLite query surface over querying PostgreSQL directly
- Improvement path: Cache per-user snapshots or route deterministic analytics straight to PostgreSQL

**Polling-based document status streaming:**
- Files: `backend/app/services/documents.py`, `backend/app/api/documents.py`
- Problem: `stream_document_status()` polls the database with `time.sleep()` for each subscriber
- Measurement: No benchmark is committed; each active document stream keeps a polling loop and DB refresh cycle alive
- Cause: Simple SSE implementation without pub/sub or push notifications
- Improvement path: Introduce an event bus, pub/sub, or DB notification mechanism for ingestion updates

## Fragile Areas

**Ingestion state transitions and cleanup:**
- Files: `backend/app/services/documents.py`
- Why fragile: File cleanup, pending upload promotion, chunk replacement, metadata state, and ingestion job state all change together
- Common failures: Re-upload races, wrong final status after background failure, orphaned pending files, or chunk replacement regressions
- Safe modification: Add regression coverage first and preserve the current update order for `Document` + `IngestionJob`
- Test coverage: Good smoke coverage exists, but the logic remains tightly coupled

**Explorer/sub-agent orchestration stack:**
- Files: `backend/app/services/explorer_agent.py`, `backend/app/services/sub_agents.py`, `backend/app/services/knowledge_base.py`
- Why fragile: LLM tool loops, heuristic fallbacks, path resolution, and delegated analysis all interact
- Common failures: Tool-call drift, duplicated analyses, weak path matching, or fallback behavior masking model issues
- Safe modification: Keep tool names/contracts stable and test with real knowledge-base fixtures before changing routing heuristics
- Test coverage: Primitive KB tools are covered; the full explorer loop is not directly exercised

## Scaling Limits

**In-process background ingestion:**
- Files: `backend/app/api/documents.py`, `backend/app/services/documents.py`
- Current capacity: Limited to the FastAPI process and machine running the app
- Limit: Long-running parsing/embedding jobs compete with normal request handling and do not survive process restarts cleanly
- Symptoms at limit: Slower uploads, stuck jobs, and uneven throughput under concurrent ingest
- Scaling path: Move ingestion to a dedicated worker queue/service

**Single-node local file storage:**
- Files: `backend/uploads/`, `backend/app/services/documents.py`
- Current capacity: Local disk on one machine
- Limit: No shared object storage or cross-node synchronization
- Symptoms at limit: Disk growth and non-portable runtime state between environments
- Scaling path: Move uploads to object storage if the app needs hosted or multi-machine deployment

## Dependencies at Risk

**DuckDuckGo HTML scraping:**
- Files: `backend/app/services/web_search.py`
- Risk: HTML parser logic depends on DuckDuckGo page structure
- Impact: Web fallback can silently degrade when markup changes
- Migration plan: Prefer Tavily or another API-backed provider for production-grade fallback

**Python 3.14 local runtime drift:**
- Files: `README.md`, local `backend/venv/` artifacts, `.dev-logs/`
- Risk: The README explicitly warns that the OpenAI SDK is noisier on Python 3.14, but local artifacts show 3.14 has been used
- Impact: Inconsistent developer environments and avoidable compatibility/debug noise
- Migration plan: Standardize local setup on Python 3.12 or 3.13 until the warning is no longer relevant

## Missing Critical Features

**Automated frontend test harness:**
- Problem: `frontend/package.json` defines `dev`, `build`, `preview`, and `typecheck`, but no test runner
- Current workaround: Manual verification through `tests/manual-smoke-checklist.md`
- Blocks: Safe refactors of `frontend/src/pages/DashboardPage.tsx` and browser SSE flows
- Implementation complexity: Medium

**Repository CI pipeline:**
- Problem: No CI workflow is committed for backend smoke tests or frontend type checks
- Current workaround: Run everything manually on a local machine
- Blocks: Consistent verification across branches and contributors
- Implementation complexity: Low to Medium

## Test Coverage Gaps

**Browser-level auth/chat/ingestion flows:**
- What's not tested: React auth flow, folder tree interactions, SSE rendering, citation chips, and metadata filter UX
- Risk: Frontend regressions can ship while backend smoke tests still pass
- Priority: High
- Difficulty to test: Medium; requires a frontend runner plus API harness

**Explorer agent tool loop:**
- What's not tested: End-to-end `run_explorer_sub_agent()` behavior across model tool calls and fallback summaries
- Risk: KB explorer behavior can regress even when `grep`, `glob`, and `read` helpers stay green
- Priority: Medium
- Difficulty to test: Medium; requires deterministic LLM/tool-call fixtures

---
*Concerns audit: 2026-03-28*
*Update as issues are fixed or new ones discovered*
