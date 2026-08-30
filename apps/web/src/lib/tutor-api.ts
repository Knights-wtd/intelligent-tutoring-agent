import { apiUrl } from "@/lib/api-base";

export type TutorKnowledgeCitation = {
  id: string;
  kind?: "knowledge";
  source_name: string;
  page_number: number | null;
  knowledge_base_id?: string | null;
  knowledge_base_name?: string | null;
  space_id?: string | null;
  url?: null;
};

export type TutorWebCitation = {
  id: string;
  kind: "web";
  source_name: string;
  page_number: null;
  knowledge_base_id: null;
  knowledge_base_name: null;
  space_id: null;
  url: string;
};

export type TutorCitation = TutorKnowledgeCitation | TutorWebCitation;

export type TutorMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations: TutorCitation[];
  created_at: string;
};

export type TutorConversation = {
  id: string;
  knowledge_base_id: string;
  title: string;
  messages: TutorMessage[];
  created_at: string;
  updated_at: string;
};

export class TutorApiError extends Error {
  readonly status: number;

  constructor(status: number) {
    super("Legacy Tutor history request failed");
    this.name = "TutorApiError";
    this.status = status;
  }
}

function resource(value: string): string {
  return encodeURIComponent(value);
}

async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(apiUrl(path), {
    ...init,
    credentials: "include",
    headers: {
      Accept: "application/json",
      ...init.headers,
    },
  });
  if (!response.ok) throw new TutorApiError(response.status);
  return response.json() as Promise<T>;
}

/** Read-only compatibility client for legacy Tutor conversation history. */
export const tutorApi = {
  getConversation(
    knowledgeBaseId: string,
    conversationId: string,
    signal?: AbortSignal,
  ): Promise<TutorConversation> {
    return requestJson(
      `/api/v1/knowledge-bases/${resource(knowledgeBaseId)}/tutor/conversations/${resource(conversationId)}`,
      { signal },
    );
  },
};
