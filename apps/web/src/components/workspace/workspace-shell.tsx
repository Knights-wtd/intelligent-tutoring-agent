"use client";

import { useEffect, useState } from "react";
import { Group, Panel, Separator } from "react-resizable-panels";

import { api, type EnabledModel, type SpaceSummary } from "@/lib/api";

import styles from "./workspace-shell.module.css";

const treeItems = [
  { label: "教材与练习", kind: "section" },
  { label: "数学上册.pdf", kind: "book" },
  { label: "同步练习.pdf", kind: "book" },
  { label: "知识图谱", kind: "active" },
  { label: "AI 笔记", kind: "note", count: "12" },
  { label: "错题集", kind: "collection", count: "8" },
  { label: "题库", kind: "collection", count: "45" },
] as const;

const workspaceViews = [
  {
    id: "graph",
    label: "知识图谱",
    message: "查看教材、笔记、题目之间的知识关系。",
  },
  {
    id: "source",
    label: "教材原页",
    message: "查看教材原始页面及其版面内容。",
  },
  {
    id: "notes",
    label: "AI 笔记",
    message: "查看基于教材内容生成和整理的 AI 笔记。",
  },
] as const;

type WorkspaceViewId = (typeof workspaceViews)[number]["id"];

const exampleSpaces: SpaceSummary[] = [
  { id: "personal", kind: "personal", name: "我的空间" },
  { id: "math", kind: "classroom", name: "七年级数学" },
];

type WorkspaceShellProps = {
  spaces?: SpaceSummary[];
};

export function WorkspaceShell({ spaces = exampleSpaces }: WorkspaceShellProps) {
  const [selectedViewId, setSelectedViewId] = useState<WorkspaceViewId>("graph");
  const [selectedSpaceId, setSelectedSpaceId] = useState(spaces[0]?.id ?? "");
  const [models, setModels] = useState<EnabledModel[] | null>(null);
  const [balance, setBalance] = useState<string | null>(null);
  const [selectedModelId, setSelectedModelId] = useState("");
  const [isModelCatalogUnavailable, setIsModelCatalogUnavailable] = useState(false);
  const [isBalanceUnavailable, setIsBalanceUnavailable] = useState(false);
  const selectedView =
    workspaceViews.find((view) => view.id === selectedViewId) ?? workspaceViews[0];
  const selectedSpace = spaces.find((space) => space.id === selectedSpaceId) ?? spaces[0];

  const loadModelCatalog = () => {
    void api.models()
      .then((catalog) => {
        setModels(catalog);
        setSelectedModelId((current) =>
          catalog.some((model) => model.id === current) ? current : (catalog[0]?.id ?? ""),
        );
      })
      .catch(() => {
        setModels(null);
        setIsModelCatalogUnavailable(true);
      });
  };

  const loadBalance = () => {
    void api
      .billingMe()
      .then((billing) => {
        setBalance(formatRmbBalance(billing.balance));
      })
      .catch(() => {
        setBalance(null);
        setIsBalanceUnavailable(true);
      });
  };

  useEffect(() => {
    loadModelCatalog();
    loadBalance();
  }, []);

  return (
    <main className={styles.shell}>
      <nav aria-label="空间切换" className={styles.spaceRail}>
        <button className={styles.brand} type="button" aria-label="平台首页">
          知
        </button>
        {spaces.map((space) => {
          const isSelected = space.id === selectedSpace?.id;
          const icon = space.kind === "personal" ? "我" : space.name.slice(0, 1);
          const spaceLabel = space.kind === "personal" ? "个人空间" : space.name;
          return (
            <button
              aria-current={isSelected ? "page" : undefined}
              aria-label={spaceLabel}
              className={`${styles.spaceButton} ${isSelected ? styles.active : ""}`}
              key={space.id}
              onClick={() => setSelectedSpaceId(space.id)}
              type="button"
            >
              <span aria-hidden="true">{icon}</span>
              <span className={styles.visuallyHidden}>{spaceLabel}</span>
            </button>
          );
        })}
        <button className={styles.spaceButton} type="button" aria-label="创建或加入班级">
          <span aria-hidden="true">+</span>
        </button>
      </nav>

      <Group
        className={styles.panelGroup}
        defaultLayout={{ tree: 22, center: 50, tutor: 28 }}
        orientation="horizontal"
      >
        <Panel id="tree" minSize="16%" maxSize="34%">
          <aside aria-label="当前空间内容" className={styles.treePane}>
            <header className={styles.paneHeader}>
              <strong>{selectedSpace?.name ?? "我的空间"}</strong>
              <button type="button" aria-label="空间设置">
                •••
              </button>
            </header>
            <ul className={styles.treeList}>
              {treeItems.map((item) => (
                <li
                  className={`${styles.treeItem} ${styles[item.kind]}`}
                  key={item.label}
                >
                  <span className={styles.itemIcon} aria-hidden="true">
                    {item.kind === "section" ? "⌄" : item.kind === "book" ? "▣" : "◇"}
                  </span>
                  <span>{item.label}</span>
                  {"count" in item ? <span className={styles.count}>{item.count}</span> : null}
                </li>
              ))}
            </ul>
          </aside>
        </Panel>

        <Separator aria-label="调整内容树和知识工作区宽度" className={styles.separator} />

        <Panel id="center" minSize="30%">
          <section aria-label="知识工作区" className={styles.centerPane}>
            <div className={styles.tabs} aria-label="知识内容视图">
              {workspaceViews.map((view) => {
                const isSelected = view.id === selectedViewId;

                return (
                  <button
                    className={isSelected ? styles.selectedTab : undefined}
                    key={view.id}
                    type="button"
                    aria-pressed={isSelected}
                    onClick={() => setSelectedViewId(view.id)}
                  >
                    {view.label}
                  </button>
                );
              })}
            </div>
            <div className={styles.emptyState}>
              <h2>{selectedView.label}</h2>
              <span>{selectedView.message}</span>
            </div>
          </section>
        </Panel>

        <Separator aria-label="调整知识工作区和 AI 家教宽度" className={styles.separator} />

        <Panel id="tutor" minSize="20%" maxSize="42%">
          <aside aria-label="AI 家教" className={styles.tutorPane}>
            <header className={styles.paneHeader}>
              <strong>AI 家教</strong>
              <button type="button">完整解答</button>
            </header>
            <div className={styles.tutorControls}>
              <div>
                <label className={styles.modelLabel}>
                  模型
                  <select
                    aria-label="选择 AI 模型"
                    disabled={models === null || models.length === 0}
                    onChange={(event) => setSelectedModelId(event.target.value)}
                    value={selectedModelId}
                  >
                    {models?.map((model) => (
                      <option key={model.id} value={model.id}>
                        {model.display_name}
                      </option>
                    ))}
                  </select>
                </label>
                {isModelCatalogUnavailable ? (
                  <div className={styles.tutorDataNotice} role="status">
                    模型暂时无法加载。
                    <button
                      type="button"
                      onClick={() => {
                        setIsModelCatalogUnavailable(false);
                        loadModelCatalog();
                      }}
                    >
                      重试模型
                    </button>
                  </div>
                ) : null}
              </div>
              <div>
                <span className={styles.balance}>
                  {balance === null ? "余额加载中…" : `余额 ¥${balance}`}
                </span>
                {isBalanceUnavailable ? (
                  <div className={styles.tutorDataNotice} role="status">
                    余额暂时无法加载。
                    <button
                      type="button"
                      onClick={() => {
                        setIsBalanceUnavailable(false);
                        loadBalance();
                      }}
                    >
                      重试余额
                    </button>
                  </div>
                ) : null}
              </div>
            </div>
            <div className={styles.answer}>
              选择教材内容或直接提出问题。回答将在这里显示来源与费用。
            </div>
            <label className={styles.questionLabel}>
              提问
              <textarea aria-label="向 AI 家教提问" placeholder="输入你的问题…" />
            </label>
          </aside>
        </Panel>
      </Group>
    </main>
  );
}

