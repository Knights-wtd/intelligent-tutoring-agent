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

type Credentials = {
  email: string;
  password: string;
};

type Registration = Credentials & {
  username: string;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });

  if (!response.ok) {
    throw new Error("API request failed");
  }

  return response.json() as Promise<T>;
}

export const api = {
  async me(): Promise<CurrentUser | null> {
    const response = await fetch("/api/v1/auth/me", { credentials: "include" });
    if (response.status === 401) {
      return null;
    }
    if (!response.ok) {
      throw new Error("API request failed");
    }
    return response.json() as Promise<CurrentUser>;
  },
  spaces: () => request<SpaceSummary[]>("/api/v1/spaces"),
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
