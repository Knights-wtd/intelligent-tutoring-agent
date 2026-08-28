"use client";

import { useCallback, useEffect, useState } from "react";

import { AuthForm } from "@/components/auth/auth-form";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";
import { api, type SpaceSummary } from "@/lib/api";

async function fetchVisibleSpaces(): Promise<SpaceSummary[]> {
  const currentUser = await api.me();
  if (!currentUser) return [];
  return api.spaces();
}

export default function HomePage() {
  const [spaces, setSpaces] = useState<SpaceSummary[] | null>(null);

  const refreshSpaces = useCallback(async () => {
    try {
      setSpaces(await fetchVisibleSpaces());
    } catch {
      setSpaces([]);
    }
  }, []);

  useEffect(() => {
    let isCurrent = true;
    void fetchVisibleSpaces().then(
      (summaries) => {
        if (isCurrent) setSpaces(summaries);
      },
      () => {
        if (isCurrent) setSpaces([]);
      },
    );
    return () => {
      isCurrent = false;
    };
  }, []);

  if (spaces === null) return null;
  if (spaces.length === 0) return <AuthForm mode="login" onAuthenticated={refreshSpaces} />;
  return (
    <WorkspaceShell
      spaces={spaces}
      onClassroomAdded={(classroomSpace) => {
        setSpaces((current) => {
          if (current === null || current.some((space) => space.id === classroomSpace.id)) {
            return current;
          }
          return [...current, classroomSpace];
        });
      }}
    />
  );
}
