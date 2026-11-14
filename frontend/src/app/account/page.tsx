"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";
import { ArrowLeft, CheckCircle2, GraduationCap, KeyRound, UserRound } from "lucide-react";
import { apiRequest, ApiUser } from "@/lib/api";

export default function AccountPage() {
  const router = useRouter();
  const [user, setUser] = useState<ApiUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
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
        localStorage.setItem("vb_user", JSON.stringify(me));
      })
      .catch(() => {
        localStorage.removeItem("vb_access_token");
        localStorage.removeItem("vb_user");
        router.replace("/auth");
      })
      .finally(() => setLoading(false));
  }, [router]);

  async function changePassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setNotice("");
    if (newPassword !== confirmPassword) {
      setError("Новый пароль и подтверждение не совпадают.");
      return;
    }
    const token = localStorage.getItem("vb_access_token");
    if (!token) {
      router.replace("/auth");
      return;
    }
    setSubmitting(true);
    try {
      const result = await apiRequest<{ message: string }>("/api/auth/password-change", {
        method: "POST",
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      }, token);
      setNotice(result.message);
      localStorage.removeItem("vb_access_token");
      localStorage.removeItem("vb_user");
      router.replace("/auth");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Не удалось изменить пароль.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="min-h-screen bg-ink px-5 py-8 text-white sm:px-8 sm:py-12">
      <div className="mx-auto max-w-3xl">
        <Link href="/dashboard" className="inline-flex items-center gap-2 text-sm font-semibold text-muted transition hover:text-white">
          <ArrowLeft size={16} /> Вернуться в личный кабинет
        </Link>

        <header className="mt-9 flex items-center gap-4">
          <span className="grid h-12 w-12 place-items-center rounded-2xl bg-lime text-ink">
            <GraduationCap size={25} />
          </span>
          <div>
            <p className="eyebrow">ПРОФИЛЬ</p>
            <h1 className="mt-1 text-3xl font-black tracking-tight">Настройки аккаунта</h1>
          </div>
        </header>

        {error && <p role="alert" className="mt-7 rounded-xl border border-red-400/20 bg-red-400/10 px-4 py-3 text-sm text-red-200">{error}</p>}
        {notice && <p role="status" className="mt-7 flex items-center gap-2 rounded-xl border border-white/15 bg-white/[0.05] px-4 py-3 text-sm text-white"><CheckCircle2 size={17} />{notice}</p>}

        <section className="mt-8 rounded-3xl border border-white/[0.08] bg-panel p-6 sm:p-8">
          <div className="flex items-center gap-3">
            <span className="grid h-10 w-10 place-items-center rounded-xl bg-white/[0.06] text-muted"><UserRound size={19} /></span>
            <div><h2 className="font-extrabold">Личные данные</h2><p className="mt-1 text-xs text-muted">Информация аккаунта</p></div>
          </div>
          {loading ? <div className="mt-7 h-16 animate-pulse rounded-xl bg-white/[0.04]" /> : (
            <dl className="mt-7 grid gap-5 sm:grid-cols-2">
              <div><dt className="text-xs font-semibold text-muted">Имя пользователя</dt><dd className="mt-2 font-bold">{user?.username || "—"}</dd></div>
              <div><dt className="text-xs font-semibold text-muted">Тип аккаунта</dt><dd className="mt-2 font-bold">{user?.role === "teacher" ? "Учитель" : user?.role === "admin" ? "Администратор" : "Ученик"}</dd></div>
                          </dl>
          )}
        </section>

        <section className="mt-5 rounded-3xl border border-white/[0.08] bg-panel p-6 sm:p-8">
          <div className="flex items-center gap-3">
            <span className="grid h-10 w-10 place-items-center rounded-xl bg-white/[0.06] text-muted"><KeyRound size={19} /></span>
            <div><h2 className="font-extrabold">Изменение пароля</h2><p className="mt-1 text-xs text-muted">Подтверждение по электронной почте не требуется</p></div>
          </div>
          <form onSubmit={changePassword} className="mt-6 space-y-4">
            <label className="block text-xs font-bold text-white/75">Текущий пароль<input required minLength={8} maxLength={128} type="password" autoComplete="current-password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} className="mt-2 w-full rounded-xl border border-white/10 bg-black/20 px-4 py-3.5 text-sm outline-none focus:border-white/30" /></label>
            <label className="block text-xs font-bold text-white/75">Новый пароль<input required minLength={8} maxLength={128} type="password" autoComplete="new-password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} className="mt-2 w-full rounded-xl border border-white/10 bg-black/20 px-4 py-3.5 text-sm outline-none focus:border-white/30" /></label>
            <label className="block text-xs font-bold text-white/75">Повтори новый пароль<input required minLength={8} maxLength={128} type="password" autoComplete="new-password" value={confirmPassword} onChange={(event) => setConfirmPassword(event.target.value)} className="mt-2 w-full rounded-xl border border-white/10 bg-black/20 px-4 py-3.5 text-sm outline-none focus:border-white/30" /></label>
            <button disabled={submitting || loading} className="rounded-xl bg-lime px-5 py-3 text-sm font-black text-ink transition hover:bg-white disabled:opacity-60">{submitting ? "Сохраняем..." : "Изменить пароль"}</button>
          </form>
        </section>
      </div>
    </main>
  );
}
