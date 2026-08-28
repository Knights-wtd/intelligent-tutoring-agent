"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";

import {
  MAX_KNOWLEDGE_QUERY_CHARACTERS,
  MAX_KNOWLEDGE_UPLOAD_BYTES,
  MAX_SOURCE_NAME_CHARACTERS,
  knowledgeApi,
  type KnowledgeBase,
  type KnowledgeSearchResult,
  type KnowledgeCandidateBatch,
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
  processingState?: "processing" | "searchable" | "failed";
  isRefreshing?: boolean;
  statusRefreshFailed?: boolean;
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
  const [candidateBatch, setCandidateBatch] = useState<KnowledgeCandidateBatch | null>(null);
  const [acceptedCandidateNotes, setAcceptedCandidateNotes] = useState<string[]>([]);
  const [acceptedCandidateLinks, setAcceptedCandidateLinks] = useState<string[]>([]);
  const [candidateMessage, setCandidateMessage] = useState("");
  const [isGeneratingCandidates, setIsGeneratingCandidates] = useState(false);
  const [isConfirmingCandidates, setIsConfirmingCandidates] = useState(false);
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
  const statusControllersRef = useRef(new Map<string, AbortController>());
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

  const abortStatusRefresh = useCallback(() => {
    const controllers = statusControllersRef.current;
    if (controllers.size === 0) return;
    controllers.forEach((controller) => controller.abort());
    controllers.clear();
    if (!mountedRef.current) return;
    setUploadsByKnowledgeBase((current) =>
      Object.fromEntries(
        Object.entries(current).map(([knowledgeBaseId, entries]) => [
          knowledgeBaseId,
          entries.map((entry) => ({ ...entry, isRefreshing: false })),
        ]),
      ),
    );
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
      abortStatusRefresh();
      abortSearchRequest();
      abortPreviewRequest();
      disposePreviewUrl();
    };
  }, [abortPreviewRequest, abortSearchRequest, abortStatusRefresh, disposePreviewUrl]);

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
          processingState: "processing",
          statusRefreshFailed: false,
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

  async function refreshUploadStatus(
    entry: UploadEntry,
    knowledgeBaseId: string,
    contextSequence: number,
  ) {
    if (!entry.response) return;
    statusControllersRef.current.get(entry.id)?.abort();
    const controller = new AbortController();
    statusControllersRef.current.set(entry.id, controller);
    setUploadsByKnowledgeBase((current) => ({
      ...current,
      [knowledgeBaseId]: replaceUpload(current[knowledgeBaseId] ?? [], {
        ...entry,
        isRefreshing: true,
        statusRefreshFailed: false,
      }),
    }));
    try {
      const status = await knowledgeApi.documentStatus(
        knowledgeBaseId,
        entry.response.document_id,
        entry.response.document_version_id,
        controller.signal,
      );
      if (
        controller.signal.aborted ||
        !mountedRef.current ||
        contextSequence !== contextSequenceRef.current
      ) {
        return;
      }
      setUploadsByKnowledgeBase((current) => ({
        ...current,
        [knowledgeBaseId]: (current[knowledgeBaseId] ?? []).map((item) =>
          item.id === entry.id
            ? { ...item, processingState: status.processing_state, statusRefreshFailed: false }
            : item,
        ),
      }));
    } catch {
      if (
        !controller.signal.aborted &&
        mountedRef.current &&
        contextSequence === contextSequenceRef.current
      ) {
        setUploadsByKnowledgeBase((current) => ({
          ...current,
          [knowledgeBaseId]: (current[knowledgeBaseId] ?? []).map((item) =>
            item.id === entry.id ? { ...item, statusRefreshFailed: true } : item,
          ),
        }));
      }
    } finally {
      if (statusControllersRef.current.get(entry.id) === controller) {
        statusControllersRef.current.delete(entry.id);
        if (mountedRef.current && contextSequence === contextSequenceRef.current) {
          setUploadsByKnowledgeBase((current) => ({
            ...current,
            [knowledgeBaseId]: (current[knowledgeBaseId] ?? []).map((item) =>
              item.id === entry.id ? { ...item, isRefreshing: false } : item,
            ),
          }));
        }
      }
    }
  }
  function showCandidateBatch(batch: KnowledgeCandidateBatch) {
    setCandidateBatch(batch);
    setAcceptedCandidateNotes(batch.notes.map((note) => note.id));
    setAcceptedCandidateLinks(batch.links.map((link) => link.id));
    setCandidateMessage("");
  }

  async function startCandidateGeneration(entry: UploadEntry) {
    if (!entry.response || !selectedKnowledgeBaseId || isGeneratingCandidates) return;
    setIsGeneratingCandidates(true);
    setCandidateMessage("");
    try {
      // A fresh key per click: a FAILED batch must be re-generatable, not
      // replayed from the server's idempotency cache.
      const batch = await knowledgeApi.startCandidateGeneration(
        selectedKnowledgeBaseId,
        entry.response.document_version_id,
        `candidate-${entry.response.document_version_id}-${crypto.randomUUID()}`,
      );
      showCandidateBatch(batch);
    } catch {
      setCandidateMessage("知识候选暂时无法生成，请稍后重试。");
    } finally {
      setIsGeneratingCandidates(false);
    }
  }

  async function refreshCandidateBatch() {
    if (!candidateBatch || !selectedKnowledgeBaseId || isGeneratingCandidates) return;
    setIsGeneratingCandidates(true);
    setCandidateMessage("");
    try {
      showCandidateBatch(
        await knowledgeApi.candidateBatch(selectedKnowledgeBaseId, candidateBatch.id),
      );
    } catch {
      setCandidateMessage("候选状态暂时无法刷新，请重试。");
    } finally {
      setIsGeneratingCandidates(false);
    }
  }

  function toggleCandidate(
    id: string,
    selected: string[],
    setSelected: (value: string[]) => void,
  ) {
    setSelected(
      selected.includes(id) ? selected.filter((value) => value !== id) : [...selected, id],
    );
  }

  async function confirmCandidates() {
    if (
      !candidateBatch ||
      !selectedKnowledgeBaseId ||
      isConfirmingCandidates ||
      acceptedCandidateNotes.length === 0
    ) {
      return;
    }
    setIsConfirmingCandidates(true);
    setCandidateMessage("");
    try {
      const confirmed = await knowledgeApi.confirmCandidateBatch(
        selectedKnowledgeBaseId,
        candidateBatch.id,
        acceptedCandidateNotes,
        acceptedCandidateLinks,
      );
      setCandidateBatch(confirmed);
      setCandidateMessage("");
    } catch {
      setCandidateMessage("确认失败，候选内容尚未写入，请重试。");
    } finally {
      setIsConfirmingCandidates(false);
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
                    <>
                      <span>{learnerUploadState(entry)}</span>
                      <button
                        disabled={entry.isRefreshing}
                        type="button"
                        onClick={() =>
                          void refreshUploadStatus(
                            entry,
                            selectedKnowledgeBaseId,
                            contextSequenceRef.current,
                          )
                        }
                      >
                        {entry.isRefreshing ? "刷新中…" : "刷新处理状态"}
                      </button>
                      {entry.processingState === "searchable" ? (
                        <button
                          disabled={isGeneratingCandidates}
                          onClick={() => void startCandidateGeneration(entry)}
                          type="button"
                        >
                          {isGeneratingCandidates ? "生成中…" : "生成知识候选"}
                        </button>
                      ) : null}
                      {entry.statusRefreshFailed ? (
                        <span role="alert">暂时无法刷新状态，请重试。</span>
                      ) : null}
                    </>
                  ) : null}
                </div>
              ))}
            </div>
          </div>

          {candidateMessage ? <p role="alert">{candidateMessage}</p> : null}
          {candidateBatch ? (
            <section aria-label="知识候选审核">
              {candidateBatch.state === "processing" ? (
                <>
                  <p role="status">正在识别章、节、小节并生成候选…</p>
                  <button
                    disabled={isGeneratingCandidates}
                    onClick={() => void refreshCandidateBatch()}
                    type="button"
                  >
                    刷新候选状态
                  </button>
                </>
              ) : null}
              {candidateBatch.state === "failed" ? (
                <p role="alert">
                  候选生成失败：{candidateFailureMessage(candidateBatch.failure_code)}
                </p>
              ) : null}
              {candidateBatch.state === "confirmed" ? <p>已写入正式知识库</p> : null}
              {candidateBatch.state === "needs_review" ? (
                <>
                  <h3>结构候选</h3>
                  {candidateBatch.notes
                    .filter((note) =>
                      ["chapter", "section", "subsection"].includes(note.kind),
                    )
                    .map((note) => (
                      <label key={note.id}>
                        <input
                          checked={acceptedCandidateNotes.includes(note.id)}
                          onChange={() =>
                            toggleCandidate(
                              note.id,
                              acceptedCandidateNotes,
                              setAcceptedCandidateNotes,
                            )
                          }
                          type="checkbox"
                        />
                        <span>{note.title}</span>
                      </label>
                    ))}
                  <h3>知识笔记候选</h3>
                  {candidateBatch.notes
                    .filter(
                      (note) =>
                        !["chapter", "section", "subsection"].includes(note.kind),
                    )
                    .map((note) => (
                      <label key={note.id}>
                        <input
                          checked={acceptedCandidateNotes.includes(note.id)}
                          onChange={() =>
                            toggleCandidate(
                              note.id,
                              acceptedCandidateNotes,
                              setAcceptedCandidateNotes,
                            )
                          }
                          type="checkbox"
                        />
                        <span>{note.title}</span>
                      </label>
                    ))}
                  <h3>结构链接</h3>
                  {candidateBatch.links
                    .filter((link) => link.kind === "structure")
                    .map((link) => (
                      <label key={link.id}>
                        <input
                          checked={acceptedCandidateLinks.includes(link.id)}
                          onChange={() =>
                            toggleCandidate(
                              link.id,
                              acceptedCandidateLinks,
                              setAcceptedCandidateLinks,
                            )
                          }
                          type="checkbox"
                        />
                        <span>{link.context}</span>
                      </label>
                    ))}
                  <h3>重复术语链接</h3>
                  {candidateBatch.links
                    .filter((link) => link.kind === "term")
                    .map((link) => (
                      <label key={link.id}>
                        <input
                          checked={acceptedCandidateLinks.includes(link.id)}
                          onChange={() =>
                            toggleCandidate(
                              link.id,
                              acceptedCandidateLinks,
                              setAcceptedCandidateLinks,
                            )
                          }
                          type="checkbox"
                        />
                        <span>{link.context}</span>
                      </label>
                    ))}
                  <button
                    disabled={
                      isConfirmingCandidates || acceptedCandidateNotes.length === 0
                    }
                    onClick={() => void confirmCandidates()}
                    type="button"
                  >
                    {isConfirmingCandidates
                      ? "正在写入…"
                      : "确认并生成层级知识库"}
                  </button>
                </>
              ) : null}
            </section>
          ) : null}


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

