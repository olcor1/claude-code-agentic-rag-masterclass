import { useEffect, useMemo, useRef, useState, type ChangeEvent, type DragEvent, type KeyboardEvent } from "react";
import {
  FileUp,
  LogOut,
  MessagesSquare,
  RefreshCcw,
  SendHorizontal,
  SlidersHorizontal,
  Trash2,
  X,
} from "lucide-react";

import {
  createConversation,
  deleteDocument,
  fetchConversation,
  fetchConversations,
  fetchDocuments,
  streamConversationMessage,
  streamDocumentStatus,
  uploadDocument,
} from "@/api/client";
import type { AgentTrace, Citation, Conversation, DocumentRecord, Message, MetadataFilters } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { useAuth } from "@/hooks/use-auth";

const terminalIngestionStatuses = new Set(["completed", "failed"]);
const uploadAccept = ".txt,.md,.html,.docx,.pdf";

type DashboardView = "chat" | "ingestion";
type MetadataFilterKey = keyof MetadataFilters;

const metadataFilterSections: Array<{ key: MetadataFilterKey; label: string }> = [
  { key: "document_types", label: "Type" },
  { key: "topics", label: "Topics" },
  { key: "entities", label: "Entities" },
  { key: "languages", label: "Language" },
];

function createEmptyMetadataFilters(): MetadataFilters {
  return {
    document_types: [],
    topics: [],
    entities: [],
    languages: [],
  };
}

function upsertDocumentRecord(items: DocumentRecord[], document: DocumentRecord) {
  return [document, ...items.filter((item) => item.id !== document.id)];
}

function mergeDocumentRecord(items: DocumentRecord[], document: DocumentRecord) {
  const index = items.findIndex((item) => item.id === document.id);
  if (index === -1) {
    return [document, ...items];
  }

  const nextItems = [...items];
  nextItems[index] = document;
  return nextItems;
}

function describeCompletedUpload(filename: string, result: DocumentRecord["last_ingestion_result"]) {
  if (result === "unchanged") {
    return `${filename} unchanged, skipped re-index`;
  }
  if (result === "updated") {
    return `${filename} re-indexed`;
  }
  return `${filename} indexed`;
}

function describeDocumentProcessingStatus(document: DocumentRecord) {
  if (document.ingestion_job.status === "processing") {
    return `Processing ${document.filename}`;
  }
  if (document.ingestion_job.status === "queued") {
    return document.version > 0 ? `Queued re-index for ${document.filename}` : `Queued ${document.filename}`;
  }
  if (document.ingestion_job.status === "failed") {
    return document.ingestion_job.error_message ?? `Processing failed for ${document.filename}`;
  }
  return describeCompletedUpload(document.filename, document.last_ingestion_result);
}

function getDocumentBadgeLabel(document: DocumentRecord) {
  if (document.ingestion_job.status === "failed") {
    return "FAILED";
  }
  if (document.ingestion_job.status === "processing") {
    return "PROCESSING";
  }
  if (document.ingestion_job.status === "queued") {
    return document.version > 0 ? "REINDEX QUEUED" : "QUEUED";
  }
  if (document.last_ingestion_result === "unchanged") {
    return "UNCHANGED";
  }
  if (document.last_ingestion_result === "updated") {
    return "UPDATED";
  }
  return "INDEXED";
}

