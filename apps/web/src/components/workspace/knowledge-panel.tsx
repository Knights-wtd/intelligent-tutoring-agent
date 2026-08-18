"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";

import {
  MAX_KNOWLEDGE_BASE_NAME_CHARACTERS,
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

type KnowledgePanelProps = {
  spaceId: string;
  spaceName: string;
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
  return <KnowledgePanelForSpace key={props.spaceId} {...props} />;
}

function KnowledgePanelForSpace({ spaceId, spaceName }: KnowledgePanelProps) {
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [selectedKnowledgeBaseId, setSelectedKnowledgeBaseId] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const [newKnowledgeBaseName, setNewKnowledgeBaseName] = useState("");
  const [createMessage, setCreateMessage] = useState("");
  const [isCreating, setIsCreating] = useState(false);
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
  const previewUrlRef = useRef<string | null>(null);
  const mountedRef = useRef(true);

  const disposePreviewUrl = useCallback(() => {
    if (previewUrlRef.current !== null) {
      URL.revokeObjectURL(previewUrlRef.current);
      previewUrlRef.current = null;
    }
  }, []);

  const clearPreview = useCallback(() => {
    previewSequenceRef.current += 1;
    disposePreviewUrl();
    setPreview(null);
    setPreviewMessage("");
    setIsOpeningPreview(false);
  }, [disposePreviewUrl]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      disposePreviewUrl();
    };
  }, [disposePreviewUrl]);

  useEffect(() => {
    const controller = new AbortController();
    let isCurrent = true;

    void knowledgeApi
      .list(spaceId, controller.signal)
      .then((items) => {
        if (!isCurrent || controller.signal.aborted) return;
        setKnowledgeBases(items);
        setSelectedKnowledgeBaseId(items[0]?.id ?? "");
        setIsLoading(false);
      })
      .catch(() => {
        if (!isCurrent || controller.signal.aborted) return;
        setIsLoading(false);
        setLoadFailed(true);
      });

    return () => {
      isCurrent = false;
      controller.abort();
    };
  }, [loadAttempt, spaceId]);

  const selectedKnowledgeBase = knowledgeBases.find(
    (knowledgeBase) => knowledgeBase.id === selectedKnowledgeBaseId,
  );
  const uploads = selectedKnowledgeBaseId
    ? (uploadsByKnowledgeBase[selectedKnowledgeBaseId] ?? [])
    : [];

  function selectKnowledgeBase(knowledgeBaseId: string) {
    if (knowledgeBaseId === selectedKnowledgeBaseId) return;
    contextSequenceRef.current += 1;
    searchSequenceRef.current += 1;
    setSelectedKnowledgeBaseId(knowledgeBaseId);
    setSearchResults([]);
    setSearchMessage("");
    setIsSearching(false);
    setSelectedFile(null);
    setUploadMessage("");
    clearPreview();
  }

  function retryLoad() {
    setIsLoading(true);
    setLoadFailed(false);
    setLoadAttempt((attempt) => attempt + 1);
  }

  async function createKnowledgeBase(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedName = newKnowledgeBaseName.trim();
    if (!normalizedName) {
      setCreateMessage("请输入知识库名称。");
      return;
    }
    if (normalizedName.length > MAX_KNOWLEDGE_BASE_NAME_CHARACTERS) {
      setCreateMessage("知识库名称不能超过 120 个字符。");
      return;
    }

    const contextSequence = contextSequenceRef.current;
    const controller = new AbortController();
    setIsCreating(true);
    setCreateMessage("");
    try {
      const created = await knowledgeApi.create(spaceId, normalizedName, controller.signal);
      if (!mountedRef.current) return;
      setKnowledgeBases((current) => [...current, created]);
      if (contextSequence === contextSequenceRef.current) {
        selectKnowledgeBase(created.id);
        setNewKnowledgeBaseName("");
      }
    } catch {
      if (mountedRef.current && contextSequence === contextSequenceRef.current) {
        setCreateMessage("暂时无法创建知识库，请重试。");
      }
    } finally {
      if (mountedRef.current) setIsCreating(false);
    }
  }

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

    setUploadMessage("");
    setUploadsByKnowledgeBase((current) => ({
      ...current,
      [knowledgeBaseId]: replaceUpload(current[knowledgeBaseId] ?? [], {
        ...entry,
        status: "uploading",
      }),
    }));

    const controller = new AbortController();
    try {
      const response = await knowledgeApi.upload(
        knowledgeBaseId,
        entry.file,
        entry.idempotencyKey,
        controller.signal,
      );
      if (!mountedRef.current) return;
      setUploadsByKnowledgeBase((current) => ({
        ...current,
        [knowledgeBaseId]: replaceUpload(current[knowledgeBaseId] ?? [], {
          ...entry,
          status: "accepted",
          response,
        }),
      }));
      if (contextSequence === contextSequenceRef.current) setSelectedFile(null);
    } catch {
      if (!mountedRef.current) return;
      setUploadsByKnowledgeBase((current) => ({
        ...current,
        [knowledgeBaseId]: replaceUpload(current[knowledgeBaseId] ?? [], {
          ...entry,
          status: "failed",
        }),
      }));
    }
  }

  function submitUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
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

    const sequence = ++searchSequenceRef.current;
    const knowledgeBaseId = selectedKnowledgeBase.id;
    const contextSequence = contextSequenceRef.current;
    const controller = new AbortController();
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
        mountedRef.current &&
        sequence === searchSequenceRef.current &&
        contextSequence === contextSequenceRef.current
      ) {
        setSearchMessage("搜索暂时不可用，请重试。");
      }
    } finally {
      if (
        mountedRef.current &&
        sequence === searchSequenceRef.current &&
        contextSequence === contextSequenceRef.current
      ) {
        setIsSearching(false);
      }
    }
  }

  async function openPreview(result: KnowledgeSearchResult) {
    if (!selectedKnowledgeBase) return;
    const sequence = ++previewSequenceRef.current;
    const knowledgeBaseId = selectedKnowledgeBase.id;
    const contextSequence = contextSequenceRef.current;
    const label = citationLabel(result);
    const controller = new AbortController();
    disposePreviewUrl();
    setPreview(null);
    setPreviewMessage("");
    setIsOpeningPreview(true);
    try {
      const response = await knowledgeApi.pagePreview(
        knowledgeBaseId,
        result.citation.id,
        controller.signal,
      );
      if (
        !mountedRef.current ||
        sequence !== previewSequenceRef.current ||
        contextSequence !== contextSequenceRef.current
      ) {
        return;
      }
      if (response.contentType.toLowerCase().startsWith("text/")) {
        const text = await response.blob.text();
        if (
          !mountedRef.current ||
          sequence !== previewSequenceRef.current ||
          contextSequence !== contextSequenceRef.current
        ) {
          return;
        }
        setPreview({ kind: "text", label, text });
      } else if (response.contentType.toLowerCase().startsWith("image/")) {
        const url = URL.createObjectURL(response.blob);
        previewUrlRef.current = url;
        setPreview({ kind: "image", label, url });
      } else {
        setPreview({ kind: "unsupported", label });
      }
    } catch {
      if (
        mountedRef.current &&
        sequence === previewSequenceRef.current &&
        contextSequence === contextSequenceRef.current
      ) {
        setPreviewMessage("原页暂时无法打开，请重试。");
      }
    } finally {
      if (
        mountedRef.current &&
        sequence === previewSequenceRef.current &&
        contextSequence === contextSequenceRef.current
      ) {
        setIsOpeningPreview(false);
      }
    }
  }

  return (
    <section aria-label="知识库面板" className={styles.knowledgePanel}>
      <header className={styles.knowledgeHeader}>
        <div>
          <span className={styles.eyebrow}>{spaceName}</span>
          <h2>知识库</h2>
        </div>
        {loadFailed ? (
          <button type="button" onClick={retryLoad}>
            重试知识库
          </button>
        ) : null}
      </header>

      {isLoading ? <p role="status">正在加载知识库…</p> : null}
      {loadFailed ? <p>知识库暂时无法加载。</p> : null}

      {!isLoading && !loadFailed ? (
        <>
          <nav aria-label="知识库列表" className={styles.knowledgeBaseList}>
            {knowledgeBases.length === 0 ? <span>当前空间还没有知识库。</span> : null}
            {knowledgeBases.map((knowledgeBase) => (
              <button
                aria-pressed={knowledgeBase.id === selectedKnowledgeBaseId}
                key={knowledgeBase.id}
                onClick={() => selectKnowledgeBase(knowledgeBase.id)}
                type="button"
              >
                {knowledgeBase.name}
              </button>
            ))}
          </nav>

          <form className={styles.inlineForm} onSubmit={createKnowledgeBase}>
            <label>
              知识库名称
              <input
                aria-label="知识库名称"
                maxLength={MAX_KNOWLEDGE_BASE_NAME_CHARACTERS}
                onChange={(event) => setNewKnowledgeBaseName(event.target.value)}
                value={newKnowledgeBaseName}
              />
            </label>
            <button disabled={isCreating} type="submit">
              {isCreating ? "创建中…" : "创建知识库"}
            </button>
          </form>
          {createMessage ? <p role="alert">{createMessage}</p> : null}

          <div aria-label="知识库内容层级" className={styles.knowledgeHierarchy}>
            <strong>知识库</strong>
            <span className={styles.hierarchyBranch}>
              {selectedKnowledgeBase?.name ?? "请选择知识库"}
            </span>
            <strong className={styles.hierarchyBranch}>教材/练习</strong>
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
            <button disabled={!selectedKnowledgeBase} type="submit">
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
                  <span>{citationLabel(result)}</span>
                  <button
                    disabled={isOpeningPreview}
                    onClick={() => void openPreview(result)}
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
      ) : null}
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
  if (states.slice(0, 2).some((state) => state === "READY" || state === "ACTIVE")) {
    return "可搜索";
  }
  return "处理中";
}

function citationLabel(result: KnowledgeSearchResult): string {
  const page = result.citation.page_number;
  return page === null
    ? result.citation.source_name
    : `${result.citation.source_name} · 第 ${page} 页`;
}
