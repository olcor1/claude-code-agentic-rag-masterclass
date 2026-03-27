CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS ingestion_jobs (
    id UUID PRIMARY KEY,
    document_id UUID NOT NULL UNIQUE REFERENCES documents(id) ON DELETE CASCADE,
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    error_message TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ingestion_jobs_document_id_idx ON ingestion_jobs (document_id);

ALTER TABLE documents
    ALTER COLUMN status SET DEFAULT 'queued';

UPDATE documents
SET status = CASE
    WHEN status = 'processed' THEN 'completed'
    WHEN status = 'uploaded' THEN 'queued'
    ELSE status
END;

INSERT INTO ingestion_jobs (
    id,
    document_id,
    status,
    error_message,
    started_at,
    completed_at,
    created_at,
    updated_at
)
SELECT
    gen_random_uuid(),
    documents.id,
    documents.status,
    documents.error_message,
    CASE
        WHEN documents.status IN ('processing', 'completed', 'failed') THEN documents.updated_at
        ELSE NULL
    END,
    CASE
        WHEN documents.status IN ('completed', 'failed') THEN documents.updated_at
        ELSE NULL
    END,
    documents.created_at,
    documents.updated_at
FROM documents
WHERE NOT EXISTS (
    SELECT 1
    FROM ingestion_jobs
    WHERE ingestion_jobs.document_id = documents.id
);
