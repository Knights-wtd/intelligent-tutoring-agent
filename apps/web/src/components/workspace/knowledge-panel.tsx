"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";

import {
  MAX_KNOWLEDGE_QUERY_CHARACTERS,
  MAX_KNOWLEDGE_UPLOAD_BYTES,
  MAX_SOURCE_NAME_CHARACTERS,
  knowledgeApi,
  type KnowledgeBase,
  type KnowledgeSearchResult,
  type KnowledgeUpload,
} from "@/lib/knowledge-api";

import styles from "./workspace-shell.module.css";

const SUPPORTED_SOURCE = /\.(?:pdf|docx|md|jpe?g|png|zip)$/i;

export type KnowledgeCitation = {
  id: string;
  source_name: string;
  page_number: number | null;
};

export type KnowledgeCitationRequest = {
  citation: KnowledgeCitation;
  requestId: number;
};

type KnowledgePanelProps = {
  spaceName: string;
  knowledgeBase: KnowledgeBase;
  citationRequest?: KnowledgeCitationRequest;
  onCitationRequestHandled?: (requestId: number) => void;
};

type UploadEntry = {
  id: string;
  file: File;
  idempotencyKey: string;
  status: "uploading" | "failed" | "accepted";
  response?: KnowledgeUpload;
};

type PreviewState =
  | { kind: "text"; label: string; text: string }
  | { kind: "image"; label: string; url: string }
  | { kind: "unsupported"; label: string };

export function KnowledgePanel(props: KnowledgePanelProps) {
  return <KnowledgePanelForKnowledgeBase key={props.knowledgeBase.id} {...props} />;
}

