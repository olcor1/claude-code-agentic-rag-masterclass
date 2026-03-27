export type User = {
  id: string;
  email: string;
  created_at: string;
};

export type TokenResponse = {
  access_token: string;
  token_type: string;
};

export type Citation = {
  index: number;
  sourceType?: "document" | "sql" | "web";
  chunkId?: string;
  documentId?: string;
  filename?: string;
  label?: string;
  title?: string;
  url?: string;
  domain?: string;
  query?: string;
  rowCount?: number;
  columns?: string[];
  excerpt: string;
  matchType?: string;
  retrievalMethods?: string[];
  vectorDistance?: number | null;
  keywordScore?: number | null;
  rrfScore?: number | null;
  rerankScore?: number | null;
};

export type AgentTraceStep = {
  id: string;
  title: string;
  kind: string;
  toolName?: string | null;
  status: string;
  summary?: string | null;
  inputSummary?: string | null;
  outputSummary?: string | null;
  citations?: Citation[];
};

export type AgentTrace = {
  id: string;
  label: string;
  kind: string;
  status: string;
  summary?: string | null;
  reasoning: string[];
  steps: AgentTraceStep[];
  children: AgentTrace[];
};

export type Message = {
  id: string;
  conversation_id?: string;
  conversationId?: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
  agent_trace?: AgentTrace | null;
  agentTrace?: AgentTrace | null;
  created_at?: string;
  createdAt?: string;
};

export type Conversation = {
  id: string;
  user_id: string;
  title: string;
  created_at: string;
  updated_at: string;
};

export type ConversationDetail = Conversation & {
  messages: Message[];
};

export type IngestionJob = {
  id: string;
  document_id: string;
  status: "queued" | "processing" | "completed" | "failed";
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
};

export type ExtractedDocumentMetadata = {
  title: string | null;
  summary: string | null;
  document_type: string | null;
  topics: string[];
  entities: string[];
  language: string | null;
};

export type MetadataFilters = {
  document_types: string[];
  topics: string[];
  entities: string[];
  languages: string[];
};

export type DocumentRecord = {
  id: string;
  user_id: string;
  filename: string;
  source_key: string;
  storage_path: string;
  content_hash: string | null;
  hash_algorithm: string;
  version: number;
  last_ingestion_result: "new" | "updated" | "unchanged" | null;
  extracted_metadata: ExtractedDocumentMetadata | null;
  metadata_schema_version: number | null;
  metadata_status: "not_started" | "processing" | "completed" | "failed";
  metadata_error: string | null;
  metadata_extracted_at: string | null;
  status: string;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  ingestion_job: IngestionJob;
};
