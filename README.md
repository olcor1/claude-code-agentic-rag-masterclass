# Cloud Code Agentic RAG Masterclass

Build an agentic RAG application from scratch by collaborating with Claude Code. Follow along with our video series using the docs in this repo.

[![Claude Code RAG Masterclass](./video-thumbnail.png)](https://www.youtube.com/watch?v=xgPWCuqLoek)

[Watch the full video on YouTube](https://www.youtube.com/watch?v=xgPWCuqLoek)

## What This Is

A hands-on course where you collaborate with Claude Code to build a full-featured RAG system. You're not the one writing code—Claude is. Your job is to guide it, understand what you're building, and course-correct when needed.

**You don't need to know how to code.** You do need to be technically minded and willing to learn about APIs, databases, and system architecture.

## What You'll Build

- **Chat interface** with threaded conversations, streaming, tool calls, and subagent reasoning
- **Document ingestion** with drag-and-drop upload, multi-format parsing, delete controls, and processing status
- **Full RAG pipeline**: chunking, embedding, hybrid search, reranking
- **Agentic patterns**: text-to-SQL, web search, subagents with isolated context

## Tech Stack

| Layer | Tech |
|-------|------|
| Frontend | React, TypeScript, Tailwind, shadcn/ui, Vite |
| Backend | Python, FastAPI |
| Database | Supabase (Postgres + pgvector + Auth + Storage) |
| Doc Processing | Docling + native text fallbacks |
| AI Models | Local (LM Studio) or Cloud (OpenAI, OpenRouter) |
| Observability | LangSmith |

## The 8 Modules

1. **App Shell** — Auth, chat UI, managed RAG with OpenAI Responses API
2. **BYO Retrieval + Memory** — Ingestion, pgvector, switch to generic completions API
3. **Record Manager** — Content hashing, deduplication
4. **Metadata Extraction** — LLM-extracted metadata, filtered retrieval
5. **Multi-Format Support** — PDF, DOCX, HTML, Markdown via Docling
6. **Hybrid Search & Reranking** — Keyword + vector search, RRF, reranking
7. **Additional Tools** — Text-to-SQL, web search fallback
8. **Subagents** — Isolated context, document analysis delegation

## Getting Started

1. Clone this repo
2. Install [Claude Code](https://docs.anthropic.com/en/docs/claude-code)
3. Open in your IDE (Cursor, VS Code, etc.)
4. Run `claude` in the terminal
5. Use the `/onboard` command to get started

## Docs

- [PRD.md](./PRD.md) — What to build (the 8 modules in detail)
- [CLAUDE.md](./CLAUDE.md) — Context for Claude Code
- [PROGRESS.md](./PROGRESS.md) — Track your build progress

## Local Module 1 Scaffold

The repository now includes a local Module 1 implementation scaffold:

- `backend/` FastAPI API with JWT auth, multi-format document ingestion, document deletion, pgvector retrieval, SSE chat streaming, realtime ingestion status streams, and optional LangSmith tracing
- `frontend/` Vite + React client with auth, separate Chat/Ingestion interfaces, drag-and-drop upload, live document status updates, conversation list, and grounded chat UI
- `docker-compose.yml` for local PostgreSQL + pgvector
- `.env.example` plus `frontend/.env.example` for environment bootstrap
- Module 7 chat orchestration that can combine document retrieval, workspace text-to-SQL over a user-scoped SQLite snapshot, and optional web-search fallback with source attribution
- OCR fallback for scanned PDFs through Docling when the initial PDF extraction returns too little text
- Database bootstrap now provisions a non-bypass application role and the app connections `SET ROLE` into it so the Postgres RLS policies are actually enforced during runtime

### Run It

1. Copy `.env.example` to `.env` and set your local LLM endpoint values.
   Module 7 notes:
   - `SQL_TOOL_ROW_LIMIT` controls how many structured rows are passed into the final answer prompt.
   - `WEB_SEARCH_ENABLED` defaults to `true`; set it to `false` if you want to disable outbound web fallback.
   - `WEB_SEARCH_PROVIDER=duckduckgo_html` works without an API key.
   - `WEB_SEARCH_PROVIDER=tavily` requires `WEB_SEARCH_API_KEY`.
   OCR notes:
   - `PDF_OCR_ENABLED=true` enables automatic OCR fallback for low-text PDFs.
   - `PDF_OCR_ENGINE=tesseract_cli` expects the `tesseract` CLI to be installed and available on your PATH.
   - For French scanned PDFs, `PDF_OCR_LANGUAGES=fra,eng` is a reasonable starting point.
   - If you switch to `easyocr`, use engine-appropriate language codes such as `fr,en`.
2. Start PostgreSQL with `docker compose up -d`.
3. Create a backend venv, install `backend/requirements.txt` for Docling-backed parsing support, then run `python backend/scripts/init_db.py`.
   This applies the schema migrations and provisions the non-bypass `rag_app` database role used for RLS-enforced app traffic.
4. Start the backend from `backend/` with `uvicorn app.main:app --reload`.
5. Install frontend dependencies in `frontend/` and run `npm run dev`.

### Test Account

Use this local account for manual smoke testing once the app is running:

- Email: `test@test.com`
- Password: `Test123456!`

Current confirmed local test password: `Test123456!`

Python note: the current OpenAI SDK emits an upstream compatibility warning on Python `3.14`, so Python `3.12` or `3.13` is the safer local target if you want a quieter runtime.

## Join the Community

If you want to connect with hundreds of builders creating production-grade AI and RAG systems, join us in [The AI Automators community](https://www.theaiautomators.com/). Share your progress, get help when you're stuck, and see what others are building.