function formatMetadataValue(value: string) {
  return value
    .split(/[\s_-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function hasActiveMetadataFilters(filters: MetadataFilters) {
  return Object.values(filters).some((values) => values.length > 0);
}

function toggleMetadataFilter(filters: MetadataFilters, key: MetadataFilterKey, value: string): MetadataFilters {
  const nextValues = filters[key].includes(value)
    ? filters[key].filter((item) => item !== value)
    : [...filters[key], value];

  return {
    ...filters,
    [key]: nextValues,
  };
}

function collectMetadataOptions(documents: DocumentRecord[]): MetadataFilters {
  const buckets: Record<MetadataFilterKey, Set<string>> = {
    document_types: new Set<string>(),
    topics: new Set<string>(),
    entities: new Set<string>(),
    languages: new Set<string>(),
  };

  for (const document of documents) {
    const metadata = document.extracted_metadata;
    if (!metadata) {
      continue;
    }
    if (metadata.document_type) {
      buckets.document_types.add(metadata.document_type);
    }
    if (metadata.language) {
      buckets.languages.add(metadata.language);
    }
    for (const topic of metadata.topics ?? []) {
      buckets.topics.add(topic);
    }
    for (const entity of metadata.entities ?? []) {
      buckets.entities.add(entity);
    }
  }

  return {
    document_types: [...buckets.document_types].sort(),
    topics: [...buckets.topics].sort(),
    entities: [...buckets.entities].sort(),
    languages: [...buckets.languages].sort(),
  };
}

function truncateText(value: string | null | undefined, maxLength: number) {
  if (!value) {
    return null;
  }
  return value.length > maxLength ? `${value.slice(0, maxLength).trim()}...` : value;
}

function getMetadataHighlights(document: DocumentRecord) {
  const metadata = document.extracted_metadata;
  if (!metadata) {
    return [];
  }

  const highlights: string[] = [];
  if (metadata.document_type) {
    highlights.push(metadata.document_type);
  }
  if (metadata.language) {
    highlights.push(metadata.language);
  }
  highlights.push(...(metadata.topics ?? []).slice(0, 3));
  return highlights;
}

function describeCitation(citation: Citation) {
  const matchTypeLabel = citation.matchType ? formatMetadataValue(citation.matchType) : null;
  if (citation.sourceType === "sql") {
    return `[SQL${citation.index}] ${citation.label ?? "Workspace SQL"}`;
  }
  if (citation.sourceType === "web") {
    return `[WEB${citation.index}] ${citation.title ?? citation.domain ?? citation.url ?? "Web result"}`;
  }
  if (matchTypeLabel) {
    return `[${citation.index}] ${citation.filename ?? "Document"} · ${matchTypeLabel}`;
  }
  return `[${citation.index}] ${citation.filename ?? "Document"}`;
}

function describeCitationDetails(citation: Citation) {
  if (citation.sourceType === "sql") {
    return citation.query ?? citation.excerpt;
  }
  if (citation.sourceType === "web") {
    return citation.url ?? citation.excerpt;
  }
  return citation.excerpt;
}

function getMessageAgentTrace(message: Message) {
  const trace = message.agentTrace ?? message.agent_trace ?? null;
  if (!trace) {
    return null;
  }
  if (!trace.label && !trace.summary && !trace.reasoning?.length && !trace.steps?.length && !trace.children?.length) {
    return null;
  }
  return trace;
}

function getStatusClasses(status: string) {
  if (status === "completed") {
    return "border-pine/20 bg-pine/10 text-pine";
  }
  if (status === "failed") {
    return "border-berry/20 bg-berry/10 text-berry";
  }
  return "border-ink/10 bg-white text-ink/60";
}

function summarizeDocumentStatuses(documents: DocumentRecord[]) {
  return documents.reduce(
    (summary, document) => {
      if (document.ingestion_job.status === "completed") {
        summary.completed += 1;
      } else if (document.ingestion_job.status === "failed") {
        summary.failed += 1;
      } else if (document.ingestion_job.status === "processing") {
        summary.processing += 1;
      } else {
        summary.queued += 1;
      }
      return summary;
    },
    { completed: 0, failed: 0, processing: 0, queued: 0 },
  );
}

function AgentTraceTree({ trace }: { trace: AgentTrace }) {
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium text-ink">{trace.label}</span>
        <span className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.18em] ${getStatusClasses(trace.status)}`}>
          {trace.status}
        </span>
      </div>

      {trace.summary ? <p className="text-xs leading-6 text-ink/65">{trace.summary}</p> : null}

      {trace.reasoning.length ? (
        <div className="space-y-2">
          {trace.reasoning.map((item, index) => (
            <div key={`${trace.id}-reasoning-${index}`} className="rounded-2xl border border-ink/10 bg-white/80 px-3 py-2 text-xs leading-6 text-ink/70">
              {item}
            </div>
          ))}
        </div>
      ) : null}

      {trace.steps.length ? (
        <div className="space-y-2">
          {trace.steps.map((step) => (
            <div key={step.id} className="rounded-2xl border border-ink/10 bg-white/85 px-3 py-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-semibold uppercase tracking-[0.18em] text-ink/50">{step.kind}</span>
                <span className="text-sm font-medium text-ink">{step.title}</span>
                <span className={`rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.18em] ${getStatusClasses(step.status)}`}>
                  {step.status}
                </span>
              </div>
              {step.toolName ? <div className="mt-2 font-mono text-[11px] text-ink/50">{step.toolName}</div> : null}
              {step.summary ? <p className="mt-2 text-xs leading-6 text-ink/70">{step.summary}</p> : null}
              {step.inputSummary ? <p className="mt-2 text-[11px] leading-5 text-ink/50">Input: {step.inputSummary}</p> : null}
              {step.outputSummary ? <p className="mt-1 text-[11px] leading-5 text-ink/50">Output: {step.outputSummary}</p> : null}
            </div>
          ))}
        </div>
      ) : null}

      {trace.children.length ? (
        <div className="space-y-3 border-l border-dashed border-ink/15 pl-3">
          {trace.children.map((child) => (
            <AgentTraceTree key={child.id} trace={child} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

function MessageBubble({ message }: { message: Message }) {
  const isAssistant = message.role === "assistant";
  const isThinking = isAssistant && !message.content.trim();
  const agentTrace = getMessageAgentTrace(message);

  return (
    <div className={`flex ${isAssistant ? "justify-start" : "justify-end"}`}>
      <div
        className={`max-w-2xl rounded-[28px] px-4 py-3 ${
          isAssistant ? "bg-white text-ink shadow-panel" : "bg-pine text-paper"
        }`}
      >
        {isThinking ? (
          <div className="flex items-center gap-3 text-sm text-ink/65">
            <div className="flex items-center gap-1" aria-hidden="true">
              <span className="h-2 w-2 animate-pulse rounded-full bg-pine/70" />
              <span className="h-2 w-2 animate-pulse rounded-full bg-pine/55" style={{ animationDelay: "150ms" }} />
              <span className="h-2 w-2 animate-pulse rounded-full bg-pine/40" style={{ animationDelay: "300ms" }} />
            </div>
            <p className="whitespace-pre-wrap text-sm leading-7">AI is thinking...</p>
          </div>
        ) : (
          <p className="whitespace-pre-wrap text-sm leading-7">{message.content}</p>
        )}
        {message.citations?.length ? (
          <div className="mt-3 flex flex-wrap gap-2">
            {message.citations.map((citation) =>
              citation.sourceType === "web" && citation.url ? (
                <a
                  key={`${message.id}-${citation.sourceType}-${citation.index}`}
                  className="rounded-full bg-paper px-3 py-1 text-xs text-ink/70 underline-offset-2 transition hover:text-pine hover:underline"
                  href={citation.url}
                  rel="noreferrer"
                  target="_blank"
                  title={describeCitationDetails(citation)}
                >
                  {describeCitation(citation)}
                </a>
              ) : (
                <span
                  key={`${message.id}-${citation.sourceType ?? "document"}-${citation.index}`}
                  className="rounded-full bg-paper px-3 py-1 text-xs text-ink/70"
                  title={describeCitationDetails(citation)}
                >
                  {describeCitation(citation)}
                </span>
              ),
            )}
          </div>
        ) : null}
        {isAssistant && agentTrace ? (
          <details className="mt-3 rounded-[22px] border border-ink/10 bg-paper/80 px-3 py-3" open={agentTrace.status === "running"}>
            <summary className="cursor-pointer text-xs font-semibold uppercase tracking-[0.18em] text-ink/50">
              Agent trace
            </summary>
            <div className="mt-3">
              <AgentTraceTree trace={agentTrace} />
            </div>
          </details>
        ) : null}
      </div>
    </div>
  );
}

function DocumentCard({
  document,
  deletingDocumentId,
  onDelete,
}: {
  document: DocumentRecord;
  deletingDocumentId: string | null;
  onDelete: (document: DocumentRecord) => Promise<void>;
}) {
  const metadataHighlights = getMetadataHighlights(document);
  const metadataSummary = truncateText(document.extracted_metadata?.summary, 180);
  const canDelete = terminalIngestionStatuses.has(document.ingestion_job.status);
  const isDeleting = deletingDocumentId === document.id;
  const showMetadataError =
    document.metadata_status === "failed" &&
    document.metadata_error &&
    document.metadata_error !== document.ingestion_job.error_message;

  return (
    <div className="rounded-[22px] border border-ink/10 bg-white px-4 py-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-ink">{document.filename}</div>
          <div className="mt-1 text-xs uppercase tracking-[0.18em] text-ink/45">{getDocumentBadgeLabel(document)}</div>
        </div>
        <button
          aria-label={`Delete ${document.filename}`}
          className="rounded-full border border-ink/10 p-2 text-ink/45 transition hover:border-berry/30 hover:text-berry disabled:cursor-not-allowed disabled:opacity-40"
          disabled={!canDelete || isDeleting}
          onClick={() => void onDelete(document)}
          type="button"
        >
          <Trash2 className="h-4 w-4" />
        </button>
      </div>

      <div className="mt-2 text-xs text-ink/45">
        v{document.version}
        {document.source_key !== document.filename ? ` · ${document.source_key}` : ""}
      </div>
      {!canDelete ? <div className="mt-2 text-xs text-ink/45">Deletion unlocks after the ingestion job reaches a terminal state.</div> : null}

      {metadataHighlights.length ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {metadataHighlights.map((item) => (
            <span key={`${document.id}-${item}`} className="rounded-full bg-paper px-3 py-1 text-[11px] font-medium text-ink/70">
              {formatMetadataValue(item)}
            </span>
          ))}
        </div>
      ) : null}

      {metadataSummary ? <p className="mt-3 text-xs leading-6 text-ink/60">{metadataSummary}</p> : null}
      {document.metadata_status === "processing" ? <div className="mt-2 text-xs text-ink/45">Refreshing metadata...</div> : null}
      {showMetadataError ? (
        <div className="mt-2 text-xs text-berry">Metadata unavailable: {document.metadata_error}</div>
      ) : null}
      {document.ingestion_job.error_message ? <div className="mt-2 text-xs text-berry">{document.ingestion_job.error_message}</div> : null}
    </div>
  );
}

function StatusMetric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-[22px] border border-ink/10 bg-white px-4 py-4">
      <div className="text-[11px] uppercase tracking-[0.18em] text-ink/45">{label}</div>
      <div className="mt-2 text-3xl font-semibold text-ink">{value}</div>
    </div>
  );
}

export function DashboardPage() {
  const { token, user, logout } = useAuth();
  const [activeView, setActiveView] = useState<DashboardView>("chat");
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [metadataFilters, setMetadataFilters] = useState<MetadataFilters>(() => createEmptyMetadataFilters());
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [status, setStatus] = useState<string>("Ready");
  const [isBusy, setIsBusy] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [isDraggingFiles, setIsDraggingFiles] = useState(false);
  const [deletingDocumentId, setDeletingDocumentId] = useState<string | null>(null);
  const activeConversationIdRef = useRef<string | null>(null);
  const messagesViewportRef = useRef<HTMLDivElement | null>(null);
  const documentStreamControllersRef = useRef<Map<string, AbortController>>(new Map());

  const activeConversation = useMemo(
    () => conversations.find((conversation) => conversation.id === activeConversationId) ?? null,
    [activeConversationId, conversations],
  );
  const metadataOptions = useMemo(() => collectMetadataOptions(documents), [documents]);
  const activeFilterChips = useMemo(
    () =>
      metadataFilterSections.flatMap(({ key, label }) =>
        metadataFilters[key].map((value) => ({
          key,
          label,
          value,
        })),
      ),
    [metadataFilters],
  );
  const activeIngestionDocuments = useMemo(
    () => documents.filter((document) => !terminalIngestionStatuses.has(document.ingestion_job.status)),
    [documents],
  );
  const documentStatusSummary = useMemo(() => summarizeDocumentStatuses(documents), [documents]);

  useEffect(() => {
    activeConversationIdRef.current = activeConversationId;
  }, [activeConversationId]);

  useEffect(() => {
    return () => {
      documentStreamControllersRef.current.forEach((controller) => controller.abort());
      documentStreamControllersRef.current.clear();
    };
  }, []);

  useEffect(() => {
    if (!token) {
      return;
    }

    const load = async () => {
      const [nextConversations, nextDocuments] = await Promise.all([fetchConversations(token), fetchDocuments(token)]);
      setConversations(nextConversations);
      setDocuments(nextDocuments);
      if (!activeConversationId && nextConversations[0]) {
        setActiveConversationId(nextConversations[0].id);
      }
    };

    void load().catch((error) => setStatus(error instanceof Error ? error.message : "Failed to load workspace"));
  }, [token]);

  useEffect(() => {
    if (!token || !activeConversationId) {
      setMessages([]);
      return;
    }

    void fetchConversation(token, activeConversationId)
      .then((conversation) => setMessages(conversation.messages))
      .catch((error) => setStatus(error instanceof Error ? error.message : "Failed to load conversation"));
  }, [activeConversationId, token]);

  useEffect(() => {
    const viewport = messagesViewportRef.current;
    if (!viewport) {
      return;
    }

    window.requestAnimationFrame(() => {
      viewport.scrollTop = viewport.scrollHeight;
    });
  }, [messages]);

  const refreshWorkspace = async () => {
    if (!token) {
      return;
    }

    const [nextConversations, nextDocuments] = await Promise.all([fetchConversations(token), fetchDocuments(token)]);
    setConversations(nextConversations);
    setDocuments(nextDocuments);
  };

  const syncConversation = async (conversationId: string) => {
    if (!token) {
      return;
    }

    const conversation = await fetchConversation(token, conversationId);
    if (activeConversationIdRef.current === null || activeConversationIdRef.current === conversationId) {
      setMessages(conversation.messages);
    }
  };

  const stopDocumentStatusStream = (documentId: string) => {
    const controller = documentStreamControllersRef.current.get(documentId);
    if (controller) {
      controller.abort();
      documentStreamControllersRef.current.delete(documentId);
    }
  };

  const startDocumentStatusStream = (document: DocumentRecord) => {
    if (!token || terminalIngestionStatuses.has(document.ingestion_job.status)) {
      stopDocumentStatusStream(document.id);
      return;
    }
    if (documentStreamControllersRef.current.has(document.id)) {
      return;
    }

    const controller = new AbortController();
    documentStreamControllersRef.current.set(document.id, controller);

    void streamDocumentStatus(
      token,
      document.id,
      {
        onDocument: (nextDocument) => {
          setDocuments((current) => mergeDocumentRecord(current, nextDocument));
          setStatus(describeDocumentProcessingStatus(nextDocument));
        },
        onDone: (nextDocument) => {
          stopDocumentStatusStream(nextDocument.id);
          setDocuments((current) => mergeDocumentRecord(current, nextDocument));
          setStatus(describeDocumentProcessingStatus(nextDocument));
          void refreshWorkspace();
        },
      },
      controller.signal,
    ).catch((error) => {
      if (controller.signal.aborted) {
        return;
      }
      documentStreamControllersRef.current.delete(document.id);
      setStatus(error instanceof Error ? error.message : "Document status stream failed");
    });
  };

  useEffect(() => {
    if (!token) {
      documentStreamControllersRef.current.forEach((controller) => controller.abort());
      documentStreamControllersRef.current.clear();
      return;
    }

    const liveDocumentIds = new Set(
      documents
        .filter((document) => !terminalIngestionStatuses.has(document.ingestion_job.status))
        .map((document) => document.id),
    );

    documents.forEach((document) => {
      if (!terminalIngestionStatuses.has(document.ingestion_job.status)) {
        startDocumentStatusStream(document);
      }
    });

    documentStreamControllersRef.current.forEach((controller, documentId) => {
      if (!liveDocumentIds.has(documentId)) {
        controller.abort();
        documentStreamControllersRef.current.delete(documentId);
      }
    });
  }, [documents, token]);

  const handleDeleteDocument = async (document: DocumentRecord) => {
    if (!token) {
      return;
    }
    if (!terminalIngestionStatuses.has(document.ingestion_job.status)) {
      setStatus(`Wait for ${document.filename} to finish processing before deleting it`);
      return;
    }

    const confirmed = window.confirm(`Delete ${document.filename}? This removes the stored file and indexed chunks.`);
    if (!confirmed) {
      return;
    }

    setDeletingDocumentId(document.id);
    setStatus(`Deleting ${document.filename}`);
    stopDocumentStatusStream(document.id);

    try {
      await deleteDocument(token, document.id);
      setDocuments((current) => current.filter((item) => item.id !== document.id));
      setStatus(`${document.filename} deleted`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Failed to delete document");
    } finally {
      setDeletingDocumentId((current) => (current === document.id ? null : current));
    }
  };

  const handleUploadFiles = async (files: File[]) => {
    if (!token || files.length === 0) {
      return;
    }

    setActiveView("ingestion");
    setIsUploading(true);

    try {
      for (const file of files) {
        const existingDocument = documents.find((document) => document.source_key === file.name);
        setStatus(`Uploading ${file.name}`);
        const created = await uploadDocument(token, file, file.name);
        const isReindex = existingDocument?.id === created.id && (existingDocument?.version ?? 0) > 0;

        setDocuments((current) => upsertDocumentRecord(current, created));

        if (created.last_ingestion_result === "unchanged") {
          setStatus(describeCompletedUpload(file.name, created.last_ingestion_result));
          continue;
        }

        if (terminalIngestionStatuses.has(created.ingestion_job.status)) {
          setStatus(
            created.ingestion_job.status === "completed"
              ? describeCompletedUpload(file.name, created.last_ingestion_result)
              : created.ingestion_job.error_message ?? "Processing failed",
          );
          continue;
        }

        setStatus(isReindex ? `Re-indexing ${file.name}` : `Indexing ${file.name}`);
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Failed to upload document");
    } finally {
      setIsUploading(false);
      setIsDraggingFiles(false);
    }
  };

  const handleUploadInput = (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    void handleUploadFiles(files);
    event.target.value = "";
  };

  const handleDrop = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    const files = Array.from(event.dataTransfer.files ?? []);
    void handleUploadFiles(files);
  };

  const handleDragState = (event: DragEvent<HTMLLabelElement>, nextState: boolean) => {
    event.preventDefault();
    setIsDraggingFiles(nextState);
  };

  const handleDraftKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) {
      return;
    }

    event.preventDefault();
    if (isBusy || !draft.trim()) {
      return;
    }

    void sendMessage();
  };

  const sendMessage = async () => {
    if (!draft.trim() || !token) {
      return;
    }

    const question = draft.trim();
    const appliedMetadataFilters = hasActiveMetadataFilters(metadataFilters) ? metadataFilters : null;
    const usesMetadataFilters = appliedMetadataFilters !== null;

    setIsBusy(true);
    setStatus(usesMetadataFilters ? "Running filtered hybrid search" : "Running hybrid search");

    const userMessage: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content: question,
      citations: [],
    };
    const assistantDraftId = crypto.randomUUID();
    const assistantMessage: Message = {
      id: assistantDraftId,
      role: "assistant",
      content: "",
      citations: [],
      agent_trace: null,
    };

    setMessages((current) => [...current, userMessage, assistantMessage]);
    setDraft("");
    let pendingCitations: Citation[] = [];

    try {
      let conversationId = activeConversationId;
      let createdConversationId: string | null = null;
      if (!conversationId) {
        const conversation = await createConversation(token);
        setConversations((current) => [conversation, ...current]);
        conversationId = conversation.id;
        createdConversationId = conversation.id;
      }

      await streamConversationMessage(
        token,
        conversationId,
        question,
        {
          onMeta: (citations) => {
            pendingCitations = citations;
            setMessages((current) =>
              current.map((message) => (message.id === assistantDraftId ? { ...message, citations } : message)),
            );
          },
          onStatus: (nextStatus) => {
            setStatus(nextStatus);
          },
          onTrace: (agentTrace) => {
            setMessages((current) => {
              const hasDraftMessage = current.some((message) => message.id === assistantDraftId);
              if (!hasDraftMessage) {
                return [
                  ...current,
                  {
                    id: assistantDraftId,
                    role: "assistant",
                    content: "",
                    citations: pendingCitations,
                    agent_trace: agentTrace,
                  },
                ];
              }

              return current.map((message) =>
                message.id === assistantDraftId ? { ...message, agent_trace: agentTrace } : message,
              );
            });
          },
          onToken: (tokenChunk) => {
            setMessages((current) => {
              const hasDraftMessage = current.some((message) => message.id === assistantDraftId);
              if (!hasDraftMessage) {
                return [
                  ...current,
                  {
                    id: assistantDraftId,
                    role: "assistant",
                    content: tokenChunk,
                    citations: pendingCitations,
                    agent_trace: null,
                  },
                ];
              }

              return current.map((message) =>
                message.id === assistantDraftId
                  ? { ...message, content: `${message.content}${tokenChunk}`, citations: pendingCitations }
                  : message,
              );
            });
          },
          onDone: (message) => {
            setMessages((current) => {
              const hasDraftMessage = current.some((item) => item.id === assistantDraftId);
              if (!hasDraftMessage) {
                return [...current, message];
              }

              return current.map((item) => (item.id === assistantDraftId ? { ...message } : item));
            });
            setStatus("Syncing response");
          },
        },
        appliedMetadataFilters,
      );

      await Promise.all([refreshWorkspace(), syncConversation(conversationId)]);
      if (createdConversationId && activeConversationIdRef.current === null) {
        setActiveConversationId(createdConversationId);
      }
      setStatus("Response complete");
      setActiveView("chat");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Failed to send message");
    } finally {
      setIsBusy(false);
    }
  };

  return (
    <main className="min-h-screen bg-paper px-4 py-4 text-ink lg:px-6">
      <div className="mx-auto grid max-w-[1600px] gap-4 lg:grid-cols-[300px_minmax(0,1fr)_320px]">
        <Card className="flex h-[calc(100vh-2rem)] flex-col gap-4 overflow-hidden bg-ink text-paper">
          <div className="flex items-start justify-between gap-3">
            <div>
              <Badge className="border-paper/15 bg-paper/10 text-paper/75">Operator</Badge>
              <h1 className="mt-3 text-2xl font-semibold">{user?.email}</h1>
              <p className="text-sm text-paper/60">JWT-secured local workspace</p>
            </div>
            <button className="rounded-full border border-paper/15 p-2 text-paper/75" onClick={logout} type="button">
              <LogOut className="h-4 w-4" />
            </button>
          </div>

          <div className="grid grid-cols-2 gap-2 rounded-[24px] border border-paper/10 bg-paper/5 p-1">
            <button
              className={`rounded-[18px] px-4 py-2 text-sm transition ${activeView === "chat" ? "bg-paper text-ink" : "text-paper/65"}`}
              onClick={() => setActiveView("chat")}
              type="button"
            >
              Chat
            </button>
            <button
              className={`rounded-[18px] px-4 py-2 text-sm transition ${
                activeView === "ingestion" ? "bg-paper text-ink" : "text-paper/65"
              }`}
              onClick={() => setActiveView("ingestion")}
              type="button"
            >
              Ingestion
            </button>
          </div>

          <Button className="bg-paper text-ink hover:bg-paper/90" onClick={() => setActiveConversationId(null)} type="button">
            New thread
          </Button>

          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-sm text-paper/70">
              <MessagesSquare className="h-4 w-4" />
              Conversations
            </div>
            <button className="text-paper/60" onClick={() => void refreshWorkspace()} type="button">
              <RefreshCcw className="h-4 w-4" />
            </button>
          </div>

          <div className="space-y-2 overflow-y-auto pr-1">
            {conversations.map((conversation) => (
              <button
                key={conversation.id}
                className={`w-full rounded-[20px] border px-4 py-3 text-left text-sm transition ${
                  activeConversationId === conversation.id
                    ? "border-paper/20 bg-paper/10 text-paper"
                    : "border-paper/10 bg-transparent text-paper/65 hover:bg-paper/5"
                }`}
                onClick={() => {
                  setActiveConversationId(conversation.id);
                  setActiveView("chat");
                }}
                type="button"
              >
                <div className="font-medium">{conversation.title}</div>
                <div className="mt-1 text-xs text-paper/45">{new Date(conversation.updated_at).toLocaleString()}</div>
              </button>
            ))}
          </div>

          <div className="mt-auto rounded-[22px] border border-paper/10 bg-paper/5 px-4 py-4 text-sm text-paper/72">
            <div className="text-[11px] uppercase tracking-[0.18em] text-paper/45">Workspace status</div>
            <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
              <div>{documents.length} docs</div>
              <div>{conversations.length} threads</div>
              <div>{documentStatusSummary.processing} processing</div>
              <div>{documentStatusSummary.failed} failed</div>
            </div>
          </div>
        </Card>

        {activeView === "chat" ? (
          <>
            <Card className="flex h-[calc(100vh-2rem)] flex-col overflow-hidden">
              <div className="border-b border-ink/10 pb-4">
                <Badge>{activeConversation ? activeConversation.title : "New conversation"}</Badge>
                <h2 className="mt-3 text-3xl font-semibold">Grounded chat</h2>
                <p className="mt-1 text-sm text-ink/60">{status}</p>
                {activeFilterChips.length ? (
                  <div className="mt-4 flex flex-wrap gap-2">
                    {activeFilterChips.map((chip) => (
                      <button
                        key={`${chip.key}-${chip.value}`}
                        className="inline-flex items-center gap-2 rounded-full border border-ink/10 bg-white px-3 py-1 text-xs font-medium text-ink/75 transition hover:border-pine/30 hover:text-ink"
                        onClick={() => setMetadataFilters((current) => toggleMetadataFilter(current, chip.key, chip.value))}
                        type="button"
                      >
                        <span>
                          {chip.label}: {formatMetadataValue(chip.value)}
                        </span>
                        <X className="h-3 w-3" />
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>

              <div ref={messagesViewportRef} className="flex-1 space-y-4 overflow-y-auto py-5">
                {messages.length ? (
                  messages.map((message) => <MessageBubble key={message.id} message={message} />)
                ) : (
                  <div className="rounded-[28px] border border-dashed border-ink/15 bg-white/55 p-8 text-sm text-ink/55">
                    Ask about indexed documents, route a workspace analytics question through text-to-SQL, or fall back to web-backed answers when the knowledge base is insufficient.
                  </div>
                )}
              </div>

              <div className="border-t border-ink/10 pt-4">
                <Textarea
                  className="min-h-[140px]"
                  placeholder="Ask about an uploaded document, your workspace data, or a web-backed fallback question..."
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  onKeyDown={handleDraftKeyDown}
                />
                <div className="mt-3 flex items-center justify-between gap-3">
                  <p className="text-xs uppercase tracking-[0.18em] text-ink/45">Streaming over SSE</p>
                  <Button disabled={isBusy || !draft.trim()} onClick={() => void sendMessage()} type="button">
                    <SendHorizontal className="mr-2 h-4 w-4" />
                    Send
                  </Button>
                </div>
              </div>
            </Card>

            <div className="flex h-[calc(100vh-2rem)] min-h-0 flex-col gap-4">
              <Card className="flex max-h-[320px] min-h-0 shrink-0 flex-col overflow-hidden">
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <SlidersHorizontal className="h-4 w-4 text-pine" />
                    <h3 className="text-lg font-semibold">Retrieval filters</h3>
                  </div>
                  <button
                    className="text-xs uppercase tracking-[0.18em] text-ink/45 disabled:opacity-40"
                    disabled={!hasActiveMetadataFilters(metadataFilters)}
                    onClick={() => setMetadataFilters(createEmptyMetadataFilters())}
                    type="button"
                  >
                    Clear
                  </button>
                </div>
                <p className="text-sm text-ink/55">Filter retrieval by extracted document metadata before the agent runs hybrid search.</p>
                <div className="space-y-4 overflow-y-auto pr-1">
                  {metadataFilterSections.map(({ key, label }) => (
                    <div key={key} className="space-y-2">
                      <div className="text-xs uppercase tracking-[0.18em] text-ink/45">{label}</div>
                      {metadataOptions[key].length ? (
                        <div className="flex flex-wrap gap-2">
                          {metadataOptions[key].map((value) => {
                            const isActive = metadataFilters[key].includes(value);
                            return (
                              <button
                                key={`${key}-${value}`}
                                className={`rounded-full border px-3 py-1 text-xs font-medium transition ${
                                  isActive
                                    ? "border-pine bg-pine text-paper"
                                    : "border-ink/10 bg-white text-ink/65 hover:border-pine/30 hover:text-ink"
                                }`}
                                onClick={() => setMetadataFilters((current) => toggleMetadataFilter(current, key, value))}
                                type="button"
                              >
                                {formatMetadataValue(value)}
                              </button>
                            );
                          })}
                        </div>
                      ) : (
                        <div className="text-xs text-ink/40">No extracted {label.toLowerCase()} yet.</div>
                      )}
                    </div>
                  ))}
                </div>
              </Card>

              <Card className="flex min-h-0 flex-1 flex-col overflow-hidden">
                <div className="mb-4 flex items-center justify-between gap-3">
                  <div>
                    <h3 className="text-lg font-semibold">Knowledge base</h3>
                    <p className="mt-1 text-sm text-ink/55">Switch to the Ingestion view for drag-and-drop uploads and full document management.</p>
                  </div>
                  <Button className="shrink-0 border-ink/10 bg-white text-ink hover:bg-paper" onClick={() => setActiveView("ingestion")} type="button">
                    Open ingestion
                  </Button>
                </div>

                <div className="flex-1 space-y-3 overflow-y-auto pr-1">
                  {documents.length ? (
                    documents.map((document) => (
                      <DocumentCard
                        key={document.id}
                        deletingDocumentId={deletingDocumentId}
                        document={document}
                        onDelete={handleDeleteDocument}
                      />
                    ))
                  ) : (
                    <div className="rounded-[24px] border border-dashed border-ink/15 bg-paper px-4 py-8 text-sm text-ink/55">
                      No documents indexed yet. Open Ingestion to add `.txt`, `.md`, `.html`, `.docx`, or `.pdf` files.
                    </div>
                  )}
                </div>
              </Card>
            </div>
          </>
        ) : (
          <>
            <Card className="flex h-[calc(100vh-2rem)] flex-col overflow-hidden">
              <div className="border-b border-ink/10 pb-4">
                <Badge>Manual upload only</Badge>
                <h2 className="mt-3 text-3xl font-semibold">Ingestion workspace</h2>
                <p className="mt-1 text-sm text-ink/60">{status}</p>
              </div>

              <div className="space-y-4 overflow-y-auto py-5">
                <label
                  className={`flex cursor-pointer flex-col items-center justify-center rounded-[28px] border border-dashed px-6 py-12 text-center transition ${
                    isDraggingFiles
                      ? "border-pine bg-pine/10 text-ink"
                      : "border-ink/15 bg-paper text-ink/65 hover:border-pine/35 hover:text-ink"
                  }`}
                  onDragEnter={(event) => handleDragState(event, true)}
                  onDragLeave={(event) => handleDragState(event, false)}
                  onDragOver={(event) => handleDragState(event, true)}
                  onDrop={handleDrop}
                >
                  <input accept={uploadAccept} className="hidden" multiple type="file" onChange={handleUploadInput} />
                  <FileUp className="h-7 w-7 text-pine" />
                  <div className="mt-4 text-lg font-semibold text-ink">Drop files here or click to upload</div>
                  <p className="mt-2 max-w-xl text-sm text-ink/60">
                    Upload `.txt`, `.md`, `.html`, `.docx`, or `.pdf` files. Processing starts immediately, metadata is refreshed automatically, and live status updates stream back into this view.
                  </p>
                  <div className="mt-4 rounded-full border border-ink/10 bg-white px-4 py-2 text-xs uppercase tracking-[0.18em] text-ink/50">
                    {isUploading ? "Uploading..." : "Drag and drop enabled"}
                  </div>
                </label>

                <div className="grid gap-3 md:grid-cols-2">
                  <StatusMetric label="Queued" value={documentStatusSummary.queued} />
                  <StatusMetric label="Processing" value={documentStatusSummary.processing} />
                  <StatusMetric label="Completed" value={documentStatusSummary.completed} />
                  <StatusMetric label="Failed" value={documentStatusSummary.failed} />
                </div>

                <div className="rounded-[26px] border border-ink/10 bg-white px-5 py-5">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <h3 className="text-lg font-semibold">Document inventory</h3>
                      <p className="mt-1 text-sm text-ink/55">Track queued and completed ingests, review extracted metadata, and delete stale files.</p>
                    </div>
                    <Badge>{documents.length} docs</Badge>
                  </div>
                  <div className="mt-4 space-y-3">
                    {documents.length ? (
                      documents.map((document) => (
                        <DocumentCard
                          key={document.id}
                          deletingDocumentId={deletingDocumentId}
                          document={document}
                          onDelete={handleDeleteDocument}
                        />
                      ))
                    ) : (
                      <div className="rounded-[22px] border border-dashed border-ink/15 bg-paper px-4 py-8 text-sm text-ink/55">
                        No documents uploaded yet.
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </Card>

            <div className="flex h-[calc(100vh-2rem)] min-h-0 flex-col gap-4">
              <Card className="space-y-4">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <h3 className="text-lg font-semibold">Live job feed</h3>
                    <p className="mt-1 text-sm text-ink/55">Realtime ingestion updates replace the old client polling loop.</p>
                  </div>
                  <button className="text-ink/45" onClick={() => void refreshWorkspace()} type="button">
                    <RefreshCcw className="h-4 w-4" />
                  </button>
                </div>
                <div className="space-y-3">
                  {activeIngestionDocuments.length ? (
                    activeIngestionDocuments.map((document) => (
                      <div key={document.id} className="rounded-[22px] border border-ink/10 bg-paper px-4 py-4">
                        <div className="text-sm font-medium text-ink">{document.filename}</div>
                        <div className="mt-2 text-xs uppercase tracking-[0.18em] text-ink/45">{getDocumentBadgeLabel(document)}</div>
                        <p className="mt-2 text-xs leading-6 text-ink/60">{describeDocumentProcessingStatus(document)}</p>
                      </div>
                    ))
                  ) : (
                    <div className="rounded-[22px] border border-dashed border-ink/15 bg-paper px-4 py-8 text-sm text-ink/55">
                      No active ingestion jobs right now.
                    </div>
                  )}
                </div>
              </Card>

              <Card className="flex min-h-0 flex-1 flex-col overflow-hidden">
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <SlidersHorizontal className="h-4 w-4 text-pine" />
                    <h3 className="text-lg font-semibold">Metadata catalog</h3>
                  </div>
                  <Button className="shrink-0 border-ink/10 bg-white text-ink hover:bg-paper" onClick={() => setActiveView("chat")} type="button">
                    Back to chat
                  </Button>
                </div>
                <p className="mt-2 text-sm text-ink/55">These values are available as retrieval filters in the Chat interface.</p>
                <div className="mt-4 space-y-4 overflow-y-auto pr-1">
                  {metadataFilterSections.map(({ key, label }) => (
                    <div key={key} className="space-y-2">
                      <div className="text-xs uppercase tracking-[0.18em] text-ink/45">{label}</div>
                      {metadataOptions[key].length ? (
                        <div className="flex flex-wrap gap-2">
                          {metadataOptions[key].map((value) => (
                            <span key={`${key}-${value}`} className="rounded-full border border-ink/10 bg-white px-3 py-1 text-xs font-medium text-ink/70">
                              {formatMetadataValue(value)}
                            </span>
                          ))}
                        </div>
                      ) : (
                        <div className="text-xs text-ink/40">No extracted {label.toLowerCase()} yet.</div>
                      )}
                    </div>
                  ))}
                </div>
              </Card>
            </div>
          </>
        )}
      </div>
    </main>
  );
}
