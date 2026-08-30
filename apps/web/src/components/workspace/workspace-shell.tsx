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
import { classroomApi } from "@/lib/classrooms-api";
import type { KnowledgeBase } from "@/lib/knowledge-api";
import type { TutorCitation } from "@/lib/tutor-api";

import { AccountPanel } from "./account-panel";
import { KnowledgeGraphPanel } from "./knowledge-graph-panel";
import { KnowledgeLibrarySidebar } from "./knowledge-library-sidebar";
import { KnowledgePanel } from "./knowledge-panel";
import { QuestionBankPanel } from "./question-bank-panel";
import { StudyDashboard } from "./study-dashboard";
import { TutorPanel } from "./tutor-panel";
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

type CitationOpenRequest = {
  knowledgeBaseId: string;
  citation: TutorCitation;
  requestId: number;
};

type NoteOpenRequest = {
  knowledgeBaseId: string;
  noteId: string;
  requestId: number;
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
  const [isAccountDialogOpen, setIsAccountDialogOpen] = useState(false);
  const [classroomName, setClassroomName] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [classroomError, setClassroomError] = useState<string | null>(null);
  const [createdInviteCode, setCreatedInviteCode] = useState<string | null>(null);
  const [isLibraryDrawerOpen, setIsLibraryDrawerOpen] = useState(false);
  const [isTutorDrawerOpen, setIsTutorDrawerOpen] = useState(false);
  const [citationOpenRequest, setCitationOpenRequest] = useState<CitationOpenRequest | null>(null);
  const [noteOpenRequest, setNoteOpenRequest] = useState<NoteOpenRequest | null>(null);
  const citationRequestSequenceRef = useRef(0);
  const noteRequestSequenceRef = useRef(0);
  const libraryDrawerTriggerRef = useRef<HTMLButtonElement>(null);
  const libraryDrawerCloseRef = useRef<HTMLButtonElement>(null);
  const tutorDrawerTriggerRef = useRef<HTMLButtonElement>(null);
  const tutorDrawerCloseRef = useRef<HTMLButtonElement>(null);
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
  }, [restoredSpaceIds, selectedKnowledgeBaseId, selectedSpace.id, tabsState.activeTabId]);

  const knowledgeBaseForGraphTab = useMemo(() => {
    if (activeTab.kind !== "graph") return null;
    return knowledgeBases.find((item) => item.id === activeTab.knowledgeBaseId) ?? null;
  }, [activeTab, knowledgeBases]);
  const tutorKnowledgeBase = knowledgeBaseForGraphTab ?? selectedKnowledgeBase;
  const tutorContext = getTutorContext(activeTab, tutorKnowledgeBase);
  const showsInlineLibrary = breakpoint === "desktop" || breakpoint === "tablet";
  const showsLibraryDrawer = breakpoint === "compact" || breakpoint === "mobile";
  const showsTutorDrawer = breakpoint !== "desktop";
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
    if (!isTutorDrawerOpen) return;
    tutorDrawerCloseRef.current?.focus();
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      setIsTutorDrawerOpen(false);
      tutorDrawerTriggerRef.current?.focus();
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [isTutorDrawerOpen]);

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
  const openTutorCitation = (citation: TutorCitation) => {
    if (!tutorKnowledgeBase) return;
    setCitationOpenRequest({
      knowledgeBaseId: tutorKnowledgeBase.id,
      citation,
      requestId: ++citationRequestSequenceRef.current,
    });
    if (selectedKnowledgeBaseId !== tutorKnowledgeBase.id) {
      selectKnowledgeBase(tutorKnowledgeBase.id);
    }
    dispatchTabs({ type: "focus", tabId: "knowledge" });
    if (breakpoint !== "desktop") setIsTutorDrawerOpen(false);
  };

  const handleCitationRequestHandled = (requestId: number) => {
    setCitationOpenRequest((current) =>
      current?.requestId === requestId ? null : current,
    );
  };
  const handleNoteRequestHandled = (requestId: number) => {
    setNoteOpenRequest((current) =>
      current?.requestId === requestId ? null : current,
    );
  };
  const closeLibraryDrawer = () => {
    setIsLibraryDrawerOpen(false);
    libraryDrawerTriggerRef.current?.focus();
  };
  const closeTutorDrawer = () => {
    setIsTutorDrawerOpen(false);
    tutorDrawerTriggerRef.current?.focus();
  };
  const librarySidebar = (
    <KnowledgeLibrarySidebar
      error={knowledgeError}
      isLoading={isKnowledgeLoading}
      knowledgeBases={knowledgeBases}
      onCreate={async (name) => {
        await createKnowledgeBase(name);
      }}
      onOpenClassroom={openClassroomDialog}
      onOpenAccount={() => setIsAccountDialogOpen(true)}
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
            onClick={() => setIsTutorDrawerOpen(true)}
            ref={tutorDrawerTriggerRef}
            type="button"
          >
            打开 AI 家教
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
        <ActivePanel
          activeTab={activeTab}
          citationRequest={
            citationOpenRequest !== null &&
            citationOpenRequest.knowledgeBaseId === selectedKnowledgeBase?.id
              ? citationOpenRequest
              : undefined
          }
          graphKnowledgeBase={knowledgeBaseForGraphTab}
          noteRequest={
            noteOpenRequest !== null &&
            noteOpenRequest.knowledgeBaseId === selectedKnowledgeBase?.id
              ? noteOpenRequest
              : undefined
          }
          onCitationRequestHandled={handleCitationRequestHandled}
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
  const tutorWorkspace = (
    <aside aria-label="AI 家教" className={styles.tutorWorkspace}>
      {tutorKnowledgeBase ? (
        <TutorPanel
          contextLabel={tutorContext}
          knowledgeBase={tutorKnowledgeBase}
          onOpenCitation={openTutorCitation}
        />
      ) : (
        <KnowledgeEmptyState
          description="选择或创建知识库后，AI 家教会跟随当前学习上下文。"
          title="AI 家教"
        />
      )}
    </aside>
  );
  const layoutName =
    breakpoint === "desktop"
      ? "library-center-tutor"
      : breakpoint === "tablet"
        ? "library-center"
        : "center-drawers";

  return (
    <main className={styles.shell} data-breakpoint={breakpoint} data-layout={layoutName}>
      <section
        aria-label="学习工作区"
        className={`${styles.desktopWorkspace} ${styles.responsiveWorkspace}`}
      >
        {breakpoint === "desktop" ? (
          <Group
            className={styles.panelGroup}
            defaultLayout={{ library: 20, center: 55, tutor: 25 }}
            orientation="horizontal"
          >
            <Panel className={styles.libraryPanelSlot} id="library" maxSize="32%" minSize="16%">
              {librarySidebar}
            </Panel>
            <Separator aria-label="调整知识库和学习内容宽度" className={styles.separator} />
            <Panel className={styles.centerPanelSlot} id="center" minSize="36%">
              {centralWorkspace}
            </Panel>
            <Separator aria-label="调整学习内容和 AI 家教宽度" className={styles.separator} />
            <Panel className={styles.tutorPanelSlot} id="tutor" maxSize="36%" minSize="20%">
              {tutorWorkspace}
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

      {showsTutorDrawer && portalTarget
        ? createPortal(
            <div className={styles.drawerLayer} hidden={!isTutorDrawerOpen}>
              <button
                aria-label="关闭 AI 家教抽屉背景"
                className={styles.drawerBackdrop}
                onClick={closeTutorDrawer}
                type="button"
              />
              <section
                aria-label="AI 家教抽屉"
                aria-modal="true"
                className={`${styles.drawer} ${styles.drawerRight}`}
                role="dialog"
              >
                <header className={styles.drawerHeader}>
                  <strong>AI 家教</strong>
                  <button
                    aria-label="关闭 AI 家教抽屉"
                    onClick={closeTutorDrawer}
                    ref={tutorDrawerCloseRef}
                    type="button"
                  >
                    关闭
                  </button>
                </header>
                <div className={styles.drawerBody}>{tutorWorkspace}</div>
              </section>
            </div>,
            portalTarget,
          )
        : null}

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
            <form className={styles.classroomForm} onSubmit={createClassroom}>
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
            <form className={styles.classroomForm} onSubmit={joinClassroom}>
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

      {isAccountDialogOpen ? <AccountPanel onClose={() => setIsAccountDialogOpen(false)} /> : null}
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
  citationRequest,
  noteRequest,
  onCitationRequestHandled,
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
  citationRequest?: CitationOpenRequest;
  noteRequest?: NoteOpenRequest;
  onCitationRequestHandled: (requestId: number) => void;
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
          citationRequest={citationRequest}
          initialNoteId={noteRequest?.noteId}
          knowledgeBase={selectedKnowledgeBase}
          onCitationRequestHandled={onCitationRequestHandled}
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

function getTutorContext(activeTab: WorkspaceTab, knowledgeBase: KnowledgeBase | null): string {
  if (activeTab.kind === "graph") return `关联图：${activeTab.label}`;
  if (activeTab.kind === "practice") return "题库练习";
  if (activeTab.kind === "knowledge") return knowledgeBase ? `知识库：${knowledgeBase.name}` : "知识库";
  return "今日任务";
}
