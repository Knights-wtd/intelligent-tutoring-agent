"use client";

import { Group, Panel, Separator } from "react-resizable-panels";

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

export function WorkspaceShell() {
  return (
    <main className={styles.shell}>
      <nav aria-label="空间切换" className={styles.spaceRail}>
        <button className={styles.brand} type="button" aria-label="平台首页">
          知
        </button>
        <button className={styles.spaceButton} type="button" aria-label="个人空间">
          <span aria-hidden="true">我</span>
          <span className={styles.visuallyHidden}>个人空间</span>
        </button>
        <button
          className={`${styles.spaceButton} ${styles.active}`}
          type="button"
          aria-label="七年级数学"
          aria-current="page"
        >
          <span aria-hidden="true">七</span>
          <span className={styles.visuallyHidden}>七年级数学</span>
        </button>
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
              <strong>七年级数学</strong>
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
              <button className={styles.selectedTab} type="button" aria-pressed="true">
                知识图谱
              </button>
              <button type="button" aria-pressed="false">
                教材原页
              </button>
              <button type="button" aria-pressed="false">
                AI 笔记
              </button>
            </div>
            <div className={styles.emptyState}>
              <strong>知识工作区</strong>
              <span>选择教材、笔记、题目或关系节点后在这里查看。</span>
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
