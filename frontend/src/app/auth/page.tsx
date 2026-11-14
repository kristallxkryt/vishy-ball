"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { FormEvent, Suspense, useState } from "react";
import { ArrowLeft, ArrowRight, Eye, EyeOff, GraduationCap, ShieldCheck } from "lucide-react";
import { apiRequest, LoginResponse } from "@/lib/api";

function AuthForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [mode, setMode] = useState<"login" | "register">(
    searchParams.get("mode") === "register" ? "register" : "login",
  );
  const [role, setRole] = useState<"student" | "teacher">("student");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setLoading(true);
    try {
      if (mode === "register") {
        await apiRequest("/api/auth/register", {
          method: "POST",
          body: JSON.stringify({ username, password, role }),
        });
      }
      const result = await apiRequest<LoginResponse>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ login: username, password }),
      });
      localStorage.setItem("vb_access_token", result.access_token);
      localStorage.setItem("vb_user", JSON.stringify(result.user));
      router.push("/dashboard");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Не удалось выполнить запрос.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden px-5 py-12">
      <div className="pointer-events-none absolute inset-0 grid-glow opacity-70" />
      <div className="pointer-events-none absolute -left-40 top-1/4 h-96 w-96 rounded-full bg-lime/[0.08] blur-[120px]" />
      <Link href="/" className="absolute left-6 top-6 inline-flex items-center gap-2 text-sm font-semibold text-muted transition hover:text-white sm:left-10 sm:top-9"><ArrowLeft size={16} /> На главную</Link>
      <div className="glass relative w-full max-w-[460px] rounded-[30px] p-7 sm:p-10">
        <Link href="/" className="mx-auto flex w-fit items-center gap-3">
          <span className="grid h-11 w-11 place-items-center rounded-xl bg-lime text-ink"><GraduationCap size={24} /></span>
          <span className="text-sm font-black tracking-tight">ВЫСШИЙ<span className="text-lime">БАЛЛ</span></span>
        </Link>
        <div className="mt-9 text-center">
          <p className="eyebrow">{mode === "login" ? "С возвращением" : "Первый шаг к цели"}</p>
          <h1 className="mt-3 text-3xl font-black tracking-tight">{mode === "login" ? "Войти в аккаунт" : "Создать аккаунт"}</h1>
          <p className="mt-3 text-sm leading-6 text-muted">{mode === "login" ? "Продолжай подготовку с того места, где остановился." : "Выбери роль и присоединяйся к платформе."}</p>
        </div>
        <div className="mt-8 grid grid-cols-2 rounded-xl border border-white/[0.08] bg-black/20 p-1">
          <button type="button" onClick={() => { setMode("login"); setError(""); }} className={`rounded-lg py-2.5 text-sm font-bold transition ${mode === "login" ? "bg-white/10 text-white" : "text-muted hover:text-white"}`}>Вход</button>
          <button type="button" onClick={() => { setMode("register"); setError(""); }} className={`rounded-lg py-2.5 text-sm font-bold transition ${mode === "register" ? "bg-white/10 text-white" : "text-muted hover:text-white"}`}>Регистрация</button>
        </div>
        <form onSubmit={handleSubmit} className="mt-6 space-y-4">
          {mode === "register" && (
            <>
              <label className="block text-xs font-bold text-white/75">Имя пользователя<input required minLength={3} maxLength={32} value={username} onChange={(e) => setUsername(e.target.value)} placeholder="Например, student_01" className="mt-2 w-full rounded-xl border border-white/10 bg-black/20 px-4 py-3.5 text-sm outline-none transition placeholder:text-muted/60 focus:border-lime/60" /></label>
              <div className="block text-xs font-bold text-white/75">Тип аккаунта<div className="mt-2 grid grid-cols-2 gap-2">{(["student", "teacher"] as const).map((value) => <button key={value} type="button" onClick={() => setRole(value)} className={`rounded-xl border px-3 py-3 text-sm font-bold transition ${role === value ? "border-lime/50 bg-lime/10 text-lime" : "border-white/10 bg-black/20 text-muted hover:text-white"}`}>{value === "student" ? "Ученик" : "Учитель"}</button>)}</div></div>
            </>
          )}
          {mode === "login" && <label className="block text-xs font-bold text-white/75">Логин<input required value={username} onChange={(e) => setUsername(e.target.value)} placeholder="Имя пользователя" className="mt-2 w-full rounded-xl border border-white/10 bg-black/20 px-4 py-3.5 text-sm outline-none transition placeholder:text-muted/60 focus:border-lime/60" /></label>}
          <label className="block text-xs font-bold text-white/75">Пароль<div className="relative mt-2"><input required minLength={8} type={showPassword ? "text" : "password"} value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Не менее 8 символов" className="w-full rounded-xl border border-white/10 bg-black/20 px-4 py-3.5 pr-12 text-sm outline-none transition placeholder:text-muted/60 focus:border-lime/60" /><button type="button" onClick={() => setShowPassword(!showPassword)} aria-label={showPassword ? "Скрыть пароль" : "Показать пароль"} className="absolute right-4 top-1/2 -translate-y-1/2 text-muted hover:text-white">{showPassword ? <EyeOff size={17} /> : <Eye size={17} />}</button></div></label>
          {error && <p role="alert" className="rounded-xl border border-red-400/20 bg-red-400/10 px-4 py-3 text-sm text-red-200">{error}</p>}
          <button disabled={loading} className="flex w-full items-center justify-center gap-2 rounded-xl bg-lime px-5 py-4 text-sm font-black text-ink transition hover:bg-[#e1e5eb] disabled:cursor-wait disabled:opacity-60">{loading ? "Подождите..." : mode === "login" ? "Войти в аккаунт" : "Создать аккаунт"} {!loading && <ArrowRight size={17} />}</button>
        </form>
        <div className="mt-6 flex items-center justify-center gap-2 text-[11px] text-muted"><ShieldCheck size={14} className="text-lime" /> Пароль защищён надёжным хешированием</div>
      </div>
    </main>
  );
}

export default function AuthPage() {
  return <Suspense fallback={<div className="grid min-h-screen place-items-center text-muted">Загрузка...</div>}><AuthForm /></Suspense>;
}
