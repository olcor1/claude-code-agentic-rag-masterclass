ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS extracted_metadata JSONB;

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS metadata_schema_version INTEGER;

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS metadata_status VARCHAR(32) NOT NULL DEFAULT 'not_started';

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS metadata_error TEXT;

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS metadata_extracted_at TIMESTAMPTZ;

UPDATE documents
SET metadata_status = 'not_started'
WHERE metadata_status IS NULL;

CREATE INDEX IF NOT EXISTS documents_extracted_metadata_gin_idx ON documents USING GIN (extracted_metadata);

CREATE INDEX IF NOT EXISTS documents_metadata_status_idx ON documents (metadata_status);
