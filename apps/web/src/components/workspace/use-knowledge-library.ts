"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { knowledgeApi, type KnowledgeBase } from "@/lib/knowledge-api";

function isAbortError(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "name" in error &&
    error.name === "AbortError"
  );
}

function asError(error: unknown): Error {
  return error instanceof Error ? error : new Error("Knowledge request failed");
}

export type RemoveKnowledgeBaseResult =
  | { removed: false }
  | { removed: true; selectedKnowledgeBaseId: string | null };

export function useKnowledgeLibrary(spaceId: string) {
  const [items, setItems] = useState<KnowledgeBase[]>([]);
  const [selectedKnowledgeBaseId, setSelectedKnowledgeBaseId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);
  const [deletingKnowledgeBaseId, setDeletingKnowledgeBaseId] = useState<string | null>(null);
  const [renderedSpaceId, setRenderedSpaceId] = useState(spaceId);
  const listControllerRef = useRef<AbortController | null>(null);
  const createControllersRef = useRef(new Set<AbortController>());
  const deleteControllersRef = useRef(new Set<AbortController>());
  const generationRef = useRef(0);
  const currentSpaceIdRef = useRef(spaceId);
  const mountedRef = useRef(true);
  const itemsRef = useRef(items);
  const selectedKnowledgeBaseIdRef = useRef(selectedKnowledgeBaseId);

  if (renderedSpaceId !== spaceId) {
    setRenderedSpaceId(spaceId);
    setItems([]);
    setSelectedKnowledgeBaseId(null);
    setIsLoading(true);
    setError(null);
    setDeletingKnowledgeBaseId(null);
  }

  const startListRequest = useCallback(() => {
    const requestedSpaceId = spaceId;
    const generation = generationRef.current;
    listControllerRef.current?.abort();
    const controller = new AbortController();
    listControllerRef.current = controller;
    return {
      requestedSpaceId,
      generation,
      controller,
      result: knowledgeApi.list(requestedSpaceId, controller.signal),
    };
  }, [spaceId]);

  const consumeListRequest = useCallback(
    async (request: ReturnType<typeof startListRequest>): Promise<void> => {
      const { requestedSpaceId, generation, controller, result } = request;
      try {
        const nextItems = await result;
        if (
          controller.signal.aborted ||
          !mountedRef.current ||
          currentSpaceIdRef.current !== requestedSpaceId ||
          generationRef.current !== generation ||
          listControllerRef.current !== controller
        ) {
          return;
        }

        const selectedId = selectedKnowledgeBaseIdRef.current;
        const nextSelectedId =
          selectedId && nextItems.some((item) => item.id === selectedId)
            ? selectedId
            : (nextItems[0]?.id ?? null);
        itemsRef.current = nextItems;
        selectedKnowledgeBaseIdRef.current = nextSelectedId;
        setItems(nextItems);
        setSelectedKnowledgeBaseId(nextSelectedId);
      } catch (requestError) {
        if (
          !isAbortError(requestError) &&
          mountedRef.current &&
          currentSpaceIdRef.current === requestedSpaceId &&
          generationRef.current === generation &&
          listControllerRef.current === controller
        ) {
          setError(asError(requestError));
        }
      } finally {
        if (
          mountedRef.current &&
          currentSpaceIdRef.current === requestedSpaceId &&
          generationRef.current === generation &&
          listControllerRef.current === controller
        ) {
          setIsLoading(false);
        }
      }
    },
    [],
  );

  const requestList = useCallback(async (): Promise<void> => {
    await consumeListRequest(startListRequest());
  }, [consumeListRequest, startListRequest]);

  const refresh = useCallback(async (): Promise<void> => {
    setIsLoading(true);
    setError(null);
    await requestList();
  }, [requestList]);

  const create = useCallback(
    async (name: string): Promise<KnowledgeBase | undefined> => {
      const requestedSpaceId = spaceId;
      const generation = generationRef.current;
      const controller = new AbortController();
      createControllersRef.current.add(controller);
      setError(null);

      try {
        const created = await knowledgeApi.create(requestedSpaceId, name, controller.signal);
        if (
          controller.signal.aborted ||
          !mountedRef.current ||
          currentSpaceIdRef.current !== requestedSpaceId ||
          generationRef.current !== generation
        ) {
          return undefined;
        }

        const currentItems = itemsRef.current;
        const nextItems = currentItems.some((item) => item.id === created.id)
          ? currentItems.map((item) => (item.id === created.id ? created : item))
          : [...currentItems, created];
        itemsRef.current = nextItems;
        selectedKnowledgeBaseIdRef.current = created.id;
        setItems(nextItems);
        setSelectedKnowledgeBaseId(created.id);
        return created;
      } catch (requestError) {
        if (
          !isAbortError(requestError) &&
          mountedRef.current &&
          currentSpaceIdRef.current === requestedSpaceId &&
          generationRef.current === generation
        ) {
          setError(asError(requestError));
        }
        return undefined;
      } finally {
        createControllersRef.current.delete(controller);
      }
    },
    [spaceId],
  );

  const remove = useCallback(
    async (knowledgeBaseId: string): Promise<RemoveKnowledgeBaseResult> => {
      const requestedSpaceId = spaceId;
      const generation = generationRef.current;
      const controller = new AbortController();
      deleteControllersRef.current.add(controller);
      setDeletingKnowledgeBaseId(knowledgeBaseId);

      try {
        await knowledgeApi.remove(knowledgeBaseId, controller.signal);
        if (
          controller.signal.aborted ||
          !mountedRef.current ||
          currentSpaceIdRef.current !== requestedSpaceId ||
          generationRef.current !== generation
        ) {
          return { removed: false };
        }

        const currentItems = itemsRef.current;
        const removedIndex = currentItems.findIndex((item) => item.id === knowledgeBaseId);
        if (removedIndex < 0) {
          return { removed: true, selectedKnowledgeBaseId: selectedKnowledgeBaseIdRef.current };
        }

        const nextItems = currentItems.filter((item) => item.id !== knowledgeBaseId);
        let nextSelectedId = selectedKnowledgeBaseIdRef.current;
        if (nextSelectedId === knowledgeBaseId) {
          nextSelectedId =
            currentItems[removedIndex + 1]?.id ?? currentItems[removedIndex - 1]?.id ?? null;
        }
        itemsRef.current = nextItems;
        selectedKnowledgeBaseIdRef.current = nextSelectedId;
        setItems(nextItems);
        setSelectedKnowledgeBaseId(nextSelectedId);
        return { removed: true, selectedKnowledgeBaseId: nextSelectedId };
      } catch (requestError) {
        if (
          controller.signal.aborted ||
          !mountedRef.current ||
          currentSpaceIdRef.current !== requestedSpaceId ||
          generationRef.current !== generation ||
          isAbortError(requestError)
        ) {
          return { removed: false };
        }
        throw requestError;
      } finally {
        deleteControllersRef.current.delete(controller);
        if (
          mountedRef.current &&
          currentSpaceIdRef.current === requestedSpaceId &&
          generationRef.current === generation
        ) {
          setDeletingKnowledgeBaseId((current) =>
            current === knowledgeBaseId ? null : current,
          );
        }
      }
    },
    [spaceId],
  );

  useEffect(() => {
    mountedRef.current = true;
    currentSpaceIdRef.current = spaceId;
    generationRef.current += 1;
    itemsRef.current = [];
    selectedKnowledgeBaseIdRef.current = null;
    const createControllers = createControllersRef.current;
    const deleteControllers = deleteControllersRef.current;
    const request = startListRequest();
    void Promise.resolve().then(() => consumeListRequest(request));

    return () => {
      generationRef.current += 1;
      listControllerRef.current?.abort();
      for (const controller of createControllers) controller.abort();
      for (const controller of deleteControllers) controller.abort();
      createControllers.clear();
      deleteControllers.clear();
    };
  }, [consumeListRequest, spaceId, startListRequest]);

  useEffect(
    () => () => {
      mountedRef.current = false;
    },
    [],
  );

  const selectedKnowledgeBase = useMemo(
    () => items.find((item) => item.id === selectedKnowledgeBaseId) ?? null,
    [items, selectedKnowledgeBaseId],
  );

  const select = useCallback((knowledgeBaseId: string) => {
    selectedKnowledgeBaseIdRef.current = knowledgeBaseId;
    setSelectedKnowledgeBaseId(knowledgeBaseId);
  }, []);

  return {
    items,
    selectedKnowledgeBase,
    selectedKnowledgeBaseId,
    isLoading,
    error,
    deletingKnowledgeBaseId,
    select,
    create,
    remove,
    refresh,
  };
}
