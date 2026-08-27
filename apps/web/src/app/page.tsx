"use client";

import { useEffect, useState } from "react";

import { AuthForm } from "@/components/auth/auth-form";
import { WorkspaceShell } from "@/components/workspace/workspace-shell";
import { api, type SpaceSummary } from "@/lib/api";

export default function HomePage() {
  const [spaces, setSpaces] = useState<SpaceSummary[] | null>(null);

  useEffect(() => {
    let isCurrent = true;
    void api.me().then(async (currentUser) => {
      if (!isCurrent) return;
      if (!currentUser) {
        setSpaces([]);
        return;
      }
      const summaries = await api.spaces();
      if (isCurrent) setSpaces(summaries);
    }).catch(() => {
      if (isCurrent) setSpaces([]);
    });
    return () => {
      isCurrent = false;
    };
  }, []);

  if (spaces === null) return null;
  if (spaces.length === 0) return <AuthForm mode="login" />;
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
