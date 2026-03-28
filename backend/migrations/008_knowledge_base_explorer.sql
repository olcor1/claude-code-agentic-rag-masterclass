CREATE TABLE IF NOT EXISTS folders (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    parent_id UUID REFERENCES folders(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    scope VARCHAR(16) NOT NULL DEFAULT 'private' CHECK (scope IN ('private', 'global')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS folders_user_id_idx ON folders (user_id);
CREATE INDEX IF NOT EXISTS folders_parent_id_idx ON folders (parent_id);
CREATE INDEX IF NOT EXISTS folders_scope_idx ON folders (scope);

CREATE UNIQUE INDEX IF NOT EXISTS folders_global_sibling_name_idx
ON folders (COALESCE(parent_id, '00000000-0000-0000-0000-000000000000'::uuid), lower(name))
WHERE scope = 'global';

CREATE UNIQUE INDEX IF NOT EXISTS folders_private_sibling_name_idx
ON folders (user_id, COALESCE(parent_id, '00000000-0000-0000-0000-000000000000'::uuid), lower(name))
WHERE scope = 'private';

CREATE OR REPLACE FUNCTION validate_folder_hierarchy()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    parent_scope TEXT;
    parent_owner UUID;
    creates_cycle BOOLEAN;
BEGIN
    IF NEW.parent_id IS NULL THEN
        RETURN NEW;
    END IF;

    IF NEW.id = NEW.parent_id THEN
        RAISE EXCEPTION 'Folder cannot be its own parent';
    END IF;

    SELECT folders.scope, folders.user_id
    INTO parent_scope, parent_owner
    FROM folders
    WHERE folders.id = NEW.parent_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Parent folder does not exist';
    END IF;

    IF parent_scope <> NEW.scope THEN
        RAISE EXCEPTION 'Folder scope must match parent folder scope';
    END IF;

    IF NEW.scope = 'private' AND parent_owner <> NEW.user_id THEN
        RAISE EXCEPTION 'Private folders can only be nested under folders owned by the same user';
    END IF;

    WITH RECURSIVE ancestors AS (
        SELECT id, parent_id
        FROM folders
        WHERE id = NEW.parent_id

        UNION ALL

        SELECT folders.id, folders.parent_id
        FROM folders
        INNER JOIN ancestors ON folders.id = ancestors.parent_id
    )
    SELECT EXISTS(SELECT 1 FROM ancestors WHERE id = NEW.id)
    INTO creates_cycle;

    IF creates_cycle THEN
        RAISE EXCEPTION 'Folder move would create a cycle';
    END IF;

    RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS folders_validate_hierarchy ON folders;
CREATE TRIGGER folders_validate_hierarchy
BEFORE INSERT OR UPDATE OF parent_id, scope, user_id ON folders
FOR EACH ROW
EXECUTE FUNCTION validate_folder_hierarchy();

ALTER TABLE documents
ADD COLUMN IF NOT EXISTS folder_id UUID,
ADD COLUMN IF NOT EXISTS full_markdown TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'documents_folder_id_fkey'
    ) THEN
        ALTER TABLE documents
        ADD CONSTRAINT documents_folder_id_fkey
        FOREIGN KEY (folder_id) REFERENCES folders(id) ON DELETE CASCADE;
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS documents_folder_id_idx ON documents (folder_id);

ALTER TABLE folders ENABLE ROW LEVEL SECURITY;
ALTER TABLE folders FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS folders_visible_select ON folders;
CREATE POLICY folders_visible_select
ON folders
FOR SELECT
USING (scope = 'global' OR user_id = current_app_user_id());

DROP POLICY IF EXISTS folders_owner_insert ON folders;
CREATE POLICY folders_owner_insert
ON folders
FOR INSERT
WITH CHECK (user_id = current_app_user_id());

DROP POLICY IF EXISTS folders_owner_update ON folders;
CREATE POLICY folders_owner_update
ON folders
FOR UPDATE
USING (user_id = current_app_user_id())
WITH CHECK (user_id = current_app_user_id());

DROP POLICY IF EXISTS folders_owner_delete ON folders;
CREATE POLICY folders_owner_delete
ON folders
FOR DELETE
USING (user_id = current_app_user_id());

DROP POLICY IF EXISTS documents_owner_select ON documents;
CREATE POLICY documents_owner_select
ON documents
FOR SELECT
USING (
    user_id = current_app_user_id()
    OR EXISTS (
        SELECT 1
        FROM folders
        WHERE folders.id = documents.folder_id
          AND folders.scope = 'global'
    )
);

DROP POLICY IF EXISTS documents_owner_insert ON documents;
CREATE POLICY documents_owner_insert
ON documents
FOR INSERT
WITH CHECK (
    user_id = current_app_user_id()
    AND (
        folder_id IS NULL
        OR EXISTS (
            SELECT 1
            FROM folders
            WHERE folders.id = documents.folder_id
              AND (
                  folders.scope = 'global'
                  OR folders.user_id = current_app_user_id()
              )
        )
    )
);

DROP POLICY IF EXISTS documents_owner_update ON documents;
CREATE POLICY documents_owner_update
ON documents
FOR UPDATE
USING (user_id = current_app_user_id())
WITH CHECK (
    user_id = current_app_user_id()
    AND (
        folder_id IS NULL
        OR EXISTS (
            SELECT 1
            FROM folders
            WHERE folders.id = documents.folder_id
              AND (
                  folders.scope = 'global'
                  OR folders.user_id = current_app_user_id()
              )
        )
    )
);

DROP POLICY IF EXISTS documents_owner_delete ON documents;
CREATE POLICY documents_owner_delete
ON documents
FOR DELETE
USING (user_id = current_app_user_id());

DROP POLICY IF EXISTS ingestion_jobs_owner_select ON ingestion_jobs;
CREATE POLICY ingestion_jobs_owner_select
ON ingestion_jobs
FOR SELECT
USING (
    EXISTS (
        SELECT 1
        FROM documents
        LEFT JOIN folders ON folders.id = documents.folder_id
        WHERE documents.id = ingestion_jobs.document_id
          AND (
              documents.user_id = current_app_user_id()
              OR folders.scope = 'global'
          )
    )
);

DROP POLICY IF EXISTS ingestion_jobs_owner_insert ON ingestion_jobs;
CREATE POLICY ingestion_jobs_owner_insert
ON ingestion_jobs
FOR INSERT
WITH CHECK (
    EXISTS (
        SELECT 1
        FROM documents
        WHERE documents.id = ingestion_jobs.document_id
          AND documents.user_id = current_app_user_id()
    )
);

DROP POLICY IF EXISTS ingestion_jobs_owner_update ON ingestion_jobs;
CREATE POLICY ingestion_jobs_owner_update
ON ingestion_jobs
FOR UPDATE
USING (
    EXISTS (
        SELECT 1
        FROM documents
        WHERE documents.id = ingestion_jobs.document_id
          AND documents.user_id = current_app_user_id()
    )
)
WITH CHECK (
    EXISTS (
        SELECT 1
        FROM documents
        WHERE documents.id = ingestion_jobs.document_id
          AND documents.user_id = current_app_user_id()
    )
);

DROP POLICY IF EXISTS ingestion_jobs_owner_delete ON ingestion_jobs;
CREATE POLICY ingestion_jobs_owner_delete
ON ingestion_jobs
FOR DELETE
USING (
    EXISTS (
        SELECT 1
        FROM documents
        WHERE documents.id = ingestion_jobs.document_id
          AND documents.user_id = current_app_user_id()
    )
);

DROP POLICY IF EXISTS document_chunks_owner_select ON document_chunks;
CREATE POLICY document_chunks_owner_select
ON document_chunks
FOR SELECT
USING (
    EXISTS (
        SELECT 1
        FROM documents
        LEFT JOIN folders ON folders.id = documents.folder_id
        WHERE documents.id = document_chunks.document_id
          AND (
              documents.user_id = current_app_user_id()
              OR folders.scope = 'global'
          )
    )
);

DROP POLICY IF EXISTS document_chunks_owner_insert ON document_chunks;
CREATE POLICY document_chunks_owner_insert
ON document_chunks
FOR INSERT
WITH CHECK (
    EXISTS (
        SELECT 1
        FROM documents
        WHERE documents.id = document_chunks.document_id
          AND documents.user_id = current_app_user_id()
    )
);

DROP POLICY IF EXISTS document_chunks_owner_update ON document_chunks;
CREATE POLICY document_chunks_owner_update
ON document_chunks
FOR UPDATE
USING (
    EXISTS (
        SELECT 1
        FROM documents
        WHERE documents.id = document_chunks.document_id
          AND documents.user_id = current_app_user_id()
    )
)
WITH CHECK (
    EXISTS (
        SELECT 1
        FROM documents
        WHERE documents.id = document_chunks.document_id
          AND documents.user_id = current_app_user_id()
    )
);

DROP POLICY IF EXISTS document_chunks_owner_delete ON document_chunks;
CREATE POLICY document_chunks_owner_delete
ON document_chunks
FOR DELETE
USING (
    EXISTS (
        SELECT 1
        FROM documents
        WHERE documents.id = document_chunks.document_id
          AND documents.user_id = current_app_user_id()
    )
);