function KnowledgePanelForKnowledgeBase({
  spaceName,
  knowledgeBase,
  citationRequest,
  onCitationRequestHandled,
}: KnowledgePanelProps) {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [uploadMessage, setUploadMessage] = useState("");
  const [uploadsByKnowledgeBase, setUploadsByKnowledgeBase] = useState<
    Record<string, UploadEntry[]>
  >({});
  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState<KnowledgeSearchResult[]>([]);
  const [searchMessage, setSearchMessage] = useState("");
  const [isSearching, setIsSearching] = useState(false);
  const [preview, setPreview] = useState<PreviewState | null>(null);
  const [previewMessage, setPreviewMessage] = useState("");
  const [isOpeningPreview, setIsOpeningPreview] = useState(false);
  const contextSequenceRef = useRef(0);
  const searchSequenceRef = useRef(0);
  const previewSequenceRef = useRef(0);
  const lastCitationRequestIdRef = useRef<number | null>(null);
  const previewUrlRef = useRef<string | null>(null);
  const searchControllerRef = useRef<AbortController | null>(null);
  const previewControllerRef = useRef<AbortController | null>(null);
  const activeUploadRef = useRef<
    | { entry: UploadEntry; knowledgeBaseId: string; controller: AbortController }
    | null
  >(null);
  const mountedRef = useRef(true);
  const [isUploading, setIsUploading] = useState(false);

  const disposePreviewUrl = useCallback(() => {
    if (previewUrlRef.current !== null) {
      URL.revokeObjectURL(previewUrlRef.current);
      previewUrlRef.current = null;
    }
  }, []);

  const abortSearchRequest = useCallback(() => {
    const controller = searchControllerRef.current;
    if (controller !== null) {
      searchControllerRef.current = null;
      controller.abort();
    }
  }, []);

  const abortPreviewRequest = useCallback(() => {
    const controller = previewControllerRef.current;
    if (controller !== null) {
      previewControllerRef.current = null;
      controller.abort();
    }
  }, []);

  const clearPreview = useCallback(() => {
    abortPreviewRequest();
    previewSequenceRef.current += 1;
    disposePreviewUrl();
    setPreview(null);
    setPreviewMessage("");
    setIsOpeningPreview(false);
  }, [abortPreviewRequest, disposePreviewUrl]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      activeUploadRef.current?.controller.abort();
      abortSearchRequest();
      abortPreviewRequest();
      disposePreviewUrl();
    };
  }, [abortPreviewRequest, abortSearchRequest, disposePreviewUrl]);

  const selectedKnowledgeBase = knowledgeBase;
  const selectedKnowledgeBaseId = knowledgeBase.id;
  const uploads = selectedKnowledgeBaseId
    ? (uploadsByKnowledgeBase[selectedKnowledgeBaseId] ?? [])
    : [];

  function validateFile(file: File): string | null {
    if (!file.name || file.name.length > MAX_SOURCE_NAME_CHARACTERS) {
      return "文件名不能超过 255 个字符。";
    }
    if (!SUPPORTED_SOURCE.test(file.name)) {
      return "请选择 PDF、DOCX、Markdown、JPG、PNG 或 Obsidian ZIP。";
    }
    if (file.size <= 0) return "不能上传空文件。";
    if (file.size > MAX_KNOWLEDGE_UPLOAD_BYTES) return "单个文件不能超过 100 MB。";
    return null;
  }

  async function upload(
    entry: UploadEntry,
    knowledgeBaseId: string,
    contextSequence: number,
  ) {
    if (activeUploadRef.current !== null) return;

    const controller = new AbortController();
    const activeUpload = { entry, knowledgeBaseId, controller };
    activeUploadRef.current = activeUpload;
    setIsUploading(true);
    setUploadMessage("");
    setUploadsByKnowledgeBase((current) => ({
      ...current,
      [knowledgeBaseId]: replaceUpload(current[knowledgeBaseId] ?? [], {
        ...entry,
        status: "uploading",
      }),
    }));

    try {
      const response = await knowledgeApi.upload(
        knowledgeBaseId,
        entry.file,
        entry.idempotencyKey,
        controller.signal,
      );
      if (
        !mountedRef.current ||
        controller.signal.aborted ||
        contextSequence !== contextSequenceRef.current
      ) {
        return;
      }
      setUploadsByKnowledgeBase((current) => ({
        ...current,
        [knowledgeBaseId]: replaceUpload(current[knowledgeBaseId] ?? [], {
          ...entry,
          status: "accepted",
          response,
        }),
      }));
      setSelectedFile((current) => (current === entry.file ? null : current));
    } catch {
      if (
        controller.signal.aborted ||
        !mountedRef.current ||
        contextSequence !== contextSequenceRef.current
      ) {
        return;
      }
      setUploadsByKnowledgeBase((current) => ({
        ...current,
        [knowledgeBaseId]: replaceUpload(current[knowledgeBaseId] ?? [], {
          ...entry,
          status: "failed",
        }),
      }));
    } finally {
      if (activeUploadRef.current === activeUpload) {
        activeUploadRef.current = null;
        if (mountedRef.current && !controller.signal.aborted) setIsUploading(false);
      }
    }
  }

  function submitUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (activeUploadRef.current !== null) return;
    if (!selectedKnowledgeBase || !selectedFile) {
      setUploadMessage("请先选择知识库和文件。");
      return;
    }
    const validationMessage = validateFile(selectedFile);
    if (validationMessage) {
      setUploadMessage(validationMessage);
      return;
    }
    const entry: UploadEntry = {
      id: newUploadId(),
      file: selectedFile,
      idempotencyKey: newUploadKey(),
      status: "uploading",
    };
    void upload(entry, selectedKnowledgeBase.id, contextSequenceRef.current);
  }

  async function search(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedQuery = query.trim().replace(/\s+/g, " ");
    if (!selectedKnowledgeBase) {
      setSearchMessage("请先选择知识库。");
      return;
    }
    if (!normalizedQuery) {
      setSearchMessage("请输入搜索内容。");
      return;
    }
    if (normalizedQuery.length > MAX_KNOWLEDGE_QUERY_CHARACTERS) {
      setSearchMessage("搜索内容不能超过 500 个字符。");
      return;
    }

    abortSearchRequest();
    const sequence = ++searchSequenceRef.current;
    const knowledgeBaseId = selectedKnowledgeBase.id;
    const contextSequence = contextSequenceRef.current;
    const controller = new AbortController();
    searchControllerRef.current = controller;
    setIsSearching(true);
    setSearchMessage("");
    setSearchResults([]);
    clearPreview();
    try {
      const response = await knowledgeApi.search(
        knowledgeBaseId,
        normalizedQuery,
        10,
        controller.signal,
      );
      if (
        !mountedRef.current ||
        sequence !== searchSequenceRef.current ||
        contextSequence !== contextSequenceRef.current
      ) {
        return;
      }
      setSearchResults(response.results);
      if (response.results.length === 0) {
        setSearchMessage("没有找到相关内容，资料可能仍在处理中。");
      }
    } catch {
      if (
        !controller.signal.aborted &&
        mountedRef.current &&
        sequence === searchSequenceRef.current &&
        contextSequence === contextSequenceRef.current
      ) {
        setSearchMessage("搜索暂时不可用，请重试。");
      }
    } finally {
      if (searchControllerRef.current === controller) searchControllerRef.current = null;
      if (
        !controller.signal.aborted &&
        mountedRef.current &&
        sequence === searchSequenceRef.current &&
        contextSequence === contextSequenceRef.current
      ) {
        setIsSearching(false);
      }
    }
  }

  const openPreview = useCallback(
    async (citation: KnowledgeCitation) => {
      if (!selectedKnowledgeBase) return;
      abortPreviewRequest();
      const sequence = ++previewSequenceRef.current;
      const knowledgeBaseId = selectedKnowledgeBase.id;
      const contextSequence = contextSequenceRef.current;
      const label = citationLabel(citation);
      const controller = new AbortController();
      previewControllerRef.current = controller;
      disposePreviewUrl();
      setPreview(null);
      setPreviewMessage("");
      setIsOpeningPreview(true);
      try {
        const response = await knowledgeApi.pagePreview(
          knowledgeBaseId,
          citation.id,
          controller.signal,
        );
        if (
          !mountedRef.current ||
          controller.signal.aborted ||
          sequence !== previewSequenceRef.current ||
          contextSequence !== contextSequenceRef.current
        ) {
          return;
        }
        if (response.contentType.toLowerCase().startsWith("text/")) {
          const text = await response.blob.text();
          if (
            !mountedRef.current ||
            controller.signal.aborted ||
            sequence !== previewSequenceRef.current ||
            contextSequence !== contextSequenceRef.current
          ) {
            return;
          }
          setPreview({ kind: "text", label, text });
        } else if (response.contentType.toLowerCase().startsWith("image/")) {
          const url = URL.createObjectURL(response.blob);
          if (
            !mountedRef.current ||
            controller.signal.aborted ||
            sequence !== previewSequenceRef.current ||
            contextSequence !== contextSequenceRef.current
          ) {
            URL.revokeObjectURL(url);
            return;
          }
          previewUrlRef.current = url;
          setPreview({ kind: "image", label, url });
        } else {
          setPreview({ kind: "unsupported", label });
        }
      } catch {
        if (
          !controller.signal.aborted &&
          mountedRef.current &&
          sequence === previewSequenceRef.current &&
          contextSequence === contextSequenceRef.current
        ) {
          setPreviewMessage("原页暂时无法打开，请重试。");
        }
      } finally {
        if (previewControllerRef.current === controller) previewControllerRef.current = null;
        if (
          !controller.signal.aborted &&
          mountedRef.current &&
          sequence === previewSequenceRef.current &&
          contextSequence === contextSequenceRef.current
        ) {
          setIsOpeningPreview(false);
        }
      }
    },
    [abortPreviewRequest, disposePreviewUrl, selectedKnowledgeBase],
  );

  useEffect(() => {
    if (
      citationRequest === undefined ||
      lastCitationRequestIdRef.current === citationRequest.requestId
    ) {
      return;
    }
    lastCitationRequestIdRef.current = citationRequest.requestId;
    onCitationRequestHandled?.(citationRequest.requestId);
    void openPreview(citationRequest.citation);
  }, [citationRequest, onCitationRequestHandled, openPreview]);

  return (
    <section aria-label="知识库面板" className={styles.knowledgePanel}>
      <header className={styles.knowledgeHeader}>
        <div>
          <span className={styles.eyebrow}>{spaceName}</span>
          <h2>知识库</h2>
        </div>
      </header>

      <>
          <div aria-label="知识库内容层级" className={styles.knowledgeHierarchy}>
            <strong>知识库</strong>
            <span>当前知识库：{selectedKnowledgeBase?.name ?? "请选择知识库"}</span>
            <strong className={styles.hierarchyBranch}>教材/练习</strong>
            <strong className={styles.hierarchyBranch}>文件</strong>
            <div className={styles.hierarchyFiles}>
              {uploads.length === 0 ? <span>尚未上传文件</span> : null}
              {uploads.map((entry) => (
                <div className={styles.fileState} key={entry.id}>
                  <span>{entry.file.name}</span>
                  {entry.status === "uploading" ? (
                    <span role="status">正在上传 {entry.file.name}</span>
                  ) : null}
                  {entry.status === "failed" ? (
                    <>
                      <span>上传失败，请重试。</span>
                      <button
                        disabled={isUploading}
                        type="button"
                        onClick={() =>
                          void upload(entry, selectedKnowledgeBaseId, contextSequenceRef.current)
                        }
                      >
                        重试上传
                      </button>
                    </>
                  ) : null}
                  {entry.status === "accepted" ? (
                    <span>{learnerUploadState(entry.response)}</span>
                  ) : null}
                </div>
              ))}
            </div>
          </div>

          <form className={styles.inlineForm} onSubmit={submitUpload}>
            <label>
              选择学习资料
              <input
                accept=".pdf,.docx,.md,.jpg,.jpeg,.png,.zip"
                aria-label="选择学习资料"
                onChange={(event) => {
                  setSelectedFile(event.target.files?.[0] ?? null);
                  setUploadMessage("");
                }}
                type="file"
              />
            </label>
            <button disabled={!selectedKnowledgeBase || isUploading} type="submit">
              上传文件
            </button>
          </form>
          {uploadMessage ? <p role="alert">{uploadMessage}</p> : null}

          <form className={styles.searchForm} onSubmit={search}>
            <label>
              搜索知识库
              <input
                aria-label="搜索知识库"
                maxLength={MAX_KNOWLEDGE_QUERY_CHARACTERS}
                onChange={(event) => setQuery(event.target.value)}
                value={query}
              />
            </label>
            <button disabled={!selectedKnowledgeBase || isSearching} type="submit">
              {isSearching ? "搜索中…" : "搜索"}
            </button>
          </form>
          {searchMessage ? <p role="status">{searchMessage}</p> : null}

          {searchResults.length > 0 ? (
            <ol aria-label="知识库搜索结果" className={styles.searchResults}>
              {searchResults.map((result) => (
                <li key={result.citation.id}>
                  <p>{result.excerpt}</p>
                  <span>{citationLabel(result.citation)}</span>
                  <button
                    disabled={isOpeningPreview}
                    onClick={() => void openPreview(result.citation)}
                    type="button"
                  >
                    打开原页
                  </button>
                </li>
              ))}
            </ol>
          ) : null}

          {previewMessage ? <p role="alert">{previewMessage}</p> : null}
          {preview ? (
            <section aria-label="引用原页预览" className={styles.preview}>
              <header>
                <strong>{preview.label}</strong>
                <button type="button" onClick={clearPreview}>
                  关闭预览
                </button>
              </header>
              {preview.kind === "text" ? <pre>{preview.text}</pre> : null}
              {preview.kind === "image" ? (
                // Blob-backed source previews cannot use Next.js image optimization.
                // eslint-disable-next-line @next/next/no-img-element
                <img alt={preview.label} src={preview.url} />
              ) : null}
              {preview.kind === "unsupported" ? (
                <p>该原页格式暂不支持在此预览。</p>
              ) : null}
            </section>
          ) : null}
      </>
    </section>
  );
}

function replaceUpload(entries: UploadEntry[], next: UploadEntry): UploadEntry[] {
  const index = entries.findIndex((entry) => entry.id === next.id);
  if (index === -1) return [...entries, next];
  return entries.map((entry) => (entry.id === next.id ? next : entry));
}

function newUploadId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

function newUploadKey(): string {
  const value = globalThis.crypto?.randomUUID?.() ?? newUploadId();
  return `web-${value}`;
}

function learnerUploadState(response?: KnowledgeUpload): string {
  if (!response) return "处理中";
  const states = [response.document_state, response.version_state, response.job_state].map((state) =>
    state.toUpperCase(),
  );
  if (states.some((state) => state === "FAILED")) return "处理失败";
  if (response.version_state.toUpperCase() === "READY" && response.job_state.toUpperCase() === "COMPLETED") {
    return "可搜索";
  }
  return "处理中";
}

function citationLabel(citation: KnowledgeCitation): string {
  const page = citation.page_number;
  return page === null ? citation.source_name : `${citation.source_name} · 第 ${page} 页`;
}
