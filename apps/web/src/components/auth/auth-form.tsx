"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

import { api } from "@/lib/api";

type AuthFormProps = {
  mode: "login" | "register";
};

export function AuthForm({ mode }: AuthFormProps) {
  const router = useRouter();
  const isRegistration = mode === "register";
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);

    const formData = new FormData(event.currentTarget);
    const email = String(formData.get("email") ?? "");
    const password = String(formData.get("password") ?? "");

    try {
      if (isRegistration) {
        await api.register({
          email,
          password,
          username: String(formData.get("username") ?? ""),
        });
      } else {
        await api.login({ email, password });
      }
      router.push("/");
    } catch {
      setError(
        isRegistration
          ? "注册未成功，请检查填写内容后重试。"
          : "登录未成功，请检查邮箱和密码后重试。",
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main>
      <h1>{isRegistration ? "注册" : "登录"}</h1>
      <p>{isRegistration ? "创建你的学习空间。" : "登录后继续学习。"}</p>
      <form onSubmit={handleSubmit}>
        {isRegistration ? (
          <label>
            用户名
            <input autoComplete="username" name="username" required />
          </label>
        ) : null}
        <label>
          邮箱
          <input autoComplete="email" name="email" required type="email" />
        </label>
        <label>
          密码
          <input autoComplete={isRegistration ? "new-password" : "current-password"} name="password" required type="password" />
        </label>
        {error ? <p role="alert">{error}</p> : null}
        <button disabled={isSubmitting} type="submit">
          {isSubmitting ? "请稍候…" : isRegistration ? "注册" : "登录"}
        </button>
      </form>
      <a href={isRegistration ? "/login" : "/register"}>
        {isRegistration ? "已有账号？去登录" : "还没有账号？去注册"}
      </a>
    </main>
  );
}
