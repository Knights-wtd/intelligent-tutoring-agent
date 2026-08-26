import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useWorkspaceBreakpoint } from "./use-workspace-breakpoint";

let viewportWidth = 1400;
const listeners = new Set<() => void>();

function queryMatches(query: string): boolean {
  const minimum = /min-width:\s*(\d+)px/u.exec(query)?.[1];
  const maximum = /max-width:\s*(\d+)px/u.exec(query)?.[1];
  return (
    (minimum === undefined || viewportWidth >= Number(minimum)) &&
    (maximum === undefined || viewportWidth <= Number(maximum))
  );
}

function installMatchMedia(width: number) {
  viewportWidth = width;
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: vi.fn((query: string) => ({
      matches: queryMatches(query),
      media: query,
      onchange: null,
      addEventListener: (_type: string, listener: () => void) => listeners.add(listener),
      removeEventListener: (_type: string, listener: () => void) => listeners.delete(listener),
      addListener: (listener: () => void) => listeners.add(listener),
      removeListener: (listener: () => void) => listeners.delete(listener),
      dispatchEvent: () => true,
    })),
  });
}

function resizeTo(width: number) {
  viewportWidth = width;
  for (const listener of listeners) listener();
}

afterEach(() => {
  listeners.clear();
  vi.restoreAllMocks();
});

describe("useWorkspaceBreakpoint", () => {
  it.each([
    [1400, "desktop"],
    [1100, "tablet"],
    [800, "compact"],
    [700, "mobile"],
  ] as const)("maps %ipx to %s", (width, expected) => {
    installMatchMedia(width);
    const { result } = renderHook(() => useWorkspaceBreakpoint());
    expect(result.current).toBe(expected);
  });

  it("updates when a media-query boundary changes", () => {
    installMatchMedia(1400);
    const { result } = renderHook(() => useWorkspaceBreakpoint());

    act(() => resizeTo(800));

    expect(result.current).toBe("compact");
  });
});
