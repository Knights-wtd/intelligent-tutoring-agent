"use client";

import { useSyncExternalStore } from "react";

export type WorkspaceBreakpoint = "desktop" | "tablet" | "compact" | "mobile";

const breakpointQueries: ReadonlyArray<readonly [WorkspaceBreakpoint, string]> = [
  ["desktop", "(min-width: 1280px)"],
  ["tablet", "(min-width: 960px) and (max-width: 1279px)"],
  ["compact", "(min-width: 720px) and (max-width: 959px)"],
  ["mobile", "(max-width: 719px)"],
];

function getBreakpointSnapshot(): WorkspaceBreakpoint {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return "desktop";
  }

  return (
    breakpointQueries.find(([, query]) => window.matchMedia(query).matches)?.[0] ?? "desktop"
  );
}

function subscribeToBreakpointChanges(onStoreChange: () => void): () => void {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return () => undefined;
  }

  const mediaQueries = breakpointQueries.map(([, query]) => window.matchMedia(query));
  for (const mediaQuery of mediaQueries) {
    mediaQuery.addEventListener("change", onStoreChange);
  }
  return () => {
    for (const mediaQuery of mediaQueries) {
      mediaQuery.removeEventListener("change", onStoreChange);
    }
  };
}

export function useWorkspaceBreakpoint(): WorkspaceBreakpoint {
  return useSyncExternalStore(
    subscribeToBreakpointChanges,
    getBreakpointSnapshot,
    () => "desktop",
  );
}