"use client";

import {
  type FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { Group, Panel, Separator } from "react-resizable-panels";

import { type SpaceSummary } from "@/lib/api";
import { apiUrl } from "@/lib/api-base";
import { classroomApi } from "@/lib/classrooms-api";
import type { KnowledgeBase } from "@/lib/knowledge-api";

import { AccountPanel } from "./account-panel";
import { AgentPanel, type AgentPanelCitationTarget } from "./agent-panel";
import { KnowledgeGraphPanel } from "./knowledge-graph-panel";
import { KnowledgeLibrarySidebar } from "./knowledge-library-sidebar";
import { KnowledgePanel } from "./knowledge-panel";
import { QuestionBankPanel } from "./question-bank-panel";
import { StudyDashboard } from "./study-dashboard";
import { useKnowledgeLibrary } from "./use-knowledge-library";
import { useWorkspaceBreakpoint } from "./use-workspace-breakpoint";
import {
  initialWorkspaceTabs,
  reduceWorkspaceTabs,
  type WorkspaceTab,
  type WorkspaceTabsAction,
  type WorkspaceTabsState,
} from "./workspace-tabs";
import {
  readWorkspacePreference,
  writeWorkspacePreference,
} from "./workspace-preferences";

import styles from "./workspace-shell.module.css";

const exampleSpaces: SpaceSummary[] = [
  { id: "personal", kind: "personal", name: "我的空间" },
  { id: "math", kind: "classroom", name: "七年级数学" },
];

const fixedTabIds = new Set<WorkspaceTab["id"]>(["today", "knowledge", "practice"]);

type WorkspaceShellProps = {
  spaces?: SpaceSummary[];
  onClassroomAdded?: (space: SpaceSummary) => void;
};

type NoteOpenRequest = {
  knowledgeBaseId: string;
  noteId: string;
  requestId: number;
};

type AgentCitationOpenRequest = AgentPanelCitationTarget & {
  requestId: number;
};

type VaultFilePreview = {
  requestId: number;
  knowledgeBaseId: string;
  relativePath: string;
  markdown: string | null;
  heading?: string;
};

type VaultFileResponse = {
  vault_file_id: string;
  relative_path: string;
  markdown: string | null;
};

export function WorkspaceShell({
  spaces = exampleSpaces,
  onClassroomAdded,
}: WorkspaceShellProps) {
  const initialSpaces = spaces.length > 0 ? spaces : exampleSpaces.slice(0, 1);
  const [availableSpaces, setAvailableSpaces] = useState(initialSpaces);
  const [selectedSpaceId, setSelectedSpaceId] = useState(initialSpaces[0].id);
  const [tabsBySpace, setTabsBySpace] = useState<Record<string, WorkspaceTabsState>>({});
  const [restoredSpaceIds, setRestoredSpaceIds] = useState<Set<string>>(() => new Set());
  const [isClassroomDialogOpen, setIsClassroomDialogOpen] = useState(false);
  const [isSpaceDialogOpen, setIsSpaceDialogOpen] = useState(false);
  const [classroomName, setClassroomName] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [classroomError, setClassroomError] = useState<string | null>(null);
  const [createdInviteCode, setCreatedInviteCode] = useState<string | null>(null);
  const [isLibraryDrawerOpen, setIsLibraryDrawerOpen] = useState(false);
  const [isAgentDrawerOpen, setIsAgentDrawerOpen] = useState(false);
  const [isAccountPanelOpen, setIsAccountPanelOpen] = useState(false);
  const [agentCitationOpenRequest, setAgentCitationOpenRequest] =
    useState<AgentCitationOpenRequest | null>(null);
  const [vaultFilePreview, setVaultFilePreview] = useState<VaultFilePreview | null>(null);
  const [citationNavigationError, setCitationNavigationError] = useState(false);
  const [noteOpenRequest, setNoteOpenRequest] = useState<NoteOpenRequest | null>(null);
  const agentCitationRequestSequenceRef = useRef(0);
  const noteRequestSequenceRef = useRef(0);
  const vaultFileControllerRef = useRef<AbortController | null>(null);
  const libraryDrawerTriggerRef = useRef<HTMLButtonElement>(null);
  const libraryDrawerCloseRef = useRef<HTMLButtonElement>(null);
  const agentDrawerTriggerRef = useRef<HTMLButtonElement>(null);
  const agentDrawerCloseRef = useRef<HTMLButtonElement>(null);
  const breakpoint = useWorkspaceBreakpoint();

  const selectedSpace =
    availableSpaces.find((space) => space.id === selectedSpaceId) ?? availableSpaces[0];
  const {
    items: knowledgeBases,
    selectedKnowledgeBase,
    selectedKnowledgeBaseId,
    isLoading: isKnowledgeLoading,
    error: knowledgeError,
    select: selectKnowledgeBase,
    create: createKnowledgeBase,
    remove: removeKnowledgeBase,
    deletingKnowledgeBaseId,
    refresh: refreshKnowledgeBases,
  } = useKnowledgeLibrary(selectedSpace.id);
  const tabsState = tabsBySpace[selectedSpace.id] ?? initialWorkspaceTabs;
  const activeTab =
    tabsState.tabs.find((tab) => tab.id === tabsState.activeTabId) ?? tabsState.tabs[0];

  const dispatchTabs = useCallback(
    (action: WorkspaceTabsAction) => {
      setTabsBySpace((current) => ({
        ...current,
        [selectedSpace.id]: reduceWorkspaceTabs(
          current[selectedSpace.id] ?? initialWorkspaceTabs,
          action,
        ),
      }));
    },
    [selectedSpace.id],
  );

  useEffect(() => {
    if (isKnowledgeLoading || restoredSpaceIds.has(selectedSpace.id)) return;

    const spaceId = selectedSpace.id;
    const preference = readWorkspacePreference(spaceId);
    const preferredKnowledgeBase = preference?.selectedKnowledgeBaseId
      ? knowledgeBases.find((item) => item.id === preference.selectedKnowledgeBaseId)
      : null;
    const graphKnowledgeBase = preference?.activeTabId.startsWith("graph:")
      ? knowledgeBases.find(
          (item) => item.id === preference.activeTabId.slice("graph:".length),
        )
      : null;

    void Promise.resolve().then(() => {
      if (preferredKnowledgeBase) selectKnowledgeBase(preferredKnowledgeBase.id);
      if (graphKnowledgeBase) {
        setTabsBySpace((current) => ({
          ...current,
          [spaceId]: reduceWorkspaceTabs(current[spaceId] ?? initialWorkspaceTabs, {
            type: "open-graph",
            knowledgeBaseId: graphKnowledgeBase.id,
            knowledgeBaseName: graphKnowledgeBase.name,
          }),
        }));
      } else if (preference && fixedTabIds.has(preference.activeTabId)) {
        setTabsBySpace((current) => ({
          ...current,
          [spaceId]: reduceWorkspaceTabs(current[spaceId] ?? initialWorkspaceTabs, {
            type: "focus",
            tabId: preference.activeTabId,
          }),
        }));
      }
      setRestoredSpaceIds((current) => new Set(current).add(spaceId));
    });
  }, [
    isKnowledgeLoading,
    knowledgeBases,
    restoredSpaceIds,
    selectKnowledgeBase,
    selectedSpace.id,
  ]);

  useEffect(() => {
    if (!restoredSpaceIds.has(selectedSpace.id)) return;
    writeWorkspacePreference(selectedSpace.id, {
      selectedKnowledgeBaseId,
      activeTabId: tabsState.activeTabId,
    });
  }, [
    restoredSpaceIds,
    selectedKnowledgeBaseId,
    selectedSpace.id,
    tabsState.activeTabId,
  ]);

  const knowledgeBaseForGraphTab = useMemo(() => {
    if (activeTab.kind !== "graph") return null;
    return knowledgeBases.find((item) => item.id === activeTab.knowledgeBaseId) ?? null;
  }, [activeTab, knowledgeBases]);
  const agentKnowledgeBase = knowledgeBaseForGraphTab ?? selectedKnowledgeBase;
  const agentContext = getAgentContext(activeTab, agentKnowledgeBase);
  const showsInlineLibrary = breakpoint === "desktop" || breakpoint === "tablet";
  const showsLibraryDrawer = breakpoint === "compact" || breakpoint === "mobile";
  const showsAgentDrawer = breakpoint !== "desktop";
  const portalTarget = typeof document === "undefined" ? null : document.body;

  useEffect(() => {
    if (!isLibraryDrawerOpen) return;
    libraryDrawerCloseRef.current?.focus();
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      setIsLibraryDrawerOpen(false);
      libraryDrawerTriggerRef.current?.focus();
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [isLibraryDrawerOpen]);

  useEffect(() => {
    if (!isAgentDrawerOpen) return;
    agentDrawerCloseRef.current?.focus();
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      setIsAgentDrawerOpen(false);
      agentDrawerTriggerRef.current?.focus();
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [isAgentDrawerOpen]);

  useEffect(() => () => vaultFileControllerRef.current?.abort(), []);

  const addClassroomSpace = (space: SpaceSummary, closeDialog: boolean) => {
    setAvailableSpaces((current) =>
      current.some((item) => item.id === space.id)
        ? current.map((item) => (item.id === space.id ? space : item))
        : [...current, space],
    );
    onClassroomAdded?.(space);
    setSelectedSpaceId(space.id);
    if (closeDialog) setIsClassroomDialogOpen(false);
  };

  const createClassroom = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const name = classroomName.trim();
    if (!name) return;
    setClassroomError(null);
    void classroomApi
      .create(name)
      .then((classroom) => {
        setCreatedInviteCode(classroom.invite_code);
        addClassroomSpace(classroom.space, false);
      })
      .catch(() => setClassroomError("创建班级失败，请稍后重试。"));
  };

  const joinClassroom = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const code = inviteCode.trim();
    if (!code) return;
    setClassroomError(null);
    void classroomApi
      .join(code)
      .then((classroom) => addClassroomSpace(classroom.space, true))
      .catch(() => setClassroomError("邀请码无效或已失效。"));
  };

  const openClassroomDialog = () => {
    setClassroomError(null);
    setCreatedInviteCode(null);
    setIsClassroomDialogOpen(true);
  };

  const openGraph = (knowledgeBase: KnowledgeBase) => {
    dispatchTabs({
      type: "open-graph",
      knowledgeBaseId: knowledgeBase.id,
      knowledgeBaseName: knowledgeBase.name,
    });
  };
  const deleteKnowledgeBase = async (knowledgeBase: KnowledgeBase) => {
    const removal = await removeKnowledgeBase(knowledgeBase.id);
    if (!removal.removed) return;

    const spaceId = selectedSpace.id;
    const closeDeletedGraphTab = (currentTabs: WorkspaceTabsState) =>
      reduceWorkspaceTabs(currentTabs, {
        type: "close",
        tabId: `graph:${knowledgeBase.id}`,
      });
    const cleanedCurrentTabs = closeDeletedGraphTab(
      tabsBySpace[spaceId] ?? initialWorkspaceTabs,
    );
    setTabsBySpace((current) => ({
      ...current,
      [spaceId]: closeDeletedGraphTab(current[spaceId] ?? initialWorkspaceTabs),
    }));
    setNoteOpenRequest((current) =>
      current?.knowledgeBaseId === knowledgeBase.id ? null : current,
    );
    setAgentCitationOpenRequest((current) => {
      if (current?.knowledgeBaseId !== knowledgeBase.id) return current;
      vaultFileControllerRef.current?.abort();
      return null;
    });
    setVaultFilePreview((current) => {
      if (current?.knowledgeBaseId !== knowledgeBase.id) return current;
      vaultFileControllerRef.current?.abort();
      return null;
    });
    setCitationNavigationError(false);
    writeWorkspacePreference(spaceId, {
      selectedKnowledgeBaseId: removal.selectedKnowledgeBaseId,
      activeTabId: cleanedCurrentTabs.activeTabId,
    });
  };
  const openGraphNote = (knowledgeBase: KnowledgeBase, noteId: string) => {
    setNoteOpenRequest({
      knowledgeBaseId: knowledgeBase.id,
      noteId,
      requestId: ++noteRequestSequenceRef.current,
    });
    if (selectedKnowledgeBaseId !== knowledgeBase.id) {
      selectKnowledgeBase(knowledgeBase.id);
    }
    dispatchTabs({ type: "focus", tabId: "knowledge" });
  };
  const focusKnowledgeInSpace = (spaceId: string) => {
    setTabsBySpace((current) => ({
      ...current,
      [spaceId]: reduceWorkspaceTabs(current[spaceId] ?? initialWorkspaceTabs, {
        type: "focus",
        tabId: "knowledge",
      }),
    }));
  };
  const openAgentCitation = (citation: AgentPanelCitationTarget) => {
    vaultFileControllerRef.current?.abort();
    setVaultFilePreview(null);
    setCitationNavigationError(false);
    const targetSpace = availableSpaces.find((space) => space.id === citation.spaceId);
    if (!targetSpace) {
      setAgentCitationOpenRequest(null);
      setCitationNavigationError(true);
      if (breakpoint !== "desktop") setIsAgentDrawerOpen(false);
      return;
    }

    setAgentCitationOpenRequest({
      ...citation,
      requestId: ++agentCitationRequestSequenceRef.current,
    });
    focusKnowledgeInSpace(citation.spaceId);
    if (selectedSpace.id !== citation.spaceId) setSelectedSpaceId(citation.spaceId);
    if (breakpoint !== "desktop") setIsAgentDrawerOpen(false);
  };

  useEffect(() => {
    const request = agentCitationOpenRequest;
    if (request === null || selectedSpace.id !== request.spaceId || isKnowledgeLoading) return;

    if (knowledgeError !== null) {
      void Promise.resolve().then(() => {
        setAgentCitationOpenRequest(null);
        setCitationNavigationError(true);
      });
      return;
    }
    const targetKnowledgeBase = knowledgeBases.find(
      (item) => item.id === request.knowledgeBaseId,
    );
    if (!targetKnowledgeBase) {
      void Promise.resolve().then(() => {
        setAgentCitationOpenRequest(null);
        setCitationNavigationError(true);
      });
      return;
    }
    if (selectedKnowledgeBaseId !== targetKnowledgeBase.id) {
      selectKnowledgeBase(targetKnowledgeBase.id);
      return;
    }

    const controller = new AbortController();
    vaultFileControllerRef.current?.abort();
    vaultFileControllerRef.current = controller;
    const knowledgeBaseId = encodeURIComponent(request.knowledgeBaseId);
    const vaultFileId = encodeURIComponent(request.vaultFileId);
    void fetch(apiUrl(`/api/v1/knowledge-bases/${knowledgeBaseId}/vault/files/${vaultFileId}`), {
      credentials: "include",
      headers: { Accept: "application/json" },
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok) throw new Error("vault_file_unavailable");
        return await response.json() as VaultFileResponse;
      })
      .then((file) => {
        if (controller.signal.aborted) return;
        if (
          file.vault_file_id !== request.vaultFileId ||
          typeof file.relative_path !== "string" ||
          !(typeof file.markdown === "string" || file.markdown === null)
        ) {
          throw new Error("vault_file_invalid_response");
        }
        setVaultFilePreview({
          requestId: request.requestId,
          knowledgeBaseId: request.knowledgeBaseId,
          relativePath: file.relative_path,
          markdown: file.markdown,
          heading: request.heading,
        });
        setAgentCitationOpenRequest(null);
        setCitationNavigationError(false);
      })
      .catch(() => {
        if (controller.signal.aborted) return;
        setAgentCitationOpenRequest(null);
        setVaultFilePreview(null);
        setCitationNavigationError(true);
      })
      .finally(() => {
        if (vaultFileControllerRef.current === controller) vaultFileControllerRef.current = null;
      });
  }, [
    agentCitationOpenRequest,
    isKnowledgeLoading,
    knowledgeBases,
    knowledgeError,
    selectKnowledgeBase,
    selectedKnowledgeBaseId,
    selectedSpace.id,
  ]);

  const handleNoteRequestHandled = (requestId: number) => {
    setNoteOpenRequest((current) =>
      current?.requestId === requestId ? null : current,
    );
  };
  const closeLibraryDrawer = () => {
    setIsLibraryDrawerOpen(false);
    libraryDrawerTriggerRef.current?.focus();
  };
  const closeAgentDrawer = () => {
    setIsAgentDrawerOpen(false);
    agentDrawerTriggerRef.current?.focus();
  };
  const librarySidebar = (
    <KnowledgeLibrarySidebar
      deletingKnowledgeBaseId={deletingKnowledgeBaseId}
      error={knowledgeError}
      isLoading={isKnowledgeLoading}
      knowledgeBases={knowledgeBases}
      onCreate={async (name) => {
        await createKnowledgeBase(name);
      }}
      onDelete={deleteKnowledgeBase}
      onOpenClassroom={openClassroomDialog}
      onOpenDueReview={() => dispatchTabs({ type: "focus", tabId: "today" })}
      onOpenGraph={openGraph}
      onRetry={refreshKnowledgeBases}
      onSelect={selectKnowledgeBase}
      onSwitchSpace={
        availableSpaces.length > 1 ? () => setIsSpaceDialogOpen(true) : undefined
      }
      selectedKnowledgeBaseId={selectedKnowledgeBaseId}
    />
  );
  const centralWorkspace = (
    <section aria-label="学习内容" className={styles.centralWorkspace}>
      {breakpoint !== "desktop" ? (
        <div aria-label="工作区侧栏" className={styles.workspaceToolbar}>
          {showsLibraryDrawer ? (
            <button
              onClick={() => setIsLibraryDrawerOpen(true)}
              ref={libraryDrawerTriggerRef}
              type="button"
            >
              打开知识库
            </button>
          ) : null}
          <button
            onClick={() => setIsAgentDrawerOpen(true)}
            ref={agentDrawerTriggerRef}
            type="button"
          >
            打开 Workspace Agent
          </button>
        </div>
      ) : null}
      <WorkspaceTabBar
        activeTabId={tabsState.activeTabId}
        onClose={(tabId) => dispatchTabs({ type: "close", tabId })}
        onFocus={(tabId) => dispatchTabs({ type: "focus", tabId })}
        tabs={tabsState.tabs}
      />
      <div className={styles.centralContent} id="workspace-active-panel" role="tabpanel">
        {citationNavigationError ? (
          <div className={styles.citationNavigationNotice} role="alert">
            <span>资源不可用</span>
            <button onClick={() => setCitationNavigationError(false)} type="button">
              关闭
            </button>
          </div>
        ) : null}
        {vaultFilePreview ? (
          <section aria-label="Vault 文件" className={styles.vaultFileViewer} role="region">
            <header>
              <div>
                <span className={styles.eyebrow}>Vault 文件</span>
                <h2>{vaultFilePreview.relativePath}</h2>
                {vaultFilePreview.heading ? <p>定位：{vaultFilePreview.heading}</p> : null}
              </div>
              <button onClick={() => setVaultFilePreview(null)} type="button">
                关闭文件
              </button>
            </header>
            {vaultFilePreview.markdown === null ? (
              <p>此文件无法作为文本预览。</p>
            ) : (
              <pre>{vaultFilePreview.markdown}</pre>
            )}
          </section>
        ) : null}
        <ActivePanel
          activeTab={activeTab}
          graphKnowledgeBase={knowledgeBaseForGraphTab}
          noteRequest={
            noteOpenRequest !== null &&
            noteOpenRequest.knowledgeBaseId === selectedKnowledgeBase?.id
              ? noteOpenRequest
              : undefined
          }
          onNoteRequestHandled={handleNoteRequestHandled}
          onOpenGraph={openGraph}
          onOpenGraphNote={openGraphNote}
          onOpenKnowledge={(knowledgeBaseId) => {
            if (knowledgeBaseId && knowledgeBaseId !== selectedKnowledgeBaseId) {
              selectKnowledgeBase(knowledgeBaseId);
            }
            dispatchTabs({ type: "focus", tabId: "knowledge" });
          }}
          onOpenPractice={(questionVersionId) =>
            dispatchTabs({ type: "open-practice", questionVersionId })
          }
          selectedKnowledgeBase={selectedKnowledgeBase}
          selectedSpace={selectedSpace}
        />
      </div>
    </section>
  );
  const agentWorkspace = (
    <div className={styles.agentWorkspace}>
      <div className={styles.agentWorkspaceBody}>
        {agentKnowledgeBase ? (
          <AgentPanel
            contextLabel={agentContext}
            joinedSpaceIds={availableSpaces.map((space) => space.id)}
            knowledgeBase={agentKnowledgeBase}
            onOpenCitation={openAgentCitation}
            readableVaultScopes={knowledgeBases.map((knowledgeBase) => ({
              spaceId: selectedSpace.id,
              knowledgeBaseId: knowledgeBase.id,
            }))}
            space={selectedSpace}
          />
        ) : (
          <KnowledgeEmptyState
            description="选择或创建知识库后，Workspace Agent 会跟随当前学习上下文。"
            title="Workspace Agent"
          />
        )}
      </div>
    </div>
  );
  const layoutName =
    breakpoint === "desktop"
      ? "library-center-agent"
      : breakpoint === "tablet"
        ? "library-center"
        : "center-drawers";

  return (
    <main className={styles.shell} data-breakpoint={breakpoint} data-layout={layoutName}>
      <div aria-label="账户与工作区设置" className={styles.workspaceAccountBar}>
        <span className={styles.workspaceAccountContext}>当前空间：{selectedSpace.name}</span>
        <button
          aria-haspopup="dialog"
          onClick={() => setIsAccountPanelOpen(true)}
          type="button"
        >
          账户与充值
        </button>
      </div>
      <section
        aria-label="学习工作区"
        className={`${styles.desktopWorkspace} ${styles.responsiveWorkspace}`}
      >
        {breakpoint === "desktop" ? (
          <Group
            className={styles.panelGroup}
            defaultLayout={{ library: 18, center: 26, agent: 56 }}
            orientation="horizontal"
          >
            <Panel className={styles.libraryPanelSlot} id="library" maxSize="32%" minSize="16%">
              {librarySidebar}
            </Panel>
            <Separator aria-label="调整知识库和学习内容宽度" className={styles.separator} />
            <Panel className={styles.centerPanelSlot} id="center" minSize="22%">
              {centralWorkspace}
            </Panel>
            <Separator
              aria-label="调整学习内容和 Workspace Agent 宽度"
              className={styles.separator}
            />
            <Panel
              className={styles.agentPanelSlot}
              id="agent"
              maxSize="62%"
              minSize="40%"
            >
              {agentWorkspace}
            </Panel>
          </Group>
        ) : showsInlineLibrary ? (
          <Group
            className={styles.panelGroup}
            defaultLayout={{ library: 28, center: 72 }}
            orientation="horizontal"
          >
            <Panel className={styles.libraryPanelSlot} id="library" maxSize="38%" minSize="22%">
              {librarySidebar}
            </Panel>
            <Separator aria-label="调整知识库和学习内容宽度" className={styles.separator} />
            <Panel className={styles.centerPanelSlot} id="center" minSize="56%">
              {centralWorkspace}
            </Panel>
          </Group>
        ) : (
          <div className={styles.centerOnly}>{centralWorkspace}</div>
        )}
      </section>

      {showsLibraryDrawer && portalTarget
        ? createPortal(
            <div className={styles.drawerLayer} hidden={!isLibraryDrawerOpen}>
              <button
                aria-label="关闭知识库抽屉背景"
                className={styles.drawerBackdrop}
                onClick={closeLibraryDrawer}
                type="button"
              />
              <section
                aria-label="知识库抽屉"
                aria-modal="true"
                className={`${styles.drawer} ${styles.drawerLeft}`}
                role="dialog"
              >
                <header className={styles.drawerHeader}>
                  <strong>知识库</strong>
                  <button
                    aria-label="关闭知识库抽屉"
                    onClick={closeLibraryDrawer}
                    ref={libraryDrawerCloseRef}
                    type="button"
                  >
                    关闭
                  </button>
                </header>
                <div className={styles.drawerBody}>{librarySidebar}</div>
              </section>
            </div>,
            portalTarget,
          )
        : null}

      {showsAgentDrawer && portalTarget
        ? createPortal(
            <div className={styles.drawerLayer} hidden={!isAgentDrawerOpen}>
              <button
                aria-label="关闭 Workspace Agent 抽屉背景"
                className={styles.drawerBackdrop}
                onClick={closeAgentDrawer}
                type="button"
              />
              <section
                aria-label="Workspace Agent 抽屉"
                aria-modal="true"
                className={`${styles.drawer} ${styles.drawerRight} ${styles.agentDrawer}`}
                role="dialog"
              >
                <header className={styles.drawerHeader}>
                  <strong>Workspace Agent</strong>
                  <button
                    aria-label="关闭 Workspace Agent 抽屉"
                    onClick={closeAgentDrawer}
                    ref={agentDrawerCloseRef}
                    type="button"
                  >
                    关闭
                  </button>
                </header>
                <div className={styles.drawerBody}>{agentWorkspace}</div>
              </section>
            </div>,
            portalTarget,
          )
        : null}

      {isAccountPanelOpen ? (
        <AccountPanel onClose={() => setIsAccountPanelOpen(false)} />
      ) : null}

      {isSpaceDialogOpen ? (
        <div className={styles.classroomDialogBackdrop} role="presentation">
          <section aria-label="切换空间" aria-modal="true" className={styles.classroomDialog} role="dialog">
            <header>
              <div>
                <span className={styles.eyebrow}>学习范围</span>
                <h2>切换空间</h2>
              </div>
              <button aria-label="关闭空间窗口" onClick={() => setIsSpaceDialogOpen(false)} type="button">
                关闭
              </button>
            </header>
            <div className={styles.spaceChoiceList}>
              {availableSpaces.map((space) => (
                <button
                  aria-current={space.id === selectedSpace.id ? "page" : undefined}
                  key={space.id}
                  onClick={() => {
                    setSelectedSpaceId(space.id);
                    setIsSpaceDialogOpen(false);
                  }}
                  type="button"
                >
                  {space.kind === "personal" ? "个人空间" : space.name}
                </button>
              ))}
            </div>
          </section>
        </div>
      ) : null}

      {isClassroomDialogOpen ? (
        <div className={styles.classroomDialogBackdrop} role="presentation">
          <section
            aria-label="创建或加入班级"
            aria-modal="true"
            className={styles.classroomDialog}
            role="dialog"
          >
            <header>
              <div>
                <span className={styles.eyebrow}>班级空间</span>
                <h2>创建或加入班级</h2>
              </div>
              <button
                aria-label="关闭班级窗口"
                onClick={() => setIsClassroomDialogOpen(false)}
                type="button"
              >
                关闭
              </button>
            </header>
            <p>创建后会生成邀请码；加入已有班级请填写教师提供的邀请码。</p>
            <form onSubmit={createClassroom}>
              <label>
                班级名称
                <input
                  aria-label="班级名称"
                  maxLength={120}
                  onChange={(event) => setClassroomName(event.target.value)}
                  value={classroomName}
                />
              </label>
              <button type="submit">创建班级</button>
            </form>
            <form onSubmit={joinClassroom}>
              <label>
                邀请码
                <input
                  aria-label="邀请码"
                  maxLength={256}
                  onChange={(event) => setInviteCode(event.target.value)}
                  value={inviteCode}
                />
              </label>
              <button type="submit">加入班级</button>
            </form>
            {classroomError ? (
              <p className={styles.classroomError} role="alert">
                {classroomError}
              </p>
            ) : null}
            {createdInviteCode ? (
              <p className={styles.inviteCode}>邀请码：{createdInviteCode}</p>
            ) : null}
          </section>
        </div>
      ) : null}
    </main>
  );
}

