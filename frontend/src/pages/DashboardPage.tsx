import { useEffect, useMemo, useState, type ChangeEvent } from "react";
import { FileUp, LogOut, MessagesSquare, RefreshCcw, SendHorizontal } from "lucide-react";

import {
  createConversation,
  fetchConversation,
  fetchConversations,
  fetchDocumentStatus,
  fetchDocuments,
  streamConversationMessage,
  uploadDocument,
} from "@/api/client";
import type { Citation, Conversation, DocumentRecord, Message } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { useAuth } from "@/hooks/use-auth";

function MessageBubble({ message }: { message: Message }) {
  const isAssistant = message.role === "assistant";
  return (
    <div className={`flex ${isAssistant ? "justify-start" : "justify-end"}`}>
      <div
        className={`max-w-2xl rounded-[28px] px-4 py-3 ${
          isAssistant ? "bg-white text-ink shadow-panel" : "bg-pine text-paper"
        }`}
      >
        <p className="whitespace-pre-wrap text-sm leading-7">{message.content}</p>
        {message.citations?.length ? (
          <div className="mt-3 flex flex-wrap gap-2">
            {message.citations.map((citation) => (
              <span key={`${message.id}-${citation.index}`} className="rounded-full bg-paper px-3 py-1 text-xs text-ink/70">
                [{citation.index}] {citation.filename}
              </span>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function DashboardPage() {
  const { token, user, logout } = useAuth();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [status, setStatus] = useState<string>("Ready");
  const [isBusy, setIsBusy] = useState(false);

  const activeConversation = useMemo(
    () => conversations.find((conversation) => conversation.id === activeConversationId) ?? null,
    [activeConversationId, conversations],
  );

  useEffect(() => {
    if (!token) return;

    const load = async () => {
      const [nextConversations, nextDocuments] = await Promise.all([fetchConversations(token), fetchDocuments(token)]);
      setConversations(nextConversations);
      setDocuments(nextDocuments);
      if (!activeConversationId && nextConversations[0]) {
        setActiveConversationId(nextConversations[0].id);
      }
    };

    void load().catch((error) => setStatus(error instanceof Error ? error.message : "Failed to load workspace"));
  }, [activeConversationId, token]);

  useEffect(() => {
    if (!token || !activeConversationId) {
      setMessages([]);
      return;
    }

    void fetchConversation(token, activeConversationId)
      .then((conversation) => setMessages(conversation.messages))
      .catch((error) => setStatus(error instanceof Error ? error.message : "Failed to load conversation"));
  }, [activeConversationId, token]);

  const refreshWorkspace = async () => {
    if (!token) return;
    const [nextConversations, nextDocuments] = await Promise.all([fetchConversations(token), fetchDocuments(token)]);
    setConversations(nextConversations);
    setDocuments(nextDocuments);
  };

  const handleUpload = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file || !token) return;

    setStatus(`Uploading ${file.name}`);
    const created = await uploadDocument(token, file);
    setDocuments((current) => [created, ...current]);

    const poll = window.setInterval(async () => {
      const current = await fetchDocumentStatus(token, created.id);
      setDocuments((items) =>
        items.map((item) => (item.id === created.id ? { ...item, status: current.status, error_message: current.error_message } : item)),
      );
      if (current.status === "processed" || current.status === "failed") {
        window.clearInterval(poll);
        setStatus(current.status === "processed" ? `${file.name} processed` : current.error_message ?? "Processing failed");
      }
    }, 2000);

    event.target.value = "";
  };

  const sendMessage = async () => {
    if (!draft.trim() || !token) return;

    setIsBusy(true);
    setStatus("Retrieving relevant chunks");

    const userMessage: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content: draft.trim(),
      citations: [],
    };
    const assistantDraftId = crypto.randomUUID();
    const assistantMessage: Message = {
      id: assistantDraftId,
      role: "assistant",
      content: "",
      citations: [],
    };

    setMessages((current) => [...current, userMessage, assistantMessage]);
    const question = draft.trim();
    setDraft("");
    let pendingCitations: Citation[] = [];

    try {
      let conversationId = activeConversationId;
      if (!conversationId) {
        const conversation = await createConversation(token);
        setConversations((current) => [conversation, ...current]);
        setActiveConversationId(conversation.id);
        conversationId = conversation.id;
      }

      await streamConversationMessage(token, conversationId, question, {
        onMeta: (citations) => {
          pendingCitations = citations;
          setStatus(citations.length ? "Grounded response streaming" : "No supporting documents found");
        },
        onToken: (tokenChunk) => {
          setMessages((current) =>
            current.map((message) =>
              message.id === assistantDraftId ? { ...message, content: `${message.content}${tokenChunk}`, citations: pendingCitations } : message,
            ),
          );
        },
        onDone: (message) => {
          setMessages((current) => current.map((item) => (item.id === assistantDraftId ? { ...message } : item)));
          setStatus("Response complete");
          void refreshWorkspace();
        },
      });
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
                onClick={() => setActiveConversationId(conversation.id)}
                type="button"
              >
                <div className="font-medium">{conversation.title}</div>
                <div className="mt-1 text-xs text-paper/45">{new Date(conversation.updated_at).toLocaleString()}</div>
              </button>
            ))}
          </div>
        </Card>

        <Card className="flex h-[calc(100vh-2rem)] flex-col overflow-hidden">
          <div className="border-b border-ink/10 pb-4">
            <Badge>{activeConversation ? activeConversation.title : "New conversation"}</Badge>
            <h2 className="mt-3 text-3xl font-semibold">Grounded chat</h2>
            <p className="mt-1 text-sm text-ink/60">{status}</p>
          </div>

          <div className="flex-1 space-y-4 overflow-y-auto py-5">
            {messages.length ? (
              messages.map((message) => <MessageBubble key={message.id} message={message} />)
            ) : (
              <div className="rounded-[28px] border border-dashed border-ink/15 bg-white/55 p-8 text-sm text-ink/55">
                Upload a document, then ask a question. The assistant will retrieve top chunks and stream the answer here.
              </div>
            )}
          </div>

          <div className="border-t border-ink/10 pt-4">
            <Textarea
              className="min-h-[140px]"
              placeholder="Ask about an uploaded document..."
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
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

        <div className="grid h-[calc(100vh-2rem)] gap-4">
          <Card className="space-y-4">
            <div className="flex items-center gap-2">
              <FileUp className="h-4 w-4 text-pine" />
              <h3 className="text-lg font-semibold">Document ingestion</h3>
            </div>
            <label className="flex cursor-pointer items-center justify-center rounded-[24px] border border-dashed border-ink/15 bg-paper px-4 py-8 text-center text-sm text-ink/65">
              <input accept=".txt,.md" className="hidden" type="file" onChange={(event) => void handleUpload(event)} />
              Drop `.txt` or `.md` here, or click to upload
            </label>
          </Card>

          <Card className="overflow-hidden">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-lg font-semibold">Knowledge base</h3>
              <Badge>{documents.length} docs</Badge>
            </div>
            <div className="space-y-3 overflow-y-auto pr-1">
              {documents.map((document) => (
                <div key={document.id} className="rounded-[22px] border border-ink/10 bg-white px-4 py-3">
                  <div className="text-sm font-medium">{document.filename}</div>
                  <div className="mt-1 text-xs uppercase tracking-[0.18em] text-ink/45">{document.status}</div>
                  {document.error_message ? <div className="mt-2 text-xs text-berry">{document.error_message}</div> : null}
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </main>
  );
}
