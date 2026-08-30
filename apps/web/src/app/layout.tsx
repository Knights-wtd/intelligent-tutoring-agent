import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "教材知识库工作台",
  description: "教材知识库学习工作台",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="zh-CN" className="h-full antialiased">
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
