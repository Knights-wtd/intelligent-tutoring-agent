export type LearnerQuestion = {
  question_version_id: string;
  question_type: string;
  prompt: string;
};

export type AttemptAssessment = {
  question_version_id: string;
  correct: boolean;
  score_basis_points: number;
  error_type: "none" | "metacognitive" | "application";
  needs_review: boolean;
  review_due_at: string;
  review_interval_days: number;
};

export type ReviewItem = AttemptAssessment & {
  question_id: string;
  question_version_id: string;
  question_type: string;
  prompt: string;
  attempted_at: string;
};

export type AttemptHistoryItem = AttemptAssessment & {
  question_version_id: string;
  question_type: string;
  prompt: string;
};

type PaginatedResponse<T> = {
  items: T[];
  next_cursor: string | null;
};
export type ReviewItemsResponse = PaginatedResponse<ReviewItem>;

export type ListReviewItemsOptions = {
  scope?: "all" | "due";
  limit?: number;
};

export class QuestionBankApiError extends Error {
  readonly status: number;

  constructor(status: number) {
    super("Question bank request failed");
    this.name = "QuestionBankApiError";
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
  if (!response.ok) throw new QuestionBankApiError(response.status);
  return response.json() as Promise<T>;
}

export const questionBankApi = {
  listQuestions(knowledgeBaseId: string, signal?: AbortSignal): Promise<LearnerQuestion[]> {
    return requestJson(`/api/v1/knowledge-bases/${resource(knowledgeBaseId)}/questions`, {
      signal,
    });
  },

  submitAttempt(
    knowledgeBaseId: string,
    questionVersionId: string,
    answer: string,
    idempotencyKey: string,
    signal?: AbortSignal,
  ): Promise<AttemptAssessment> {
    return requestJson(
      `/api/v1/knowledge-bases/${resource(knowledgeBaseId)}/question-versions/${resource(questionVersionId)}/attempts`,
      {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey },
        body: JSON.stringify({ answer }),
        signal,
      },
    );
  },

  listReviewItems(
    knowledgeBaseId: string,
    optionsOrSignal: ListReviewItemsOptions | AbortSignal = {},
    signal?: AbortSignal,
  ): Promise<ReviewItemsResponse> {
    let options: ListReviewItemsOptions;
    if (optionsOrSignal instanceof AbortSignal) {
      options = {};
      signal = optionsOrSignal;
    } else {
      options = optionsOrSignal;
    }
    const query = new URLSearchParams();
    if (options.scope !== undefined) query.set("scope", options.scope);
    if (options.limit !== undefined) query.set("limit", String(options.limit));
    const suffix = query.size > 0 ? `?${query.toString()}` : "";
    return requestJson(
      `/api/v1/knowledge-bases/${resource(knowledgeBaseId)}/review-items${suffix}`,
      { signal },
    );
  },

  listAttemptHistory(
    knowledgeBaseId: string,
    questionVersionId: string,
    signal?: AbortSignal,
  ): Promise<PaginatedResponse<AttemptHistoryItem>> {
    return requestJson(
      `/api/v1/knowledge-bases/${resource(knowledgeBaseId)}/question-versions/${resource(questionVersionId)}/attempt-history`,
      { signal },
    );
  },
};
