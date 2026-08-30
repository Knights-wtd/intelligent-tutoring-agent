"use client";

import { Fragment, type ReactNode } from "react";

import styles from "./workspace-shell.module.css";

/**
 * 轻量导师消息格式化:把模型输出的 Markdown 子集解析为分块结构再渲染。
 *
 * 仅支持导师提示词约定的输出形态——#/##/### 标题、**加粗**、`行内代码`、
 * 编号/无序列表——刻意不引入 Markdown 依赖库。所有内容都以 React 元素输出,
 * 不经过 dangerouslySetInnerHTML,模型输出中的任何 HTML 片段都会被转义。
 */

export type InlineSpan =
  | { kind: "text"; value: string }
  | { kind: "strong"; value: string }
  | { kind: "code"; value: string };

export type TutorBlock =
  | { kind: "heading"; level: 1 | 2 | 3; spans: InlineSpan[] }
  | { kind: "paragraph"; spans: InlineSpan[] }
  | { kind: "list"; ordered: boolean; items: InlineSpan[][] };

const HEADING_PATTERN = /^(#{1,6})\s+(.*)$/;
const UNORDERED_ITEM_PATTERN = /^[-*•]\s+(.*)$/;
const ORDERED_ITEM_PATTERN = /^\d+[.、)]\s*(.*)$/;
const BOLD_PATTERN = /\*\*([^*]+)\*\*/;
const CODE_PATTERN = /`([^`]+)`/;

function parseInlineSpans(text: string): InlineSpan[] {
  const spans: InlineSpan[] = [];
  let rest = text;
  while (rest) {
    const boldMatch = BOLD_PATTERN.exec(rest);
    const codeMatch = CODE_PATTERN.exec(rest);
    let earliest: RegExpExecArray | null;
    if (boldMatch && codeMatch) {
      earliest = boldMatch.index <= codeMatch.index ? boldMatch : codeMatch;
    } else {
      earliest = boldMatch ?? codeMatch;
    }
    if (!earliest) {
      spans.push({ kind: "text", value: rest });
      break;
    }
    if (earliest.index > 0) {
      spans.push({ kind: "text", value: rest.slice(0, earliest.index) });
    }
    if (earliest === boldMatch && boldMatch !== null) {
      spans.push({ kind: "strong", value: boldMatch[1] });
    } else if (codeMatch !== null) {
      spans.push({ kind: "code", value: codeMatch[1] });
    }
    rest = rest.slice(earliest.index + earliest[0].length);
  }
  return spans.length > 0 ? spans : [{ kind: "text", value: "" }];
}

function headingLevel(hashCount: number): 1 | 2 | 3 {
  if (hashCount <= 1) return 1;
  if (hashCount === 2) return 2;
  return 3;
}

export function parseTutorBlocks(content: string): TutorBlock[] {
  const blocks: TutorBlock[] = [];
  let pendingList: { ordered: boolean; items: InlineSpan[][] } | null = null;

  const flushList = () => {
    if (pendingList) {
      blocks.push({ kind: "list", ...pendingList });
      pendingList = null;
    }
  };

  for (const rawLine of content.split("\n")) {
    const line = rawLine.trim();
    if (!line) {
      flushList();
      continue;
    }
    const heading = HEADING_PATTERN.exec(line);
    if (heading) {
      flushList();
      blocks.push({
        kind: "heading",
        level: headingLevel(heading[1].length),
        spans: parseInlineSpans(heading[2]),
      });
      continue;
    }
    const unordered = UNORDERED_ITEM_PATTERN.exec(line);
    if (unordered) {
      if (pendingList && !pendingList.ordered) {
        pendingList.items.push(parseInlineSpans(unordered[1]));
      } else {
        flushList();
        pendingList = { ordered: false, items: [parseInlineSpans(unordered[1])] };
      }
      continue;
    }
    const ordered = ORDERED_ITEM_PATTERN.exec(line);
    if (ordered) {
      if (pendingList && pendingList.ordered) {
        pendingList.items.push(parseInlineSpans(ordered[1]));
      } else {
        flushList();
        pendingList = { ordered: true, items: [parseInlineSpans(ordered[1])] };
      }
      continue;
    }
    flushList();
    blocks.push({ kind: "paragraph", spans: parseInlineSpans(line) });
  }
  flushList();
  return blocks;
}

function renderSpans(spans: InlineSpan[]): ReactNode {
  return spans.map((span, index) => {
    if (span.kind === "strong") {
      return <strong className={styles.tutorRichStrong} key={index}>{span.value}</strong>;
    }
    if (span.kind === "code") {
      return <code className={styles.tutorRichCode} key={index}>{span.value}</code>;
    }
    return <Fragment key={index}>{span.value}</Fragment>;
  });
}

export function TutorRichText({ content }: { content: string }) {
  const blocks = parseTutorBlocks(content);
  return (
    <div className={styles.tutorRich}>
      {blocks.map((block, index) => {
        if (block.kind === "heading") {
          if (block.level === 1) {
            return (
              <h3 className={styles.tutorRichHeading1} key={index}>
                {renderSpans(block.spans)}
              </h3>
            );
          }
          if (block.level === 2) {
            return (
              <h4 className={styles.tutorRichHeading2} key={index}>
                {renderSpans(block.spans)}
              </h4>
            );
          }
          return (
            <h5 className={styles.tutorRichHeading3} key={index}>
              {renderSpans(block.spans)}
            </h5>
          );
        }
        if (block.kind === "list") {
          const items = block.items.map((spans, itemIndex) => (
            <li key={itemIndex}>{renderSpans(spans)}</li>
          ));
          return block.ordered ? (
            <ol className={styles.tutorRichList} key={index}>
              {items}
            </ol>
          ) : (
            <ul className={styles.tutorRichList} key={index}>
              {items}
            </ul>
          );
        }
        return (
          <p className={styles.tutorRichParagraph} key={index}>
            {renderSpans(block.spans)}
          </p>
        );
      })}
    </div>
  );
}
