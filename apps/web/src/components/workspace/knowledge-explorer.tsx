"use client";

import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  knowledgeApi,
  type KnowledgeBase,
  type KnowledgeNoteDetail,
  type KnowledgeNoteSummary,
  type KnowledgeWorkspaceDocument,
} from "@/lib/knowledge-api";

import styles from "./workspace-shell.module.css";

type KnowledgeExplorerProps = {
  knowledgeBase: KnowledgeBase;
  documents: KnowledgeWorkspaceDocument[];
  notes: KnowledgeNoteSummary[];
  initialNoteId?: string | null;
  onInitialNoteHandled?: (noteId: string) => void;
  taskContent?: ReactNode;
};

type Selection =
  | { kind: "note"; id: string }
  | { kind: "document"; id: string }
  | null;

export function KnowledgeExplorer({
  knowledgeBase,
  documents,
  notes,
  initialNoteId,
  onInitialNoteHandled,
  taskContent,
}: KnowledgeExplorerProps) {
  const [selection, setSelection] = useState<Selection>(null);
  const [noteDetail, setNoteDetail] = useState<KnowledgeNoteDetail | null>(null);
  const [noteMessage, setNoteMessage] = useState("");
  const [isLoadingNote, setIsLoadingNote] = useState(false);
  const requestRef = useRef<AbortController | null>(null);
  const noteTree = useMemo(() => buildNoteTree(notes), [notes]);
  const selectedDocument =
    selection?.kind === "document"
      ? documents.find((document) => document.document_id === selection.id) ?? null
      : null;

  const openNote = useCallback(async (noteId: string) => {
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setSelection({ kind: "note", id: noteId });
    setNoteDetail(null);
    setNoteMessage("");
    setIsLoadingNote(true);
    try {
      const detail = await knowledgeApi.note(knowledgeBase.id, noteId, controller.signal);
      if (!controller.signal.aborted) setNoteDetail(detail);
    } catch {
      if (!controller.signal.aborted) setNoteMessage("知识笔记暂时无法打开，请重试。");
    } finally {
      if (requestRef.current === controller) requestRef.current = null;
      if (!controller.signal.aborted) setIsLoadingNote(false);
    }
  }, [knowledgeBase.id]);

  useEffect(() => {
    if (!initialNoteId || !notes.some((note) => note.id === initialNoteId)) return;
    let cancelled = false;
    void Promise.resolve().then(() => {
      if (cancelled) return;
      void openNote(initialNoteId);
      onInitialNoteHandled?.(initialNoteId);
    });
    return () => {
      cancelled = true;
    };
  }, [initialNoteId, notes, onInitialNoteHandled, openNote]);

  useEffect(
    () => () => {
      requestRef.current?.abort();
    },
    [],
  );

  return (
    <div className={styles.knowledgeExplorer}>
      <nav aria-label="知识库内容层级" className={styles.explorerTreePane} role="tree">
        <div className={styles.explorerRootLabel}>{knowledgeBase.name}</div>
        {taskContent}
        <section
          aria-expanded="true"
          aria-label="知识笔记目录"
          aria-selected="false"
          className={styles.explorerFolder}
          role="treeitem"
        >
          <strong><span aria-hidden="true">▾ </span><span>知识笔记</span></strong>
          {noteTree.length === 0 ? <p>暂无正式知识笔记</p> : null}
          <ul role="group">
            {noteTree.map((node) => (
              <NoteTreeItem
                key={node.note.id}
                node={node}
                onOpen={openNote}
                selectedNoteId={selection?.kind === "note" ? selection.id : null}
              />
            ))}
          </ul>
        </section>
        <section
          aria-expanded="true"
          aria-label="原始资料目录"
          aria-selected="false"
          className={styles.explorerFolder}
          role="treeitem"
        >
          <strong><span aria-hidden="true">▾ </span><span>原始资料</span></strong>
          {documents.length === 0 ? <p>尚未上传文件</p> : null}
          <ul role="group">
            {documents.map((document) => (
              <li
                aria-selected={
                  selection?.kind === "document" && selection.id === document.document_id
                }
                key={document.document_id}
                role="treeitem"
              >
                <button
                  aria-label={`打开原始资料：${document.source_name}`}
                  className={styles.explorerFileButton}
                  onClick={() => setSelection({ kind: "document", id: document.document_id })}
                  type="button"
                >
                  <span><span aria-hidden="true">▤ </span><span>{document.source_name}</span></span>
                  <small>{documentStateLabel(document.processing_state)}</small>
                </button>
              </li>
            ))}
          </ul>
        </section>
      </nav>

      <section aria-label="知识文件查看器" className={styles.explorerViewer}>
        {selection === null ? (
          <div className={styles.explorerWelcome}>
            <span>资料浏览</span>
            <h3>选择一个知识笔记或原始资料</h3>
            <p>
              已整理 {notes.length} 篇知识笔记，收录 {documents.length} 份原始资料。
            </p>
          </div>
        ) : null}
        {isLoadingNote ? <p role="status">正在打开知识笔记…</p> : null}
        {noteMessage ? <p role="alert">{noteMessage}</p> : null}
        {selection?.kind === "note" && noteDetail ? <NoteViewer detail={noteDetail} /> : null}
        {selectedDocument ? <DocumentViewer document={selectedDocument} /> : null}
      </section>
    </div>
  );
}

