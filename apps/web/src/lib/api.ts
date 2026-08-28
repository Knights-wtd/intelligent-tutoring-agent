import { apiUrl } from "@/lib/api-base";

export type SpaceSummary = {
  id: string;
  kind: "personal" | "classroom";
  name: string;
};

export type CurrentUser = {
  user: {
    id: string;
    email: string;
    username: string;
  };
  personal_space: SpaceSummary;
};

export type EnabledModel = {
  id: string;
  provider: string;
  display_name: string;
  price_summary: string;
};

export type BillingSummary = {
  balance: string;
  currency: "CNY";
  entries: Array<{
    id: string;
    amount: string;
    entry_type: string;
    created_at: string | null;
  }>;
  total: number;
  limit: number;
  offset: number;
};

type Credentials = {
  identifier: string;
  password: string;
};

type Registration = {
  email: string;
  username: string;
  password: string;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(apiUrl(path), {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });

  if (!response.ok) {
    let detail = "API request failed";
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (typeof payload.detail === "string" && payload.detail.trim()) {
        detail = payload.detail;
      }
    } catch {
      // Keep the neutral fallback for non-JSON gateway and infrastructure errors.
    }
    throw new Error(detail);
  }

  return response.json() as Promise<T>;
}

export const api = {
  async me(): Promise<CurrentUser | null> {
    const response = await fetch(apiUrl("/api/v1/auth/me"), { credentials: "include" });
    if (response.status === 401) {
      return null;
    }
    if (!response.ok) {
      throw new Error("API request failed");
    }
    return response.json() as Promise<CurrentUser>;
  },
  spaces: () => request<SpaceSummary[]>("/api/v1/spaces"),
  models: () => request<EnabledModel[]>("/api/v1/models"),
  billingMe: () => request<BillingSummary>("/api/v1/billing/me"),
  login: (credentials: Credentials) =>
    request("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify(credentials),
    }),
  register: (registration: Registration) =>
    request("/api/v1/auth/register", {
      method: "POST",
      body: JSON.stringify(registration),
    }),
};
