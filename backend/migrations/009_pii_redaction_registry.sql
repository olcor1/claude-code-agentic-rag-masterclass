CREATE TABLE IF NOT EXISTS conversation_pii_registry_entries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    entity_type VARCHAR(64) NOT NULL,
    normalized_value VARCHAR(512) NOT NULL,
    real_value TEXT NOT NULL,
    surrogate_value TEXT NOT NULL,
    cluster_key VARCHAR(128),
    profile JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT conversation_pii_registry_entries_unique_value
        UNIQUE (conversation_id, entity_type, normalized_value)
);

CREATE INDEX IF NOT EXISTS ix_conversation_pii_registry_entries_conversation_id
    ON conversation_pii_registry_entries (conversation_id);

CREATE INDEX IF NOT EXISTS ix_conversation_pii_registry_entries_user_id
    ON conversation_pii_registry_entries (user_id);

ALTER TABLE conversation_pii_registry_entries ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS conversation_pii_registry_entries_policy ON conversation_pii_registry_entries;
CREATE POLICY conversation_pii_registry_entries_policy
    ON conversation_pii_registry_entries
    USING (
        current_setting('app.auth_bypass', true) = 'true'
        OR user_id = current_setting('app.current_user_id', true)::uuid
    )
    WITH CHECK (
        current_setting('app.auth_bypass', true) = 'true'
        OR user_id = current_setting('app.current_user_id', true)::uuid
    );