function WorkspaceTabBar({
  tabs,
  activeTabId,
  onFocus,
  onClose,
}: {
  tabs: WorkspaceTab[];
  activeTabId: WorkspaceTab["id"];
  onFocus: (tabId: WorkspaceTab["id"]) => void;
  onClose: (tabId: WorkspaceTab["id"]) => void;
}) {
  return (
    <div aria-label="学习标签" className={styles.workspaceTabBar} role="tablist">
      {tabs.map((tab) => {
        const graphLabel = tab.kind === "graph" ? `关联图 · ${tab.label}` : tab.label;
        return (
          <div className={styles.workspaceTabItem} key={tab.id}>
            <button
              aria-controls="workspace-active-panel"
              aria-label={graphLabel}
              aria-selected={tab.id === activeTabId}
              className={tab.id === activeTabId ? styles.workspaceTabActive : undefined}
              onClick={() => onFocus(tab.id)}
              role="tab"
              type="button"
            >
              {graphLabel}
            </button>
            {tab.kind === "graph" ? (
              <button
                aria-label={`关闭关联图 · ${tab.label}`}
                className={styles.workspaceTabClose}
                onClick={() => onClose(tab.id)}
                type="button"
              >
                ×
              </button>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

function ActivePanel({
  activeTab,
  graphKnowledgeBase,
  selectedKnowledgeBase,
  selectedSpace,
  noteRequest,
  onNoteRequestHandled,
  onOpenGraph,
  onOpenGraphNote,
  onOpenKnowledge,
  onOpenPractice,
}: {
  activeTab: WorkspaceTab;
  graphKnowledgeBase: KnowledgeBase | null;
  selectedKnowledgeBase: KnowledgeBase | null;
  selectedSpace: SpaceSummary;
  noteRequest?: NoteOpenRequest;
  onNoteRequestHandled: (requestId: number) => void;
  onOpenGraph: (knowledgeBase: KnowledgeBase) => void;
  onOpenGraphNote: (knowledgeBase: KnowledgeBase, noteId: string) => void;
  onOpenKnowledge: (knowledgeBaseId?: string) => void;
  onOpenPractice: (questionVersionId: string) => void;
}) {
  switch (activeTab.kind) {
    case "today":
      return (
        <StudyDashboard
          knowledgeBase={selectedKnowledgeBase}
          onOpenKnowledge={onOpenKnowledge}
          onOpenPractice={onOpenPractice}
        />
      );
    case "knowledge":
      return selectedKnowledgeBase ? (
        <KnowledgePanel
          initialNoteId={noteRequest?.noteId}
          knowledgeBase={selectedKnowledgeBase}
          onInitialNoteHandled={() => noteRequest && onNoteRequestHandled(noteRequest.requestId)}
          onOpenGraph={() => onOpenGraph(selectedKnowledgeBase)}
          spaceName={selectedSpace.name}
        />
      ) : (
        <KnowledgeEmptyState description="先在左侧创建或选择知识库。" title="知识库" />
      );
    case "practice":
      return selectedKnowledgeBase ? (
        <QuestionBankPanel
          initialQuestionVersionId={activeTab.questionVersionId}
          knowledgeBase={selectedKnowledgeBase}
        />
      ) : (
        <KnowledgeEmptyState description="先在左侧创建或选择知识库。" title="题库练习" />
      );
    case "graph":
      return graphKnowledgeBase ? (
        <KnowledgeGraphPanel
          knowledgeBase={graphKnowledgeBase}
          onOpenNote={(noteId) => onOpenGraphNote(graphKnowledgeBase, noteId)}
          onReviewCandidates={() => onOpenKnowledge(graphKnowledgeBase.id)}
        />
      ) : (
        <KnowledgeEmptyState description="这个知识库已不在当前空间中。" title="关联图不可用" />
      );
  }
}

function KnowledgeEmptyState({ title, description }: { title: string; description: string }) {
  return (
    <section className={styles.workspaceEmptyState}>
      <span className={styles.eyebrow}>学习工作台</span>
      <h2>{title}</h2>
      <p>{description}</p>
    </section>
  );
}

function getAgentContext(activeTab: WorkspaceTab, knowledgeBase: KnowledgeBase | null): string {
  if (activeTab.kind === "graph") return `关联图：${activeTab.label}`;
  if (activeTab.kind === "practice") return "题库练习";
  if (activeTab.kind === "knowledge") return knowledgeBase ? `知识库：${knowledgeBase.name}` : "知识库";
  return "今日任务";
}
