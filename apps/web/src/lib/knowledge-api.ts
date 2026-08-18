export const MAX_KNOWLEDGE_BASE_NAME_CHARACTERS = 120;
export const MAX_KNOWLEDGE_QUERY_CHARACTERS = 500;
export const MAX_KNOWLEDGE_RESULTS = 20;
export const MAX_KNOWLEDGE_UPLOAD_BYTES = 100 * 1024 * 1024;
export const MAX_SOURCE_NAME_CHARACTERS = 255;

export type KnowledgeBase = {
  id: string;
  space_id: string;
  name: string;
  state: string;
  created_at: string;
  updated_at: string;
};

export type KnowledgeUpload = {
  document_id: string;
  document_version_id: string;
  ingestion_job_id: string;
  space_id: string;
  knowledge_base_id: string;
  source_name: string;
  version_number: number;
  content_sha256: string;
  content_type: string;
  document_state: string;
  version_state: string;
  job_state: string;
  created_at: string;
};

export type KnowledgeCitation = {
  id: string;
  source_name: string;
  page_number: number | null;
};

export type KnowledgeSearchResult = {
  excerpt: string;
  citation: KnowledgeCitation;
};

export type KnowledgeSearchResponse = {
  results: KnowledgeSearchResult[];
};

export type KnowledgePreview = {
  blob: Blob;
  contentType: string;
};

export class KnowledgeApiError extends Error {
  readonly status: number;

  constructor(status: number) {
    super("Knowledge request failed");
    this.name = "KnowledgeApiError";
    this.status = status;
  }
}

function resource(value: string): string {
  return encodeURIComponent(value);
}

async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...init.headers,
    },
  });
  if (!response.ok) throw new KnowledgeApiError(response.status);
  return response.json() as Promise<T>;
}

export const knowledgeApi = {
  list(spaceId: string, signal?: AbortSignal): Promise<KnowledgeBase[]> {
    return requestJson(`/api/v1/spaces/${resource(spaceId)}/knowledge-bases`, { signal });
  },

  create(spaceId: string, name: string, signal?: AbortSignal): Promise<KnowledgeBase> {
    return requestJson(`/api/v1/spaces/${resource(spaceId)}/knowledge-bases`, {
      method: "POST",
      body: JSON.stringify({ name }),
      signal,
    });
  },

  async upload(
    knowledgeBaseId: string,
    file: File,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<KnowledgeUpload> {
    const body = new FormData();
    body.append("file", file, file.name);
    const response = await fetch(
      `/api/v1/knowledge-bases/${resource(knowledgeBaseId)}/documents`,
      {
        method: "POST",
        credentials: "include",
        headers: { "Idempotency-Key": idempotencyKey },
        body,
        signal,
      },
    );
    if (!response.ok) throw new KnowledgeApiError(response.status);
    return response.json() as Promise<KnowledgeUpload>;
  },

  search(
    knowledgeBaseId: string,
    query: string,
    limit = 10,
    signal?: AbortSignal,
  ): Promise<KnowledgeSearchResponse> {
    const boundedLimit = Math.min(MAX_KNOWLEDGE_RESULTS, Math.max(1, Math.trunc(limit)));
    return requestJson(`/api/v1/knowledge-bases/${resource(knowledgeBaseId)}/search`, {
      method: "POST",
      body: JSON.stringify({ query, limit: boundedLimit }),
      signal,
    });
  },

  async pagePreview(
    knowledgeBaseId: string,
    citationId: string,
    signal?: AbortSignal,
  ): Promise<KnowledgePreview> {
    const response = await fetch(
      `/api/v1/knowledge-bases/${resource(knowledgeBaseId)}/citations/${resource(citationId)}/page`,
      {
        credentials: "include",
        headers: { Range: "bytes=0-65535" },
        signal,
      },
    );
    if (!response.ok) throw new KnowledgeApiError(response.status);
    return {
      blob: await response.blob(),
      contentType: response.headers.get("Content-Type") ?? "application/octet-stream",
    };
  },
};
