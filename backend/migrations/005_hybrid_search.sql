CREATE INDEX IF NOT EXISTS document_chunks_embedding_cosine_idx
ON document_chunks
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

CREATE INDEX IF NOT EXISTS document_chunks_content_fts_idx
ON document_chunks
USING GIN (to_tsvector('simple', content));
