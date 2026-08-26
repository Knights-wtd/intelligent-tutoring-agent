import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { KnowledgeBase } from "@/lib/knowledge-api";

import { useKnowledgeLibrary } from "./use-knowledge-library";

const mockKnowledgeApi = vi.hoisted(() => ({ list: vi.fn(), create: vi.fn() }));

vi.mock("@/lib/knowledge-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/knowledge-api")>();
  return { ...actual, knowledgeApi: mockKnowledgeApi };
});

const wireless: KnowledgeBase = { id: "wireless", space_id: "personal", name: "无线通信", state: "ready", created_at: "2026-08-24T00:00:00Z", updated_at: "2026-08-24T00:00:00Z" };
const digital: KnowledgeBase = { ...wireless, id: "digital", name: "数字通信" };
const notes: KnowledgeBase = { ...wireless, id: "notes", name: "学习笔记" };

beforeEach(() => {
  mockKnowledgeApi.list.mockReset();
  mockKnowledgeApi.create.mockReset();
});

describe("useKnowledgeLibrary", () => {
  it("selects the first knowledge base and preserves an explicit selection after refresh", async () => {
    mockKnowledgeApi.list.mockResolvedValueOnce([wireless, digital]).mockResolvedValueOnce([
      wireless,
      digital,
      notes,
    ]);
    const { result } = renderHook(() => useKnowledgeLibrary("personal"));

    await waitFor(() => expect(result.current.selectedKnowledgeBaseId).toBe("wireless"));
    act(() => result.current.select("digital"));
    await act(() => result.current.refresh());

    expect(result.current.selectedKnowledgeBaseId).toBe("digital");
    expect(result.current.selectedKnowledgeBase).toEqual(digital);
  });

  it("falls back to the first item when the explicit selection disappears", async () => {
    mockKnowledgeApi.list.mockResolvedValueOnce([wireless, digital]).mockResolvedValueOnce([notes]);
    const { result } = renderHook(() => useKnowledgeLibrary("personal"));

    await waitFor(() => expect(result.current.selectedKnowledgeBaseId).toBe("wireless"));
    act(() => result.current.select("digital"));
    await act(() => result.current.refresh());

    expect(result.current.selectedKnowledgeBaseId).toBe("notes");
  });

  it("adds and selects a newly created knowledge base", async () => {
    mockKnowledgeApi.list.mockResolvedValue([wireless]);
    mockKnowledgeApi.create.mockResolvedValue(notes);
    const { result } = renderHook(() => useKnowledgeLibrary("personal"));
    await waitFor(() => expect(result.current.items).toEqual([wireless]));

    await act(() => result.current.create("学习笔记"));

    expect(mockKnowledgeApi.create).toHaveBeenCalledWith("personal", "学习笔记", expect.any(AbortSignal));
    expect(result.current.items).toEqual([wireless, notes]);
    expect(result.current.selectedKnowledgeBaseId).toBe("notes");
  });

  it("aborts old list and create requests when the space changes", async () => {
    let listSignal: AbortSignal | undefined;
    let createSignal: AbortSignal | undefined;
    mockKnowledgeApi.list
      .mockImplementationOnce((_spaceId: string, signal?: AbortSignal) => {
        listSignal = signal;
        return new Promise<KnowledgeBase[]>(() => undefined);
      })
      .mockResolvedValueOnce([digital]);
    mockKnowledgeApi.create.mockImplementation(
      (_spaceId: string, _name: string, signal?: AbortSignal) => {
        createSignal = signal;
        return new Promise<KnowledgeBase>(() => undefined);
      },
    );

    const { result, rerender } = renderHook(({ spaceId }) => useKnowledgeLibrary(spaceId), {
      initialProps: { spaceId: "personal" },
    });
    act(() => {
      void result.current.create("学习笔记");
    });
    rerender({ spaceId: "classroom" });

    expect(listSignal?.aborted).toBe(true);
    expect(createSignal?.aborted).toBe(true);
    await waitFor(() => expect(result.current.items).toEqual([digital]));
    expect(result.current.selectedKnowledgeBaseId).toBe("digital");
  });

  it("ignores old list and create results that settle after the space changes", async () => {
    let resolveOldList!: (items: KnowledgeBase[]) => void;
    let resolveOldCreate!: (item: KnowledgeBase) => void;
    mockKnowledgeApi.list
      .mockImplementationOnce(
        () =>
          new Promise<KnowledgeBase[]>((resolve) => {
            resolveOldList = resolve;
          }),
      )
      .mockResolvedValueOnce([digital]);
    mockKnowledgeApi.create.mockImplementationOnce(
      () =>
        new Promise<KnowledgeBase>((resolve) => {
          resolveOldCreate = resolve;
        }),
    );

    const { result, rerender } = renderHook(({ spaceId }) => useKnowledgeLibrary(spaceId), {
      initialProps: { spaceId: "personal" },
    });
    let createRequest!: Promise<unknown>;
    act(() => {
      createRequest = result.current.create("学习笔记");
    });
    rerender({ spaceId: "classroom" });
    await waitFor(() => expect(result.current.items).toEqual([digital]));

    await act(async () => {
      resolveOldList([wireless]);
      resolveOldCreate(notes);
      await createRequest;
    });

    expect(result.current.items).toEqual([digital]);
    expect(result.current.selectedKnowledgeBaseId).toBe("digital");
  });

  it("reports real list and create errors", async () => {
    const listError = new Error("list failed");
    const createError = new Error("create failed");
    mockKnowledgeApi.list.mockRejectedValueOnce(listError).mockResolvedValueOnce([wireless]);
    mockKnowledgeApi.create.mockRejectedValueOnce(createError);
    const { result } = renderHook(() => useKnowledgeLibrary("personal"));

    await waitFor(() => expect(result.current.error).toBe(listError));
    expect(result.current.isLoading).toBe(false);

    await act(() => result.current.refresh());
    expect(result.current.error).toBeNull();
    await act(() => result.current.create("学习笔记"));
    expect(result.current.error).toBe(createError);
    expect(result.current.items).toEqual([wireless]);
  });

  it("silently ignores aborted list and create requests", async () => {
    mockKnowledgeApi.list
      .mockRejectedValueOnce(new DOMException("aborted", "AbortError"))
      .mockResolvedValueOnce([wireless]);
    mockKnowledgeApi.create.mockRejectedValueOnce(new DOMException("aborted", "AbortError"));
    const { result } = renderHook(() => useKnowledgeLibrary("personal"));

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.error).toBeNull();
    await act(() => result.current.refresh());
    await act(() => result.current.create("学习笔记"));

    expect(result.current.error).toBeNull();
    expect(result.current.items).toEqual([wireless]);
  });
  it("aborts in-flight requests when unmounted", () => {
    let listSignal: AbortSignal | undefined;
    let createSignal: AbortSignal | undefined;
    mockKnowledgeApi.list.mockImplementation((_spaceId: string, signal?: AbortSignal) => {
      listSignal = signal;
      return new Promise<KnowledgeBase[]>(() => undefined);
    });
    mockKnowledgeApi.create.mockImplementation(
      (_spaceId: string, _name: string, signal?: AbortSignal) => {
        createSignal = signal;
        return new Promise<KnowledgeBase>(() => undefined);
      },
    );

    const { result, unmount } = renderHook(() => useKnowledgeLibrary("personal"));
    act(() => {
      void result.current.create("学习笔记");
    });
    unmount();

    expect(listSignal?.aborted).toBe(true);
    expect(createSignal?.aborted).toBe(true);
  });
});