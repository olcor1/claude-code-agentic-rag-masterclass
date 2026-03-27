ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS source_key TEXT;

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64);

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS hash_algorithm VARCHAR(32) NOT NULL DEFAULT 'sha256';

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 0;

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS last_ingestion_result VARCHAR(32);

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS pending_filename VARCHAR(255);

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS pending_storage_path VARCHAR(500);

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS pending_content_hash VARCHAR(64);

UPDATE documents
SET source_key = filename
WHERE source_key IS NULL;

WITH ranked AS (
    SELECT
        id,
        source_key,
        ROW_NUMBER() OVER (
            PARTITION BY user_id, source_key
            ORDER BY
                CASE WHEN status = 'completed' THEN 0 ELSE 1 END,
                updated_at DESC,
                created_at DESC,
                id DESC
        ) AS duplicate_rank
    FROM documents
    WHERE source_key IS NOT NULL
)
UPDATE documents
SET source_key = ranked.source_key || '::' || documents.id::text
FROM ranked
WHERE documents.id = ranked.id
  AND ranked.duplicate_rank > 1;

UPDATE documents
SET hash_algorithm = 'sha256'
WHERE hash_algorithm IS NULL OR hash_algorithm = '';

UPDATE documents
SET version = CASE
    WHEN status = 'completed' THEN GREATEST(version, 1)
    ELSE 0
END;

UPDATE documents
SET last_ingestion_result = 'new'
WHERE last_ingestion_result IS NULL
  AND status = 'completed';

CREATE UNIQUE INDEX IF NOT EXISTS documents_user_source_key_uidx ON documents (user_id, source_key);

CREATE INDEX IF NOT EXISTS documents_user_content_hash_idx ON documents (user_id, content_hash);
