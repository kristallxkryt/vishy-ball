"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  ArrowRight, BookOpen, CheckCircle2, ChevronRight, GraduationCap,
  LayoutDashboard, LogOut, Target, TrendingUp, UserRound, ChevronDown, Settings,
} from "lucide-react";
import { apiRequest, ApiUser } from "@/lib/api";

type Subject = { subject_code: string; name: string; task_count: number };
type SubjectsResponse = { total_subjects: number; subjects: Subject[] };
type Stats = {
  total_answered: number;
  correct_answers: number;
  wrong_answers: number;
  accuracy_percent: number;
  total_score: number;
  max_score: number;
  score_percent: number;
  subjects: Array<{ subject_code: string; total_answered: number; accuracy_percent: number }>;
};

const subjectMarks: Record<string, string> = {
  russian: "РУ", "math-profile": "МП", "math-basic": "МБ", informatics: "ИН",
  physics: "ФИ", chemistry: "ХИ", biology: "БИ", history: "ИС",
  "social-studies": "ОБ", literature: "ЛИ", geography: "ГЕ", english: "АН",
};

export default function DashboardPage() {
  const router = useRouter();
  const [user, setUser] = useState<ApiUser | null>(null);
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [profileMenuOpen, setProfileMenuOpen] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem("vb_access_token");
    if (!token) { router.replace("/auth"); return; }
    const storedUser = localStorage.getItem("vb_user");
    if (storedUser) {
      try { setUser(JSON.parse(storedUser) as ApiUser); } catch { localStorage.removeItem("vb_user"); }
    }
    Promise.all([
      apiRequest<SubjectsResponse>("/api/tasks/subjects"),
      apiRequest<Stats>("/api/profile/stats", {}, token),
      apiRequest<ApiUser>("/api/auth/me", {}, token),
    ]).then(([catalog, progress, me]) => {
      setSubjects(catalog.subjects);
      setStats(progress);
      setUser(me);
      localStorage.setItem("vb_user", JSON.stringify(me));
    }).catch((cause) => {
      if (cause instanceof Error && /сессия|авториз|токен/i.test(cause.message)) {
        localStorage.removeItem("vb_access_token");
        localStorage.removeItem("vb_user");
        router.replace("/auth");
      } else {
        setError(cause instanceof Error ? cause.message : "Не удалось загрузить данные.");
      }
    }).finally(() => setLoading(false));
  }, [router]);

  async function logout() {
    const token = localStorage.getItem("vb_access_token");
    try { if (token) await apiRequest("/api/auth/logout", { method: "POST" }, token); } catch { /* local logout still proceeds */ }
    localStorage.removeItem("vb_access_token");
    localStorage.removeItem("vb_user");
    router.replace("/");
  }

  return (
    <main className="min-h-screen bg-ink">
      <aside className="fixed inset-y-0 left-0 z-20 hidden w-[248px] flex-col border-r border-white/[0.07] bg-[#0e1411] px-5 py-7 lg:flex">
        <Link href="/" className="flex items-center gap-3 px-2"><span className="grid h-10 w-10 place-items-center rounded-xl bg-lime text-ink"><GraduationCap size={22} /></span><span className="text-sm font-black">ВЫСШИЙ<span className="text-lime">БАЛЛ</span></span></Link>
        <p className="mb-3 mt-12 px-3 text-[10px] font-black uppercase tracking-[.18em] text-muted">Рабочее пространство</p>
        <div className="space-y-1"><div className="flex items-center gap-3 rounded-xl bg-lime/10 px-3 py-3 text-sm font-bold text-lime"><LayoutDashboard size={17} /> Обзор</div><a href="#subjects" className="flex items-center gap-3 rounded-xl px-3 py-3 text-sm font-semibold text-muted transition hover:bg-white/5 hover:text-white"><BookOpen size={17} /> Предметы</a><a href="#progress" className="flex items-center gap-3 rounded-xl px-3 py-3 text-sm font-semibold text-muted transition hover:bg-white/5 hover:text-white"><TrendingUp size={17} /> Мой прогресс</a></div>
        <div className="mt-auto rounded-2xl border border-lime/15 bg-lime/[0.06] p-4"><Target size={20} className="text-lime" /><p className="mt-3 text-sm font-bold">Маленький шаг каждый день</p><p className="mt-1 text-xs leading-5 text-muted">Регулярная практика помогает приблизиться к цели.</p></div>
        <button onClick={logout} className="mt-5 flex items-center gap-3 rounded-xl px-3 py-3 text-sm font-semibold text-muted transition hover:bg-white/5 hover:text-white"><LogOut size={17} /> Выйти</button>
      </aside>

      <div className="lg:pl-[248px]">
        <header className="flex h-[76px] items-center justify-between border-b border-white/[0.07] px-6 sm:px-10">
          <div><p className="text-xs text-muted">Личный кабинет</p><p className="mt-1 text-sm font-bold">Обзор подготовки</p></div>
          <div className="relative flex items-center gap-3">
            <span className="hidden text-right sm:block"><span className="block text-xs font-bold">{user?.username || "Ученик"}</span><span className="text-[10px] capitalize text-muted">{user?.role === "teacher" ? "Учитель" : user?.role === "admin" ? "Администратор" : "Ученик"}</span></span>
            <button type="button" onClick={() => setProfileMenuOpen((open) => !open)} aria-expanded={profileMenuOpen} aria-label="Меню профиля" className="flex h-10 items-center gap-2 rounded-full border border-white/10 bg-panel px-3 text-lime transition hover:border-lime/30">
              <UserRound size={18} /><ChevronDown size={14} className={`transition ${profileMenuOpen ? "rotate-180" : ""}`} />
            </button>
            {profileMenuOpen && (
              <div className="absolute right-0 top-12 z-40 w-56 overflow-hidden rounded-2xl border border-white/10 bg-[#151e19] p-2 shadow-2xl">
                <Link href="/dashboard" onClick={() => setProfileMenuOpen(false)} className="flex items-center gap-3 rounded-xl px-3 py-3 text-sm font-semibold text-white transition hover:bg-white/[0.06]">
                  <LayoutDashboard size={16} className="text-lime" /> Личный кабинет
                </Link>
                <Link href="/account" onClick={() => setProfileMenuOpen(false)} className="flex items-center gap-3 rounded-xl px-3 py-3 text-sm font-semibold text-white transition hover:bg-white/[0.06]">
                  <Settings size={16} className="text-lime" /> Настройки аккаунта
                </Link>
                <button onClick={logout} className="flex w-full items-center gap-3 rounded-xl px-3 py-3 text-left text-sm font-semibold text-muted transition hover:bg-white/[0.06] hover:text-white">
                  <LogOut size={16} /> Выйти
                </button>
              </div>
            )}
          </div>
        </header>
        <div className="mx-auto max-w-[1280px] px-6 py-9 sm:px-10 sm:py-12">
          <div className="flex flex-wrap items-end justify-between gap-5"><div><p className="eyebrow">ТВОЙ ПЛАН НА РЕЗУЛЬТАТ</p><h1 className="mt-3 text-3xl font-black tracking-tight sm:text-4xl">Привет, {user?.username || "будущий стобалльник"} 👋</h1><p className="mt-3 text-sm text-muted">Продолжай двигаться вперёд. Каждый ответ имеет значение.</p></div><Link href="#subjects" className="inline-flex items-center gap-2 rounded-xl bg-lime px-4 py-3 text-sm font-black text-ink transition hover:bg-[#d5ff86]">Выбрать предмет <ArrowRight size={16} /></Link></div>
          {error && <div role="alert" className="mt-7 rounded-2xl border border-red-400/20 bg-red-400/10 p-4 text-sm text-red-200">{error}</div>}
          <section id="progress" className="mt-9 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {[
              { label: "Решено заданий", value: stats?.total_answered ?? "—", icon: BookOpen, hint: "Всего ответов" },
              { label: "Правильные ответы", value: stats ? stats.correct_answers : "—", icon: CheckCircle2, hint: "Успешная практика" },
              { label: "Точность", value: stats ? `${stats.accuracy_percent}%` : "—", icon: Target, hint: "Доля верных ответов" },
              { label: "Набрано баллов", value: stats ? `${stats.total_score} / ${stats.max_score}` : "—", icon: TrendingUp, hint: "По проверенным работам" },
            ].map(({ label, value, icon: Icon, hint }) => <article key={label} className="rounded-2xl border border-white/[0.07] bg-panel p-5"><div className="flex items-center justify-between"><span className="text-xs font-semibold text-muted">{label}</span><Icon size={18} className="text-lime" /></div><p className="mt-5 text-3xl font-black tracking-tight">{loading ? "…" : value}</p><p className="mt-2 text-[11px] text-muted">{hint}</p></article>)}
          </section>

          <section id="subjects" className="mt-12">
            <div className="flex items-end justify-between"><div><p className="eyebrow">КАТАЛОГ ЕГЭ</p><h2 className="mt-3 text-2xl font-black tracking-tight">Выбери предмет</h2></div><span className="text-xs text-muted">{subjects.length} предметов</span></div>
            {loading ? <div className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{[1,2,3,4,5,6].map((item) => <div key={item} className="h-36 animate-pulse rounded-2xl border border-white/[0.06] bg-panel" />)}</div> : (
              <div className="mt-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                {subjects.map((subject, index) => <Link href={`/subjects/${encodeURIComponent(subject.subject_code)}`} key={subject.subject_code} className="group relative isolate min-h-[184px] overflow-hidden rounded-[24px] border border-white/[0.08] bg-[#131c17] p-6 transition duration-300 hover:-translate-y-1 hover:border-lime/30 hover:shadow-[0_18px_50px_-28px_rgba(190,242,100,.28)]">
                  <div className="pointer-events-none absolute -right-10 -top-12 -z-10 h-40 w-40 rounded-full bg-lime/[0.055] blur-3xl transition group-hover:bg-lime/[0.13]" />
                  <div className="flex items-start justify-between">
                    <span className="grid h-12 w-12 place-items-center rounded-2xl border border-lime/15 bg-lime/[0.08] text-xs font-black tracking-wide text-lime">{subjectMarks[subject.subject_code] || subject.name.slice(0,2).toUpperCase()}</span>
                    <span className="text-[11px] font-bold tabular-nums text-white/20">{String(index + 1).padStart(2, "0")}</span>
                  </div>
                  <div className="mt-7 flex items-end justify-between gap-3">
                    <div><h3 className="text-[17px] font-extrabold tracking-tight text-white transition group-hover:text-lime">{subject.name}</h3><p className="mt-2 text-xs font-medium text-muted">{subject.task_count} заданий <span className="mx-1 text-white/20">·</span> каталог</p></div>
                    <span className="mb-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-full border border-white/[0.08] bg-white/[0.025] text-muted transition group-hover:border-lime/30 group-hover:bg-lime group-hover:text-ink"><ChevronRight size={17} /></span>
                  </div>
                </Link>)}
              </div>
            )}
            {!loading && subjects.length === 0 && <p className="mt-6 rounded-2xl border border-white/[0.07] bg-panel p-6 text-sm text-muted">В каталоге пока нет активных предметов.</p>}
          </section>
          <div className="mt-12 rounded-2xl border border-lime/15 bg-lime/[0.05] p-6"><div className="flex items-start gap-4"><span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-lime/10 text-lime"><Target size={19} /></span><div><h3 className="font-extrabold">Следующий шаг — практика</h3><p className="mt-1 text-sm leading-6 text-muted">Выбери предмет, найди нужную тему и начни решать задания. Разделы тренажёра подключим к каталогу следующим этапом.</p></div></div></div>
        </div>
      </div>
    </main>
  );
}
