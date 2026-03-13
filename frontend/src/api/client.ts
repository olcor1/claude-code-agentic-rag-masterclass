import type {
  Conversation,
  ConversationDetail,
  DocumentRecord,
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
): Promise<{ id: string; status: string; error_message: string | null }> {
  return request(`/documents/${documentId}/status`, { token });
}

export async function uploadDocument(token: string, file: File): Promise<DocumentRecord> {
  const form = new FormData();
  form.append("file", file);
  return request<DocumentRecord>("/documents/upload", {
    method: "POST",
    token,
    body: form,
  });
}

type StreamHandlers = {
  onMeta?: (citations: Message["citations"]) => void;
  onToken?: (token: string) => void;
  onDone?: (message: Message) => void;
};

export async function streamConversationMessage(
  token: string,
  conversationId: string,
  content: string,
  handlers: StreamHandlers,
): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/conversations/${conversationId}/messages/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ content }),
  });

  if (!response.ok || !response.body) {
    const payload = await response.json().catch(() => ({ detail: "Streaming request failed" }));
    throw new Error(payload.detail ?? "Streaming request failed");
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

    if (!event || !data) return;

    const parsed = JSON.parse(data);
    if (event === "meta") {
      handlers.onMeta?.(parsed.citations ?? []);
    }
    if (event === "token") {
      handlers.onToken?.(parsed.text ?? "");
    }
    if (event === "done") {
      handlers.onDone?.(parsed.message);
    }
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
