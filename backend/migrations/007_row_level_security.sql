CREATE OR REPLACE FUNCTION current_app_user_id()
RETURNS UUID
LANGUAGE sql
STABLE
AS $$
    SELECT NULLIF(current_setting('app.current_user_id', true), '')::uuid
$$;

CREATE OR REPLACE FUNCTION current_app_auth_bypass()
RETURNS BOOLEAN
LANGUAGE sql
STABLE
AS $$
    SELECT COALESCE(NULLIF(current_setting('app.auth_bypass', true), ''), 'false')::boolean
$$;

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE users FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS users_self_select ON users;
CREATE POLICY users_self_select
ON users
FOR SELECT
USING (id = current_app_user_id() OR current_app_auth_bypass());

DROP POLICY IF EXISTS users_self_insert ON users;
CREATE POLICY users_self_insert
ON users
FOR INSERT
WITH CHECK (id = current_app_user_id() OR current_app_auth_bypass());

DROP POLICY IF EXISTS users_self_update ON users;
CREATE POLICY users_self_update
ON users
FOR UPDATE
USING (id = current_app_user_id() OR current_app_auth_bypass())
WITH CHECK (id = current_app_user_id() OR current_app_auth_bypass());

DROP POLICY IF EXISTS users_self_delete ON users;
CREATE POLICY users_self_delete
ON users
FOR DELETE
USING (id = current_app_user_id() OR current_app_auth_bypass());

ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversations FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS conversations_owner_select ON conversations;
CREATE POLICY conversations_owner_select
ON conversations
FOR SELECT
USING (user_id = current_app_user_id());

DROP POLICY IF EXISTS conversations_owner_insert ON conversations;
CREATE POLICY conversations_owner_insert
ON conversations
FOR INSERT
WITH CHECK (user_id = current_app_user_id());

DROP POLICY IF EXISTS conversations_owner_update ON conversations;
CREATE POLICY conversations_owner_update
ON conversations
FOR UPDATE
USING (user_id = current_app_user_id())
WITH CHECK (user_id = current_app_user_id());

DROP POLICY IF EXISTS conversations_owner_delete ON conversations;
CREATE POLICY conversations_owner_delete
ON conversations
FOR DELETE
USING (user_id = current_app_user_id());

ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS messages_owner_select ON messages;
CREATE POLICY messages_owner_select
ON messages
FOR SELECT
USING (
    EXISTS (
        SELECT 1
        FROM conversations
        WHERE conversations.id = messages.conversation_id
          AND conversations.user_id = current_app_user_id()
    )
);

DROP POLICY IF EXISTS messages_owner_insert ON messages;
CREATE POLICY messages_owner_insert
ON messages
FOR INSERT
WITH CHECK (
    EXISTS (
        SELECT 1
        FROM conversations
        WHERE conversations.id = messages.conversation_id
          AND conversations.user_id = current_app_user_id()
    )
);

DROP POLICY IF EXISTS messages_owner_update ON messages;
CREATE POLICY messages_owner_update
ON messages
FOR UPDATE
USING (
    EXISTS (
        SELECT 1
        FROM conversations
        WHERE conversations.id = messages.conversation_id
          AND conversations.user_id = current_app_user_id()
    )
)
WITH CHECK (
    EXISTS (
        SELECT 1
        FROM conversations
        WHERE conversations.id = messages.conversation_id
          AND conversations.user_id = current_app_user_id()
    )
);

DROP POLICY IF EXISTS messages_owner_delete ON messages;
CREATE POLICY messages_owner_delete
ON messages
FOR DELETE
USING (
    EXISTS (
        SELECT 1
        FROM conversations
        WHERE conversations.id = messages.conversation_id
          AND conversations.user_id = current_app_user_id()
    )
);

ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS documents_owner_select ON documents;
CREATE POLICY documents_owner_select
ON documents
FOR SELECT
USING (user_id = current_app_user_id());

DROP POLICY IF EXISTS documents_owner_insert ON documents;
CREATE POLICY documents_owner_insert
ON documents
FOR INSERT
WITH CHECK (user_id = current_app_user_id());

DROP POLICY IF EXISTS documents_owner_update ON documents;
CREATE POLICY documents_owner_update
ON documents
FOR UPDATE
USING (user_id = current_app_user_id())
WITH CHECK (user_id = current_app_user_id());

DROP POLICY IF EXISTS documents_owner_delete ON documents;
CREATE POLICY documents_owner_delete
ON documents
FOR DELETE
USING (user_id = current_app_user_id());

ALTER TABLE ingestion_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE ingestion_jobs FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS ingestion_jobs_owner_select ON ingestion_jobs;
CREATE POLICY ingestion_jobs_owner_select
ON ingestion_jobs
FOR SELECT
USING (
    EXISTS (
        SELECT 1
        FROM documents
        WHERE documents.id = ingestion_jobs.document_id
          AND documents.user_id = current_app_user_id()
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

ALTER TABLE document_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_chunks FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS document_chunks_owner_select ON document_chunks;
CREATE POLICY document_chunks_owner_select
ON document_chunks
FOR SELECT
USING (
    EXISTS (
        SELECT 1
        FROM documents
        WHERE documents.id = document_chunks.document_id
          AND documents.user_id = current_app_user_id()
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
