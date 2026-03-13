# Module 1 Manual Smoke Checklist

1. Start PostgreSQL with pgvector and apply migrations via `python backend/scripts/init_db.py`.
2. Register a user through `POST /auth/register`, then confirm `GET /auth/me` returns that user with the bearer token.
3. Upload a `.txt` or `.md` file and poll `GET /documents/{id}/status` until it reaches `processed`.
4. Inspect `document_chunks` in Postgres and verify embeddings exist for the uploaded document.
5. Create a conversation, send a streamed message, and confirm the assistant answer includes citations like `[1]`.
6. When LangSmith env vars are set, confirm traces appear for ingestion, embedding, retrieval, and chat generation.
