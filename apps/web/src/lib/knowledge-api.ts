import { apiUrl } from "@/lib/api-base";
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
  source_name: string;
  created_at: string;
};

export type KnowledgeDocumentStatus = {
  document_id: string;
  document_version_id: string;
  processing_state: "processing" | "searchable" | "failed";
};


export type KnowledgeWorkspaceDocument = {
  document_id: string;
  document_version_id: string;
  source_name: string;
  content_type: string;
  processing_state: "processing" | "searchable" | "failed";
  created_at: string;
  updated_at: string;
};

export type KnowledgeNoteSummary = {
  id: string;
  title: string;
  kind: string;
  parent_id: string | null;
  source_document_id: string | null;
  updated_at: string;
};

export type KnowledgeNoteReference = {
  id: string;
  title: string;
};

export type KnowledgeNoteDetail = {
  id: string;
  title: string;
  kind: string;
  markdown: string;
  source_markers: string[];
  source_document_id: string | null;
  source_name: string | null;
  parent: KnowledgeNoteReference | null;
  children: KnowledgeNoteReference[];
  updated_at: string;
};

export type KnowledgeCandidateNote = {
  id: string;
  ordinal: number;
  candidate_key: string;
  title: string;
  kind:
    | "chapter"
    | "section"
    | "subsection"
    | "concept"
    | "property"
    | "formula"
    | "method"
    | "example";
  parent_key: string | null;
  markdown: string;
  source_pointers: string[];
  review_state: "pending" | "accepted" | "rejected";
};

export type KnowledgeCandidateLink = {
  id: string;
  ordinal: number;
  kind: "structure" | "term";
  relation: string;
  source_key: string;
  target_key: string;
  source_pointer: string;
  occurrence: string | null;
  context: string;
  review_state: "pending" | "accepted" | "rejected";
};

export type KnowledgeCandidateBatch = {
  id: string;
  document_id: string;
  document_version_id: string;
  generation_number: number;
  state: "processing" | "needs_review" | "confirmed" | "rejected" | "failed";
  failure_code: string | null;
  notes: KnowledgeCandidateNote[];
  links: KnowledgeCandidateLink[];
  created_at: string;
  updated_at: string;
};
export type KnowledgeWorkspace = {
  knowledge_base_id: string;
  documents: KnowledgeWorkspaceDocument[];
  candidate_batch: KnowledgeCandidateBatch | null;
  notes: KnowledgeNoteSummary[];
};
export type KnowledgeGraphNode = {
  id: string;
  note_id: string | null;
  title: string;
  kind: string;
  source_pointers: string[];
};

export type KnowledgeGraphEdge = {
  id: string;
  source_id: string;
  target_id: string;
  kind: string;
  relation: string;
  source_pointer: string;
};

export type KnowledgeGraph = {
  knowledge_base_id: string;
  nodes: KnowledgeGraphNode[];
  edges: KnowledgeGraphEdge[];
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

export type KnowledgeDocumentSummary = {
  document_id: string;
  document_version_id: string;
  source_name: string;
  processing_state: "processing" | "searchable" | "failed";
  created_at: string;
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
  const response = await fetch(apiUrl(path), {
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
      apiUrl(`/api/v1/knowledge-bases/${resource(knowledgeBaseId)}/documents`),
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

  workspace(knowledgeBaseId: string, signal?: AbortSignal): Promise<KnowledgeWorkspace> {
    return requestJson(`/api/v1/knowledge-bases/${resource(knowledgeBaseId)}/workspace`, { signal });
  },

  note(
    knowledgeBaseId: string,
    noteId: string,
    signal?: AbortSignal,
  ): Promise<KnowledgeNoteDetail> {
    return requestJson(
      `/api/v1/knowledge-bases/${resource(knowledgeBaseId)}/notes/${resource(noteId)}`,
      { signal },
    );
  },

  graph(knowledgeBaseId: string, signal?: AbortSignal): Promise<KnowledgeGraph> {
    return requestJson(`/api/v1/knowledge-bases/${resource(knowledgeBaseId)}/graph`, { signal });
  },
  documentStatus(
    knowledgeBaseId: string,
    documentId: string,

    documentVersionId: string,
    signal?: AbortSignal,
  ): Promise<KnowledgeDocumentStatus> {
    return requestJson(
      `/api/v1/knowledge-bases/${resource(knowledgeBaseId)}/documents/${resource(documentId)}/versions/${resource(documentVersionId)}/status`,
      { signal },
    );
  },
  startCandidateGeneration(
    knowledgeBaseId: string,
    documentVersionId: string,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<KnowledgeCandidateBatch> {
    return requestJson(
      `/api/v1/knowledge-bases/${resource(knowledgeBaseId)}/candidate-batches`,
      {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
        body: JSON.stringify({ document_version_id: documentVersionId }),
        signal,
      },
    );
  },

  candidateBatch(
    knowledgeBaseId: string,
    batchId: string,
    signal?: AbortSignal,
  ): Promise<KnowledgeCandidateBatch> {
    return requestJson(
      `/api/v1/knowledge-bases/${resource(knowledgeBaseId)}/candidate-batches/${resource(batchId)}`,
      { signal },
    );
  },

  confirmCandidateBatch(
    knowledgeBaseId: string,
    batchId: string,
    acceptedNoteIds: string[],
    acceptedLinkIds: string[],
    signal?: AbortSignal,
  ): Promise<KnowledgeCandidateBatch> {
    return requestJson(
      `/api/v1/knowledge-bases/${resource(knowledgeBaseId)}/candidate-batches/${resource(batchId)}/confirm`,
      {
        method: "POST",
        body: JSON.stringify({
          accepted_note_ids: acceptedNoteIds,
          accepted_link_ids: acceptedLinkIds,
        }),
        signal,
      },
    );
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

  documents(knowledgeBaseId: string, signal?: AbortSignal): Promise<KnowledgeDocumentSummary[]> {
    return requestJson(`/api/v1/knowledge-bases/${resource(knowledgeBaseId)}/documents`, {
      signal,
    });
  },

  async pagePreview(
    knowledgeBaseId: string,
    citationId: string,
    signal?: AbortSignal,
  ): Promise<KnowledgePreview> {
    const response = await fetch(
      apiUrl(`/api/v1/knowledge-bases/${resource(knowledgeBaseId)}/citations/${resource(citationId)}/page`),
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
