"use client";

import {
  type FormEvent,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { Group, Panel, Separator } from "react-resizable-panels";

import { type SpaceSummary } from "@/lib/api";
import { classroomApi } from "@/lib/classrooms-api";
import type { KnowledgeBase } from "@/lib/knowledge-api";

import { KnowledgeGraphPanel } from "./knowledge-graph-panel";
import { KnowledgeLibrarySidebar } from "./knowledge-library-sidebar";
import { KnowledgePanel } from "./knowledge-panel";
import { QuestionBankPanel } from "./question-bank-panel";
import { StudyDashboard } from "./study-dashboard";
import { TutorPanel } from "./tutor-panel";
import { useKnowledgeLibrary } from "./use-knowledge-library";
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

  return (
    <main className={styles.shell} data-layout="library-center-tutor">
      <section aria-label="学习工作区" className={styles.desktopWorkspace}>
        <Group
          className={styles.panelGroup}
          defaultLayout={{ library: 20, center: 55, tutor: 25 }}
          orientation="horizontal"
        >
          <Panel className={styles.libraryPanelSlot} id="library" maxSize="32%" minSize="16%">
            <KnowledgeLibrarySidebar
              error={knowledgeError}
              isLoading={isKnowledgeLoading}
              knowledgeBases={knowledgeBases}
              onCreate={async (name) => {
                await createKnowledgeBase(name);
              }}
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
          </Panel>

          <Separator aria-label="调整知识库和学习内容宽度" className={styles.separator} />

          <Panel className={styles.centerPanelSlot} id="center" minSize="36%">
            <section aria-label="学习内容" className={styles.centralWorkspace}>
              <WorkspaceTabBar
                activeTabId={tabsState.activeTabId}
                onClose={(tabId) => dispatchTabs({ type: "close", tabId })}
                onFocus={(tabId) => dispatchTabs({ type: "focus", tabId })}
                tabs={tabsState.tabs}
              />
              <div className={styles.centralContent} id="workspace-active-panel" role="tabpanel">
                {renderActivePanel({
                  activeTab,
                  graphKnowledgeBase: knowledgeBaseForGraphTab,
                  selectedKnowledgeBase,
                  selectedSpace,
                  onOpenKnowledge: () => dispatchTabs({ type: "focus", tabId: "knowledge" }),
                  onOpenPractice: (questionVersionId) =>
                    dispatchTabs({ type: "open-practice", questionVersionId }),
                })}
              </div>
            </section>
          </Panel>

          <Separator aria-label="调整学习内容和 AI 家教宽度" className={styles.separator} />

          <Panel className={styles.tutorPanelSlot} id="tutor" maxSize="36%" minSize="20%">
            <aside aria-label="AI 家教" className={styles.tutorWorkspace}>
              {tutorKnowledgeBase ? (
                <TutorPanel
                  contextLabel={tutorContext}
                  knowledgeBase={tutorKnowledgeBase}
                  onOpenCitation={() => dispatchTabs({ type: "focus", tabId: "knowledge" })}
                />
              ) : (
                <KnowledgeEmptyState
                  description="选择或创建知识库后，AI 家教会跟随当前学习上下文。"
                  title="AI 家教"
                />
              )}
            </aside>
          </Panel>
        </Group>
      </section>

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

function renderActivePanel({
  activeTab,
  graphKnowledgeBase,
  selectedKnowledgeBase,
  selectedSpace,
  onOpenKnowledge,
  onOpenPractice,
}: {
  activeTab: WorkspaceTab;
  graphKnowledgeBase: KnowledgeBase | null;
  selectedKnowledgeBase: KnowledgeBase | null;
  selectedSpace: SpaceSummary;
  onOpenKnowledge: () => void;
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
        <KnowledgePanel knowledgeBase={selectedKnowledgeBase} spaceName={selectedSpace.name} />
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
        <KnowledgeGraphPanel knowledgeBase={graphKnowledgeBase} />
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
