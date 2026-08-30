import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { parseTutorBlocks, TutorRichText } from "./tutor-rich-text";

describe("parseTutorBlocks", () => {
  it("splits headings, lists and paragraphs into ordered blocks", () => {
    const blocks = parseTutorBlocks(
      "## 原理与机制\n正文第一段。\n\n1. 第一步\n2. 第二步\n\n- 要点甲\n- 要点乙\n### 次要标题\n结尾。",
    );

    expect(blocks.map((block) => block.kind)).toEqual([
      "heading",
      "paragraph",
      "list",
      "list",
      "heading",
      "paragraph",
    ]);
    const [heading, , ordered, unordered, minor] = blocks;
    expect(heading).toMatchObject({ kind: "heading", level: 2 });
    expect(ordered).toMatchObject({ kind: "list", ordered: true });
    expect(unordered).toMatchObject({ kind: "list", ordered: false });
    expect(minor).toMatchObject({ kind: "heading", level: 3 });
  });

  it("parses bold and inline code spans including multiple per line", () => {
    const blocks = parseTutorBlocks("结论:**路径损耗** 随距离增大,见 `公式 (1-2)`,**易错**。");
    const spans = blocks[0].kind === "paragraph" ? blocks[0].spans : [];
    expect(spans.map((span) => span.kind)).toEqual([
      "text",
      "strong",
      "text",
      "code",
      "text",
      "strong",
      "text",
    ]);
  });

  it("keeps unclosed markers as literal text instead of swallowing them", () => {
    const blocks = parseTutorBlocks("这是 ** 未闭合 的重点");
    const spans = blocks[0].kind === "paragraph" ? blocks[0].spans : [];
    expect(spans.every((span) => span.kind === "text")).toBe(true);
    expect(spans.map((span) => (span.kind === "text" ? span.value : "")).join("")).toContain("**");
  });
});

describe("TutorRichText", () => {
  it("renders hierarchical headings with decreasing levels and bold emphasis", () => {
    render(
      <TutorRichText
        content={"## 原理与机制\n结论:**路径损耗** 随距离增大,见 `公式 (1-2)`。\n### 补充说明\n- 对照组\n"}
      />,
    );

    expect(screen.getByRole("heading", { level: 4, name: "原理与机制" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 5, name: "补充说明" })).toBeInTheDocument();

    const strong = screen.getByText("路径损耗");
    expect(strong.tagName).toBe("STRONG");
    const code = screen.getByText("公式 (1-2)");
    expect(code.tagName).toBe("CODE");
    expect(within(screen.getByRole("list")).getByText("对照组")).toBeInTheDocument();
  });

  it("distinguishes ordered and unordered lists", () => {
    const { container } = render(<TutorRichText content={"1. 先列式\n2. 再代入\n\n- 注意单位\n"} />);
    expect(container.querySelector("ol")).not.toBeNull();
    expect(container.querySelector("ul")).not.toBeNull();
  });

  it("never interprets raw HTML in model output", () => {
    render(<TutorRichText content={"<img src=x onerror=alert(1)>安全验证"} />);
    expect(document.querySelector("img")).toBeNull();
    expect(screen.getByText(/<img/)).toBeInTheDocument();
  });
});
