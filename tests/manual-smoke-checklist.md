# Module 5 Manual Smoke Checklist

Test account for the local app:

- Email: `test@test.com`
- Password: `Test123456!`

1. Start PostgreSQL with pgvector and apply migrations via `python backend/scripts/init_db.py`.
2. Sign in with the test account above. If it does not exist yet, register it through `POST /auth/register`, then confirm `GET /auth/me` returns that user with the bearer token.
3. Upload one file from each supported format you want to validate: `.txt`, `.md`, `.html`, `.docx`, and `.pdf`. Confirm each successful response contains a non-null `ingestion_job`, `source_key`, `content_hash` or `pending` processing state, and `version` metadata on the document payload.
4. Subscribe to `GET /documents/{id}/status/stream` or watch the Ingestion view until the document reaches `completed`, then verify the document row shows `last_ingestion_result = "new"` and `version = 1`.
5. Confirm the completed document also includes `metadata_status = "completed"` plus an `extracted_metadata` payload with `document_type`, `topics`, `entities`, or `language` fields populated when the model can infer them.
6. Re-upload the exact same file and confirm the response returns the same document id, reports `last_ingestion_result = "unchanged"`, and does not enqueue a new ingestion job.
7. Edit the file contents, upload it again, and confirm the response still returns the same document id while the ingestion job moves through `queued -> processing -> completed`.
8. After the changed re-upload completes, confirm the document `version` increments, `last_ingestion_result = "updated"`, the `document_chunks` rows reflect only the new content, and the extracted metadata refreshes to match the new document text.
9. Upload a malformed or unsupported file and confirm the API rejects it with a clear parser error without leaving a document row or orphaned upload behind.
10. Force a re-index failure after at least one successful ingest, then confirm the document remains retrievable with its last successful chunks while the ingestion job surfaces a `failed` status and error payload.
11. Delete a completed document from the dashboard and confirm the document row disappears, retrieval no longer cites it, and its stored file is removed from `backend/uploads`.
12. Attempt to delete a `queued` or `processing` document and confirm the API returns `409 Conflict` with a clear message.
13. Delete a failed document and confirm any staged pending upload file is removed as part of cleanup.
14. Create a conversation, send a streamed message with no filters, and confirm the assistant answer includes citations like `[1]` from the currently active document content.
15. Apply a metadata filter in the UI, send a question, and confirm retrieval only cites documents whose extracted metadata matches the selected filter values.
16. Apply a filter that should exclude every document and confirm the UI reports that no supporting documents were found in the current filter scope.
17. Ask a question about text removed in the updated upload and confirm retrieval no longer cites the removed content.
18. Ask a structured workspace question such as `How many completed documents do I have by document type?` and confirm the answer cites `[SQL1]` with a hoverable SQL preview rather than only document citations.
19. Ask a mixed question such as `Which languages exist in my uploaded documents, and what do the docs say about embeddings?` and confirm the answer can combine `[SQL1]` with normal document citations like `[1]`.
20. With `WEB_SEARCH_ENABLED=false`, ask an out-of-knowledge-base question and confirm the assistant says evidence is insufficient rather than fabricating a web answer.
21. With `WEB_SEARCH_ENABLED=true`, ask an out-of-knowledge-base question such as `What is the latest OpenAI API release?` and confirm the answer cites `[WEB1]` style sources with clickable result chips.
22. Temporarily misconfigure the web-search provider or disconnect the network, repeat the same out-of-knowledge-base question, and confirm the assistant reports the fallback was unavailable instead of silently failing.
23. When LangSmith env vars are set, confirm traces appear for ingestion, embedding, metadata extraction, retrieval, workspace SQL, optional web search, and final chat generation.
24. With `PDF_OCR_ENABLED=true`, upload a scanned or image-only PDF and confirm it reaches `completed` instead of failing with `The uploaded document does not contain any text to chunk`.
25. For a French scanned PDF, set `PDF_OCR_LANGUAGES=fra,eng`, re-upload the file, and confirm retrieval can cite text that only exists in the scanned pages.
26. Temporarily disable OCR or remove the OCR backend, upload the same scanned PDF again, and confirm the API returns a clear parser or dependency error instead of silently indexing an empty document.
