import type { SpaceSummary } from "@/lib/api";

type ClassroomResponse = {
  id: string;
  name: string;
  space: SpaceSummary;
  membership: { user_id: string; role: string };
};

export type CreatedClassroomResponse = ClassroomResponse & {
  invite_code: string;
};

async function request<T>(path: string, body: Record<string, string>): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!response.ok) throw new Error("CLASSROOM_REQUEST_FAILED");
  return response.json() as Promise<T>;
}

export const classroomApi = {
  create: (name: string) =>
    request<CreatedClassroomResponse>("/api/v1/classrooms", { name }),
  join: (code: string) => request<ClassroomResponse>("/api/v1/classrooms/join", { code }),
};
