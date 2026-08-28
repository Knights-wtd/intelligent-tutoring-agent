import { apiUrl } from "@/lib/api-base";
export type TutorStatus = {
  configured: boolean;
  model: string;
};

export type TutorCitation = {
  id: string;
  source_name: string;
  page_number: number | null;
};

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
  readonly code: string | null;

  constructor(status: number, code: string | null = null) {
    super("Tutor request failed");
    this.name = "TutorApiError";
    this.status = status;
    this.code = code;
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
      "Content-Type": "application/json",
      ...init.headers,
    },
  });
  if (!response.ok) {
    let code: string | null = null;
    try {
      const body: unknown = await response.json();
      if (
        body !== null &&
        typeof body === "object" &&
        "detail" in body &&
        typeof (body as { detail: unknown }).detail === "string"
      ) {
        code = (body as { detail: string }).detail;
      }
    } catch {
      // Non-JSON error bodies keep the null code; the status alone still
      // selects the generic message.
    }
    throw new TutorApiError(response.status, code);
  }
  return response.json() as Promise<T>;
}

export const tutorApi = {
  status(signal?: AbortSignal): Promise<TutorStatus> {
    return requestJson("/api/v1/tutor/status", { signal });
  },

  createConversation(
    knowledgeBaseId: string,
    prompt: string,
    signal?: AbortSignal,
  ): Promise<TutorConversation> {
    return requestJson(
      `/api/v1/knowledge-bases/${resource(knowledgeBaseId)}/tutor/conversations`,
      { method: "POST", body: JSON.stringify({ prompt }), signal },
    );
  },

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

  sendMessage(
    knowledgeBaseId: string,
    conversationId: string,
    prompt: string,
    signal?: AbortSignal,
  ): Promise<TutorConversation> {
    return requestJson(
      `/api/v1/knowledge-bases/${resource(knowledgeBaseId)}/tutor/conversations/${resource(conversationId)}/messages`,
      { method: "POST", body: JSON.stringify({ prompt }), signal },
    );
  },
};
