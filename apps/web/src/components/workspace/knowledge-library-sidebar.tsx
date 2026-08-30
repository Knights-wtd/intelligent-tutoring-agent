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
  onSelect: (knowledgeBaseId: string) => void;
  onOpenGraph: (knowledgeBase: KnowledgeBase) => void;
  onCreate: (name: string) => Promise<void> | void;
  onRetry?: () => void;
  onOpenImport?: () => void;
  onOpenDueReview?: () => void;
  onSwitchSpace?: () => void;
  onOpenClassroom?: () => void;
  onOpenAccount?: () => void;
  onOpenSettings?: () => void;
};

export function KnowledgeLibrarySidebar({
  knowledgeBases,
  selectedKnowledgeBaseId,
  isLoading = false,
  error = null,
  onSelect,
  onOpenGraph,
  onCreate,
  onRetry,
  onOpenImport,
  onOpenDueReview,
  onSwitchSpace,
  onOpenClassroom,
  onOpenAccount,
  onOpenSettings,
}: KnowledgeLibrarySidebarProps) {
  const inputId = useId();
  const errorId = useId();
  const [name, setName] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);

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

  const utilityActions = [
    ["账户", onOpenAccount],
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
              return (
                <li className={styles.knowledgeBaseRow} key={knowledgeBase.id}>
                  <button
                    aria-current={selected ? "page" : undefined}
                    aria-label={"选择" + knowledgeBase.name}
                    className={styles.knowledgeBaseName}
                    onClick={() => onSelect(knowledgeBase.id)}
                    type="button"
                  >
                    {knowledgeBase.name}
                  </button>
                  <button
                    aria-label={"打开" + knowledgeBase.name + "关联图"}
                    className={styles.knowledgeGraphButton}
                    onClick={() => onOpenGraph(knowledgeBase)}
                    title={"打开《" + knowledgeBase.name + "》关联图"}
                    type="button"
                  >
                    <GraphIcon aria-hidden="true" />
                  </button>
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