"use client";

import { type FormEvent, useId, useState } from "react";

import {
  MAX_KNOWLEDGE_BASE_NAME_CHARACTERS,
  type KnowledgeBase,
} from "@/lib/knowledge-api";

import { GraphIcon, PlusIcon } from "./workspace-icons";

import styles from "./workspace-shell.module.css";

type KnowledgeLibrarySidebarProps = {
  knowledgeBases: KnowledgeBase[];
  selectedKnowledgeBaseId: string | null;
  isLoading?: boolean;
  error?: Error | null;
  deletingKnowledgeBaseId?: string | null;
  onSelect: (knowledgeBaseId: string) => void;
  onOpenGraph: (knowledgeBase: KnowledgeBase) => void;
  onCreate: (name: string) => Promise<void> | void;
  onDelete: (knowledgeBase: KnowledgeBase) => Promise<void> | void;
  onRetry?: () => void;
  onOpenImport?: () => void;
  onOpenDueReview?: () => void;
  onSwitchSpace?: () => void;
  onOpenClassroom?: () => void;
  onOpenSettings?: () => void;
};

function deleteErrorMessage(error: unknown): string {
  if (
    typeof error === "object" &&
    error !== null &&
    "status" in error &&
    error.status === 409
  ) {
    return "该知识库仍有文件处理或知识候选生成任务运行，请等待任务结束后重试。";
  }
  return "删除知识库失败，请稍后重试。";
}

