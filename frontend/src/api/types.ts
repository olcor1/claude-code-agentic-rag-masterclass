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
  chunkId?: string;
  documentId?: string;
  filename: string;
  excerpt: string;
};

export type Message = {
  id: string;
  conversation_id?: string;
  conversationId?: string;
  role: "user" | "assistant";
  content: string;
  citations: Citation[];
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

export type DocumentRecord = {
  id: string;
  user_id: string;
  filename: string;
  storage_path: string;
  status: string;
  error_message: string | null;
  created_at: string;
  updated_at: string;
};