function formatRmbBalance(value: string): string {
  const match = /^([+-]?)(\d+)(?:\.(\d+))?$/.exec(value.trim());
  if (!match) return "0.00";

  const [, sign, integerPart, fractionalPart = ""] = match;
  let whole = stripLeadingZeroes(integerPart);
  let cents = `${fractionalPart}00`.slice(0, 2);

  if ((fractionalPart[2] ?? "0") >= "5") {
    const incremented = incrementCents(cents);
    cents = incremented.cents;
    if (incremented.carry) whole = incrementWhole(whole);
  }

  const isZero = whole === "0" && cents === "00";
  return `${sign === "-" && !isZero ? "-" : ""}${whole}.${cents}`;
}

function stripLeadingZeroes(value: string): string {
  return value.replace(/^0+(?=\d)/, "");
}

function incrementCents(cents: string): { cents: string; carry: boolean } {
  if (cents === "99") return { cents: "00", carry: true };
  if (cents[1] !== "9") return { cents: `${cents[0]}${nextDigit(cents[1])}`, carry: false };
  return { cents: `${nextDigit(cents[0])}0`, carry: false };
}

function incrementWhole(value: string): string {
  const digits = value.split("");
  for (let index = digits.length - 1; index >= 0; index -= 1) {
    if (digits[index] === "9") {
      digits[index] = "0";
      continue;
    }
    digits[index] = nextDigit(digits[index]);
    return digits.join("");
  }
  return `1${digits.join("")}`;
}

function nextDigit(value: string): string {
  const digits = "0123456789";
  return digits[digits.indexOf(value) + 1];
}