export function KnowledgeLibrarySidebar({
  knowledgeBases,
  selectedKnowledgeBaseId,
  isLoading = false,
  error = null,
  deletingKnowledgeBaseId = null,
  onSelect,
  onOpenGraph,
  onCreate,
  onDelete,
  onRetry,
  onOpenImport,
  onOpenDueReview,
  onSwitchSpace,
  onOpenClassroom,
  onOpenSettings,
}: KnowledgeLibrarySidebarProps) {
  const inputId = useId();
  const errorId = useId();
  const deleteInputId = useId();
  const [name, setName] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [confirmingKnowledgeBaseId, setConfirmingKnowledgeBaseId] = useState<string | null>(null);
  const [confirmationName, setConfirmationName] = useState("");
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [submittingKnowledgeBaseId, setSubmittingKnowledgeBaseId] = useState<string | null>(null);


  const submitCreate = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const normalizedName = name.trim();
    if (!normalizedName) {
      setCreateError("请输入知识库名称。");
      return;
    }

    setCreateError(null);
    setIsCreating(true);
    try {
      await onCreate(normalizedName);
      setName("");
    } catch {
      setCreateError("创建知识库失败，请稍后重试。");
    } finally {
      setIsCreating(false);
    }
  };

  const beginDelete = (knowledgeBaseId: string) => {
    setConfirmingKnowledgeBaseId(knowledgeBaseId);
    setConfirmationName("");
    setDeleteError(null);
  };

  const cancelDelete = () => {
    setConfirmingKnowledgeBaseId(null);
    setConfirmationName("");
    setDeleteError(null);
  };

  const submitDelete = async (
    event: FormEvent<HTMLFormElement>,
    knowledgeBase: KnowledgeBase,
  ) => {
    event.preventDefault();
    if (confirmationName.trim() !== knowledgeBase.name) return;

    setDeleteError(null);
    setSubmittingKnowledgeBaseId(knowledgeBase.id);
    try {
      await onDelete(knowledgeBase);
      setConfirmingKnowledgeBaseId(null);
      setConfirmationName("");
    } catch (requestError) {
      setDeleteError(deleteErrorMessage(requestError));
    } finally {
      setSubmittingKnowledgeBaseId((current) =>
        current === knowledgeBase.id ? null : current,
      );
    }
  };

  const activeConfirmingKnowledgeBaseId = knowledgeBases.some(
    (item) => item.id === confirmingKnowledgeBaseId,
  )
    ? confirmingKnowledgeBaseId
    : null;

  const utilityActions = [
    ["导入教材", onOpenImport],
    ["待复习", onOpenDueReview],
    ["切换空间", onSwitchSpace],
    ["创建或加入班级", onOpenClassroom],
    ["设置", onOpenSettings],
  ] as const;

  return (
    <nav aria-label="知识库" className={styles.knowledgeLibrary}>
      <header className={styles.knowledgeLibraryHeader}>
        <div>
          <span className={styles.eyebrow}>个人学习库房</span>
          <strong>知识库</strong>
        </div>
        <details className={styles.knowledgeCreateDetails}>
          <summary>
            <PlusIcon aria-hidden="true" />
            新建知识库
          </summary>
          <form className={styles.knowledgeCreateForm} onSubmit={submitCreate}>
            <label htmlFor={inputId}>知识库名称</label>
            <input
              aria-describedby={createError ? errorId : undefined}
              aria-invalid={createError ? "true" : undefined}
              disabled={isCreating}
              id={inputId}
              maxLength={MAX_KNOWLEDGE_BASE_NAME_CHARACTERS}
              onChange={(event) => {
                setName(event.target.value);
                if (createError) setCreateError(null);
              }}
              value={name}
            />
            {createError ? (
              <p className={styles.knowledgeCreateError} id={errorId} role="alert">
                {createError}
              </p>
            ) : null}
            <button disabled={isCreating} type="submit">
              {isCreating ? "正在创建…" : "创建知识库"}
            </button>
          </form>
        </details>
      </header>

      <div className={styles.knowledgeLibraryBody}>
        {isLoading ? (
          <p className={styles.knowledgeLibraryStatus} role="status">
            正在加载知识库…
          </p>
        ) : error ? (
          <div className={styles.knowledgeLibraryError} role="alert">
            <p>知识库加载失败，请稍后重试。</p>
            {onRetry ? (
              <button onClick={onRetry} type="button">
                重试加载知识库
              </button>
            ) : null}
          </div>
        ) : knowledgeBases.length === 0 ? (
          <p className={styles.knowledgeLibraryStatus}>还没有知识库</p>
        ) : (
          <ul className={styles.knowledgeBaseList}>
            {knowledgeBases.map((knowledgeBase) => {
              const selected = knowledgeBase.id === selectedKnowledgeBaseId;
              const confirming = knowledgeBase.id === activeConfirmingKnowledgeBaseId;
              const isDeleting =
                knowledgeBase.id === deletingKnowledgeBaseId ||
                knowledgeBase.id === submittingKnowledgeBaseId;
              const canConfirm = confirmationName.trim() === knowledgeBase.name;
              return (
                <li className={styles.knowledgeBaseItem} key={knowledgeBase.id}>
                  <div className={styles.knowledgeBaseRow}>
                    <button
                      aria-current={selected ? "page" : undefined}
                      aria-label={"选择" + knowledgeBase.name}
                      className={styles.knowledgeBaseName}
                      disabled={isDeleting}
                      onClick={() => onSelect(knowledgeBase.id)}
                      type="button"
                    >
                      {knowledgeBase.name}
                    </button>
                    <button
                      aria-label={"打开" + knowledgeBase.name + "关联图"}
                      className={styles.knowledgeGraphButton}
                      disabled={isDeleting}
                      onClick={() => onOpenGraph(knowledgeBase)}
                      title={"打开《" + knowledgeBase.name + "》关联图"}
                      type="button"
                    >
                      <GraphIcon aria-hidden="true" />
                    </button>
                    <button
                      aria-expanded={confirming}
                      aria-label={"删除" + knowledgeBase.name}
                      className={styles.knowledgeDeleteButton}
                      disabled={Boolean(deletingKnowledgeBaseId || submittingKnowledgeBaseId)}
                      onClick={() => (confirming ? cancelDelete() : beginDelete(knowledgeBase.id))}
                      type="button"
                    >
                      删除
                    </button>
                  </div>
                  {confirming ? (
                    <form
                      aria-label={"确认删除" + knowledgeBase.name}
                      className={styles.knowledgeDeleteConfirm}
                      onSubmit={(event) => void submitDelete(event, knowledgeBase)}
                      role="group"
                    >
                      <strong>永久删除“{knowledgeBase.name}”？</strong>
                      <p>相关文档、笔记、候选和学习记录将被删除，此操作不可撤销。</p>
                      <label htmlFor={deleteInputId}>输入知识库名称“{knowledgeBase.name}”以确认</label>
                      <input
                        aria-label={"输入知识库名称" + knowledgeBase.name + "以确认"}
                        autoComplete="off"
                        disabled={isDeleting}
                        id={deleteInputId}
                        onChange={(event) => {
                          setConfirmationName(event.target.value);
                          if (deleteError) setDeleteError(null);
                        }}
                        value={confirmationName}
                      />
                      {deleteError ? (
                        <p className={styles.knowledgeDeleteError} role="alert">
                          {deleteError}
                        </p>
                      ) : null}
                      <div className={styles.knowledgeDeleteActions}>
                        <button disabled={isDeleting} onClick={cancelDelete} type="button">
                          取消
                        </button>
                        <button
                          aria-label={"永久删除" + knowledgeBase.name}
                          disabled={!canConfirm || isDeleting}
                          type="submit"
                        >
                          {isDeleting ? "正在删除…" : "永久删除"}
                        </button>
                      </div>
                    </form>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {utilityActions.some(([, callback]) => callback) ? (
        <footer className={styles.knowledgeLibraryFooter}>
          {utilityActions.map(([label, callback]) =>
            callback ? (
              <button key={label} onClick={callback} type="button">
                {label}
              </button>
            ) : null,
          )}
        </footer>
      ) : null}
    </nav>
  );
}