function candidateFailureMessage(failureCode: string | null): string {
  switch (failureCode) {
    case "llm_unauthorized":
      return "Faro API 密钥无效。请在 .env 中配置真实的 FARO_API_KEY 并重启服务。";
    case "llm_timeout":
      return "连接 Faro 超时，请稍后重试。";
    case "llm_rate_limited":
      return "Faro 请求过于频繁，请稍后重试。";
    case "llm_network_error":
      return "无法连接 Faro 服务，请检查网络后重试。";
    case "llm_provider_unavailable":
    case "llm_provider_error":
    case "llm_response_invalid":
    case "llm_response_empty":
      return "Faro 服务暂时异常，请稍后重试。";
    default:
      return "请重新发起生成。";
  }
}

function newUploadId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

function newUploadKey(): string {
  const value = globalThis.crypto?.randomUUID?.() ?? newUploadId();
  return `web-${value}`;
}

function learnerUploadState(entry: UploadEntry): string {
  if (entry.processingState === "failed") return "处理失败";
  if (entry.processingState === "searchable") return "可搜索";
  return "处理中";
}

function citationLabel(citation: KnowledgeCitation): string {
  const page = citation.page_number;
  return page === null ? citation.source_name : `${citation.source_name} · 第 ${page} 页`;
}
