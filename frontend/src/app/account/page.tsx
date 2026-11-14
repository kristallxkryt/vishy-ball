"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import {
  ArrowLeft, CheckCircle2, ChevronRight, GraduationCap, KeyRound,
  Mail, ShieldCheck, UserRound,
} from "lucide-react";
import { apiRequest, ApiUser } from "@/lib/api";

type Flow = "email" | "password";

export default function AccountPage() {
  const router = useRouter();
  const [user, setUser] = useState<ApiUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [activeFlow, setActiveFlow] = useState<Flow | null>(null);
  const [email, setEmail] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [code, setCode] = useState("");
  const [step, setStep] = useState<"form" | "code">("form");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem("vb_access_token");
    if (!token) {
      router.replace("/auth");
      return;
    }
    apiRequest<ApiUser>("/api/auth/me", {}, token)
      .then((me) => {
        setUser(me);
        setEmail(me.email);
        localStorage.setItem("vb_user", JSON.stringify(me));
      })
      .catch(() => {
        localStorage.removeItem("vb_access_token");
        localStorage.removeItem("vb_user");
        router.replace("/auth");
      })
      .finally(() => setLoading(false));
  }, [router]);

  function openFlow(flow: Flow) {
    setActiveFlow(flow);
    setStep("form");
    setCode("");
    setError("");
    setNotice("");
    setCurrentPassword("");
    setNewPassword("");
    if (flow === "email") setEmail(user?.email || "");
  }

  async function handleRequestCode(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const token = localStorage.getItem("vb_access_token");
    if (!token || !activeFlow) return;
    setError("");
    setNotice("");
    setSubmitting(true);
    try {
      const path = activeFlow === "email"
        ? "/api/auth/email-change/request"
        : "/api/auth/password-change/request";
      const body = activeFlow === "email"
        ? { new_email: email.trim() }
        : { current_password: currentPassword, new_password: newPassword };
      const result = await apiRequest<{ message: string }>(path, {
        method: "POST",
        body: JSON.stringify(body),
      }, token);
      setNotice(result.message || "Код подтверждения отправлен на почту.");
      setStep("code");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Не удалось отправить код.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleConfirmCode(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const token = localStorage.getItem("vb_access_token");
    if (!token || !activeFlow) return;
    setError("");
    setSubmitting(true);
    try {
      const path = activeFlow === "email"
        ? "/api/auth/email-change/confirm"
        : "/api/auth/password-change/confirm";
      const result = await apiRequest<{ message: string; user?: ApiUser }>(path, {
        method: "POST",
        body: JSON.stringify({ code: code.trim() }),
      }, token);
      if (result.user) {
        setUser(result.user);
        localStorage.setItem("vb_user", JSON.stringify(result.user));
      }
      setNotice(result.message || "Изменения сохранены.");
      setActiveFlow(null);
      setStep("form");
      setCode("");
      setCurrentPassword("");
      setNewPassword("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Не удалось подтвердить код.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="min-h-screen bg-ink px-5 py-8 sm:px-8 sm:py-12">
      <div className="mx-auto max-w-3xl">
        <Link href="/dashboard" className="inline-flex items-center gap-2 text-sm font-semibold text-muted transition hover:text-white">
          <ArrowLeft size={16} /> Вернуться в личный кабинет
        </Link>

        <header className="mt-9 flex items-center gap-4">
          <span className="grid h-12 w-12 place-items-center rounded-2xl bg-lime text-ink">
            <GraduationCap size={25} />
          </span>
          <div>
            <p className="eyebrow">ПРОФИЛЬ И БЕЗОПАСНОСТЬ</p>
            <h1 className="mt-1 text-3xl font-black tracking-tight">Настройки аккаунта</h1>
          </div>
        </header>

        {error && <p role="alert" className="mt-7 rounded-xl border border-red-400/20 bg-red-400/10 px-4 py-3 text-sm text-red-200">{error}</p>}
        {notice && <p role="status" className="mt-7 flex items-center gap-2 rounded-xl border border-lime/20 bg-lime/[0.07] px-4 py-3 text-sm text-lime"><CheckCircle2 size={17} />{notice}</p>}

        <section className="mt-8 rounded-3xl border border-white/[0.08] bg-panel p-6 sm:p-8">
          <div className="flex items-center gap-3">
            <span className="grid h-10 w-10 place-items-center rounded-xl bg-white/[0.06] text-lime"><UserRound size={19} /></span>
            <div><h2 className="font-extrabold">Личные данные</h2><p className="mt-1 text-xs text-muted">Информация, связанная с аккаунтом</p></div>
          </div>
          {loading ? <div className="mt-7 h-16 animate-pulse rounded-xl bg-white/[0.04]" /> : (
            <dl className="mt-7 grid gap-5 sm:grid-cols-2">
              <div><dt className="text-xs font-semibold text-muted">Имя пользователя</dt><dd className="mt-2 font-bold">{user?.username || "—"}</dd></div>
              <div><dt className="text-xs font-semibold text-muted">Тип аккаунта</dt><dd className="mt-2 font-bold">{user?.role === "teacher" ? "Учитель" : user?.role === "admin" ? "Администратор" : "Ученик"}</dd></div>
              <div className="sm:col-span-2"><dt className="text-xs font-semibold text-muted">Текущая почта</dt><dd className="mt-2 flex items-center gap-2 font-bold"><Mail size={15} className="text-lime" />{user?.email || "—"}</dd></div>
            </dl>
          )}
        </section>

        <section className="mt-5 grid gap-4 sm:grid-cols-2">
          <button type="button" onClick={() => openFlow("email")} className="group rounded-3xl border border-white/[0.08] bg-panel p-6 text-left transition hover:border-lime/30">
            <span className="grid h-11 w-11 place-items-center rounded-xl bg-lime/10 text-lime"><Mail size={20} /></span>
            <h2 className="mt-5 font-extrabold">Изменить почту</h2>
            <p className="mt-2 text-sm leading-6 text-muted">Подтвердим новый адрес кодом, отправленным на него.</p>
            <span className="mt-5 inline-flex items-center gap-2 text-xs font-bold text-lime">Изменить адрес <ChevronRight size={15} className="transition group-hover:translate-x-1" /></span>
          </button>
          <button type="button" onClick={() => openFlow("password")} className="group rounded-3xl border border-white/[0.08] bg-panel p-6 text-left transition hover:border-lime/30">
            <span className="grid h-11 w-11 place-items-center rounded-xl bg-lime/10 text-lime"><KeyRound size={20} /></span>
            <h2 className="mt-5 font-extrabold">Изменить пароль</h2>
            <p className="mt-2 text-sm leading-6 text-muted">Понадобится текущий пароль и код подтверждения из письма.</p>
            <span className="mt-5 inline-flex items-center gap-2 text-xs font-bold text-lime">Сменить пароль <ChevronRight size={15} className="transition group-hover:translate-x-1" /></span>
          </button>
        </section>

        {activeFlow && (
          <section className="mt-5 rounded-3xl border border-lime/20 bg-lime/[0.04] p-6 sm:p-8">
            <div className="flex items-center gap-3">
              <span className="grid h-10 w-10 place-items-center rounded-xl bg-lime/10 text-lime"><ShieldCheck size={19} /></span>
              <div><h2 className="font-extrabold">{activeFlow === "email" ? "Новый адрес почты" : "Новый пароль"}</h2><p className="mt-1 text-xs text-muted">{step === "form" ? "Сначала укажи новые данные" : "Введи код из письма"}</p></div>
            </div>
            {step === "form" ? (
              <form onSubmit={handleRequestCode} className="mt-6 space-y-4">
                {activeFlow === "email" ? (
                  <label className="block text-xs font-bold text-white/75">Новая электронная почта<input required type="email" value={email} onChange={(event) => setEmail(event.target.value)} className="mt-2 w-full rounded-xl border border-white/10 bg-black/20 px-4 py-3.5 text-sm outline-none focus:border-lime/60" /></label>
                ) : (
                  <>
                    <label className="block text-xs font-bold text-white/75">Текущий пароль<input required type="password" autoComplete="current-password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} className="mt-2 w-full rounded-xl border border-white/10 bg-black/20 px-4 py-3.5 text-sm outline-none focus:border-lime/60" /></label>
                    <label className="block text-xs font-bold text-white/75">Новый пароль<input required minLength={8} maxLength={128} type="password" autoComplete="new-password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} placeholder="Не менее 8 символов" className="mt-2 w-full rounded-xl border border-white/10 bg-black/20 px-4 py-3.5 text-sm outline-none focus:border-lime/60" /></label>
                  </>
                )}
                <div className="flex flex-wrap gap-3 pt-2">
                  <button disabled={submitting} className="rounded-xl bg-lime px-5 py-3 text-sm font-black text-ink transition hover:bg-[#d5ff86] disabled:opacity-60">{submitting ? "Отправляем..." : "Отправить код"}</button>
                  <button type="button" onClick={() => setActiveFlow(null)} className="rounded-xl border border-white/10 px-5 py-3 text-sm font-bold text-muted transition hover:text-white">Отмена</button>
                </div>
              </form>
            ) : (
              <form onSubmit={handleConfirmCode} className="mt-6 space-y-4">
                <label className="block text-xs font-bold text-white/75">Код подтверждения<input required inputMode="numeric" autoComplete="one-time-code" minLength={6} maxLength={6} pattern="[0-9]{6}" value={code} onChange={(event) => setCode(event.target.value.replace(/\D/g, "").slice(0, 6))} placeholder="000000" className="mt-2 w-full rounded-xl border border-white/10 bg-black/20 px-4 py-3.5 text-center text-xl font-black tracking-[.4em] outline-none focus:border-lime/60" /></label>
                <div className="flex flex-wrap gap-3 pt-2">
                  <button disabled={submitting || code.length !== 6} className="rounded-xl bg-lime px-5 py-3 text-sm font-black text-ink transition hover:bg-[#d5ff86] disabled:opacity-60">{submitting ? "Проверяем..." : "Подтвердить"}</button>
                  <button type="button" onClick={() => { setStep("form"); setCode(""); }} className="rounded-xl border border-white/10 px-5 py-3 text-sm font-bold text-muted transition hover:text-white">Назад</button>
                </div>
              </form>
            )}
          </section>
        )}
      </div>
    </main>
  );
}
