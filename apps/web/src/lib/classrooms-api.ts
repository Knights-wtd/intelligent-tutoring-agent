import type { SpaceSummary } from "@/lib/api";

export type ClassroomMembership = {
  user_id: string;
  role: "teacher" | "student";
};

export type Classroom = {
  id: string;
  name: string;
  space: SpaceSummary;
  membership: ClassroomMembership;
};

export type CreatedClassroom = Classroom & {
  invite_code: string;
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

export const classroomApi = {
  create: (name: string) =>
    request<CreatedClassroom>("/api/v1/classrooms", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  join: (code: string) =>
    request<Classroom>("/api/v1/classrooms/join", {
      method: "POST",
      body: JSON.stringify({ code }),
    }),
};
