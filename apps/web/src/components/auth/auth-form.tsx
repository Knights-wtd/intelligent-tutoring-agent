"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

import { api } from "@/lib/api";

import styles from "./auth-form.module.css";

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
    const identifier = String(formData.get("identifier") ?? "");
    const password = String(formData.get("password") ?? "");

    if (isRegistration && password.length < 12) {
      setError("密码至少需要 12 位。");
      setIsSubmitting(false);
      return;
    }

    try {
      if (isRegistration) {
        await api.register({
          email: String(formData.get("email") ?? ""),
          password,
          username: String(formData.get("username") ?? ""),
        });
      } else {
        await api.login({ identifier, password });
      }
      router.push("/");
    } catch {
      setError(
        isRegistration
          ? "注册未成功，请检查填写内容后重试。"
          : "登录未成功，请检查邮箱/用户名和密码后重试。",
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className={styles.authPage}>
      <section className={styles.authCard}>
        <div className={styles.brandMark}>知</div>
        <span className={styles.eyebrow}>知学空间 · 教材学习工作台</span>
        <h1>{isRegistration ? "注册" : "登录"}</h1>
        <p className={styles.subtitle}>
          {isRegistration ? "创建你的学习空间，开始一套可追溯的学习流程。" : "欢迎回来，登录后继续学习。"}
        </p>
        <form className={styles.form} onSubmit={handleSubmit}>
        {isRegistration ? (
          <label className={styles.field}>
            用户名
            <input autoComplete="username" name="username" required />
          </label>
        ) : null}
        {isRegistration ? (
          <label className={styles.field}>
            邮箱
            <input autoComplete="email" name="email" required type="email" />
          </label>
        ) : (
          <label className={styles.field}>
            邮箱或用户名
            <input autoComplete="username" name="identifier" required type="text" />
          </label>
        )}
        <label className={styles.field}>
          密码
          <input aria-label="密码" autoComplete={isRegistration ? "new-password" : "current-password"} name="password" required type="password" />
          {isRegistration ? <small>至少 12 位</small> : null}
        </label>
        {error ? <p className={styles.error} role="alert">{error}</p> : null}
        <button className={styles.submitButton} disabled={isSubmitting} type="submit">
          {isSubmitting ? "请稍候…" : isRegistration ? "注册" : "登录"}
        </button>
        </form>
        <a className={styles.switchLink} href={isRegistration ? "/login" : "/register"}>
          {isRegistration ? "已有账号？去登录" : "还没有账号？去注册"}
        </a>
      </section>
    </main>
  );
}