type NoteTreeNode = { note: KnowledgeNoteSummary; children: NoteTreeNode[] };

function buildNoteTree(notes: KnowledgeNoteSummary[]): NoteTreeNode[] {
  const nodes = new Map(notes.map((note) => [note.id, { note, children: [] as NoteTreeNode[] }]));
  const roots: NoteTreeNode[] = [];
  for (const node of nodes.values()) {
    const parent = node.note.parent_id ? nodes.get(node.note.parent_id) : undefined;
    if (parent && !wouldCreateCycle(node.note.id, parent.note.id, nodes)) parent.children.push(node);
    else roots.push(node);
  }
  const sortNodes = (items: NoteTreeNode[]) => {
    items.sort((left, right) => left.note.title.localeCompare(right.note.title, "zh-CN"));
    items.forEach((item) => sortNodes(item.children));
  };
  sortNodes(roots);
  return roots;
}

function wouldCreateCycle(
  childId: string,
  parentId: string,
  nodes: Map<string, NoteTreeNode>,
): boolean {
  const visited = new Set<string>([childId]);
  let currentId: string | null = parentId;
  while (currentId) {
    if (visited.has(currentId)) return true;
    visited.add(currentId);
    currentId = nodes.get(currentId)?.note.parent_id ?? null;
  }
  return false;
}

function NoteTreeItem({
  node,
  onOpen,
  selectedNoteId,
}: {
  node: NoteTreeNode;
  onOpen: (id: string) => void;
  selectedNoteId: string | null;
}) {
  return (
    <li aria-selected={selectedNoteId === node.note.id} role="treeitem">
      <button
        aria-label={`打开知识笔记：${node.note.title}`}
        className={styles.explorerFileButton}
        onClick={() => void onOpen(node.note.id)}
        type="button"
      >
        <span><span aria-hidden="true">◇ </span><span>{node.note.title}.md</span></span>
      </button>
      {node.children.length > 0 ? (
        <ul role="group">
          {node.children.map((child) => (
            <NoteTreeItem
              key={child.note.id}
              node={child}
              onOpen={onOpen}
              selectedNoteId={selectedNoteId}
            />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

function NoteViewer({ detail }: { detail: KnowledgeNoteDetail }) {
  const breadcrumb = [detail.parent?.title, detail.title].filter(Boolean).join(" / ");
  return (
    <article className={styles.noteViewer}>
      <header>
        <span>{breadcrumb}</span>
        <h3>{detail.title}</h3>
        <p>
          {detail.source_name ? `来源：${detail.source_name}` : "来源资料未关联"} · 更新于
          {` ${new Date(detail.updated_at).toLocaleString("zh-CN")}`}
        </p>
      </header>
      <pre>{detail.markdown}</pre>
      <section aria-label="知识来源标记">
        <strong>来源标记</strong>
        {detail.source_markers.length > 0 ? (
          <ul>
            {detail.source_markers.map((marker) => (
              <li key={marker}>{marker}</li>
            ))}
          </ul>
        ) : (
          <p>暂无来源标记。</p>
        )}
      </section>
    </article>
  );
}

function DocumentViewer({ document }: { document: KnowledgeWorkspaceDocument }) {
  return (
    <article className={styles.documentViewer}>
      <span>原始资料</span>
      <h3>{document.source_name}</h3>
      <dl>
        <div>
          <dt>类型</dt>
          <dd>{document.content_type}</dd>
        </div>
        <div>
          <dt>状态</dt>
          <dd>{documentStateLabel(document.processing_state)}</dd>
        </div>
        <div>
          <dt>更新时间</dt>
          <dd>{new Date(document.updated_at).toLocaleString("zh-CN")}</dd>
        </div>
      </dl>
      {document.processing_state === "searchable" ? (
        <p>已完成解析，可供知识库搜索和 AI 助教使用。</p>
      ) : null}
      {document.processing_state === "processing" ? <p>资料仍在后台解析，离开页面不会中断。</p> : null}
      {document.processing_state === "failed" ? <p role="alert">资料处理失败，可重新上传后再试。</p> : null}
    </article>
  );
}

function documentStateLabel(state: KnowledgeWorkspaceDocument["processing_state"]): string {
  if (state === "searchable") return "可搜索";
  if (state === "failed") return "失败";
  return "处理中";
}
