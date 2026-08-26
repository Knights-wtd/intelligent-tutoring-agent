export type ReviewItem = {
  question_id: string;
  question_version_id: string;
  question_type: string;
  prompt: string;
  attempted_at: string;
  correct: boolean;
  score_basis_points: number;
  error_type: "none" | "metacognitive" | "application";
  needs_review: boolean;
  review_due_at: string;
  review_interval_days: number;
};

export type ReviewItemsResponse = {
  items: ReviewItem[];
  next_cursor: string | null;
};

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

export const questionBankApi = {
  async listReviewItems(
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
    const response = await fetch(
      `/api/v1/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/review-items${suffix}`,
      { credentials: "include", signal },
    );
    if (!response.ok) throw new QuestionBankApiError(response.status);
    return response.json() as Promise<ReviewItemsResponse>;
  },
};
