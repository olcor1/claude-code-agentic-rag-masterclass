import type {
  Conversation,
  ConversationDetail,
  DocumentRecord,
  IngestionJob,
  MetadataFilters,
  Message,
  TokenResponse,
  User,
} from "@/api/types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

type RequestOptions = {
  method?: string;
  token?: string | null;
  body?: BodyInit | null;
  headers?: HeadersInit;
  cache?: RequestCache;
};

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (!(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (options.token) {
    headers.set("Authorization", `Bearer ${options.token}`);
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: options.method ?? "GET",
    headers,
    body: options.body ?? null,
    cache: options.cache,
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(payload.detail ?? "Request failed");
  }

  return response.json() as Promise<T>;
}

export async function register(email: string, password: string): Promise<TokenResponse> {
  return request<TokenResponse>("/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export async function login(email: string, password: string): Promise<TokenResponse> {
  return request<TokenResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export async function fetchMe(token: string): Promise<User> {
  return request<User>("/auth/me", { token });
}

export async function fetchConversations(token: string): Promise<Conversation[]> {
  return request<Conversation[]>("/conversations", { token });
}

export async function createConversation(token: string, title?: string): Promise<Conversation> {
  return request<Conversation>("/conversations", {
    method: "POST",
    token,
    body: JSON.stringify({ title }),
  });
}

export async function fetchConversation(token: string, conversationId: string): Promise<ConversationDetail> {
  return request<ConversationDetail>(`/conversations/${conversationId}`, { token });
}

export async function fetchDocuments(token: string): Promise<DocumentRecord[]> {
  return request<DocumentRecord[]>("/documents", { token });
}

export async function fetchDocumentStatus(
  token: string,
  documentId: string,
): Promise<{
  document_id: string;
  ingestion_job_id: string;
  status: IngestionJob["status"];
  last_ingestion_result: DocumentRecord["last_ingestion_result"];
  error_message: string | null;
  metadata_status: DocumentRecord["metadata_status"];
  metadata_error: string | null;
  metadata_extracted_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  updated_at: string | null;
}> {
  return request(`/documents/${documentId}/status`, {
    token,
    cache: "no-store",
    headers: {
      "Cache-Control": "no-cache",
      Pragma: "no-cache",
    },
  });
}

export async function uploadDocument(token: string, file: File, sourceKey = file.name): Promise<DocumentRecord> {
  const form = new FormData();
  form.append("file", file);
  form.append("source_key", sourceKey);
  return request<DocumentRecord>("/documents/upload", {
    method: "POST",
    token,
    body: form,
  });
}

export async function deleteDocument(token: string, documentId: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/documents/${documentId}`, {
    method: "DELETE",
    headers: {
      Authorization: `Bearer ${token}`,
    },
  });

  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: "Delete request failed" }));
    throw new Error(payload.detail ?? "Delete request failed");
  }
}

type StreamEvent = {
  event: string;
  data: unknown;
};

async function readEventStream(
  response: Response,
  onEvent: (event: StreamEvent) => void,
): Promise<void> {
  if (!response.body) {
    throw new Error("Streaming response body is unavailable");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const processEvent = (rawEvent: string) => {
    const lines = rawEvent.split("\n").filter(Boolean);
    const event = lines.find((line) => line.startsWith("event:"))?.replace("event:", "").trim();
    const data = lines
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.replace("data:", "").trim())
      .join("\n");

    if (!event || !data) {
      return;
    }

    onEvent({
      event,
      data: JSON.parse(data),
    });
  };

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });

    let boundaryIndex = buffer.indexOf("\n\n");
    while (boundaryIndex >= 0) {
      processEvent(buffer.slice(0, boundaryIndex));
      buffer = buffer.slice(boundaryIndex + 2);
      boundaryIndex = buffer.indexOf("\n\n");
    }

    if (done) {
      if (buffer.trim()) {
        processEvent(buffer);
      }
      break;
    }
  }
}

type StreamHandlers = {
  onMeta?: (citations: Message["citations"]) => void;
  onStatus?: (status: string) => void;
  onTrace?: (agentTrace: NonNullable<Message["agent_trace"]>) => void;
  onToken?: (token: string) => void;
  onDone?: (message: Message) => void;
};

export async function streamConversationMessage(
  token: string,
  conversationId: string,
  content: string,
  handlers: StreamHandlers,
  metadataFilters: MetadataFilters | null = null,
): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/conversations/${conversationId}/messages/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      content,
      metadata_filters: metadataFilters,
    }),
  });

  if (!response.ok || !response.body) {
    const payload = await response.json().catch(() => ({ detail: "Streaming request failed" }));
    throw new Error(payload.detail ?? "Streaming request failed");
  }

  await readEventStream(response, ({ event, data }) => {
    const parsed = data as Record<string, unknown>;
    if (event === "meta") {
      handlers.onMeta?.((parsed.citations as Message["citations"]) ?? []);
    }
    if (event === "status") {
      handlers.onStatus?.((parsed.text as string) ?? "");
    }
    if (event === "trace" && parsed.agentTrace) {
      handlers.onTrace?.(parsed.agentTrace as NonNullable<Message["agent_trace"]>);
    }
    if (event === "token") {
      handlers.onToken?.((parsed.text as string) ?? "");
    }
    if (event === "done") {
      handlers.onDone?.(parsed.message as Message);
    }
  });
}

type DocumentStatusStreamHandlers = {
  onDocument?: (document: DocumentRecord) => void;
  onDone?: (document: DocumentRecord) => void;
};

export async function streamDocumentStatus(
  token: string,
  documentId: string,
  handlers: DocumentStatusStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/documents/${documentId}/status/stream`, {
    method: "GET",
    headers: {
      Authorization: `Bearer ${token}`,
    },
    signal,
  });

  if (!response.ok || !response.body) {
    const payload = await response.json().catch(() => ({ detail: "Document status stream failed" }));
    throw new Error(payload.detail ?? "Document status stream failed");
  }

  try {
    await readEventStream(response, ({ event, data }) => {
      const parsed = data as { document?: DocumentRecord };
      if (event === "document" && parsed.document) {
        handlers.onDocument?.(parsed.document);
      }
      if (event === "done" && parsed.document) {
        handlers.onDone?.(parsed.document);
      }
    });
  } catch (error) {
    if (signal?.aborted) {
      return;
    }
    throw error;
  }
}
