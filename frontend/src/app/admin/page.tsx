"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  Activity, AlertTriangle, ArrowLeft, BookOpen, CheckCircle2, ClipboardList,
  GraduationCap, LayoutDashboard, LogOut,
  Plus, RefreshCw, ShieldCheck, Users, X,
} from "lucide-react";
import { apiRequest, ApiUser } from "@/lib/api";

type Overview = {
  users: { total: number; students: number; teachers: number; admins: number; active_students: number };
  learning: { total_attempts: number; correct_attempts: number; wrong_attempts: number; accuracy_percent: number; students_with_attempts: number; unique_tasks_solved: number; available_tasks: number };
  reviews: { pending: number };
};
type Student = { rank: number; user_id: number; username: string; total_attempts: number; accuracy_percent: number; total_score: number; max_score: number; pending_reviews: number; is_active: boolean };
type Topic = { subject_code: string; topic: string; total_attempts: number; wrong_attempts: number; error_percent: number; students_count: number };
type AdminUser = { id: number; username: string; email: string | null; role: "student" | "teacher" | "admin"; is_active: boolean; created_at: string };
type UsersResponse = { total: number; users: AdminUser[] };
type Subject = { subject_code: string; name: string; task_count: number };

const tabs = [
  { id: "overview", label: "Обзор", icon: LayoutDashboard },
  { id: "users", label: "Пользователи", icon: Users },
  { id: "tasks", label: "Банк заданий", icon: BookOpen },
] as const;
type Tab = typeof tabs[number]["id"];

const inputClass = "w-full rounded-xl border border-white/10 bg-[#10161e] px-3.5 py-3 text-sm text-white outline-none placeholder:text-muted focus:border-lime/50";
const panelClass = "rounded-2xl border border-white/[0.08] bg-panel p-5 sm:p-6";

export default function AdminPage() {
  const router = useRouter();
  const [tab, setTab] = useState<Tab>("overview");
  const [user, setUser] = useState<ApiUser | null>(null);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [students, setStudents] = useState<Student[]>([]);
  const [topics, setTopics] = useState<Topic[]>([]);
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [userTotal, setUserTotal] = useState(0);
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [query, setQuery] = useState("");
  const [showTaskForm, setShowTaskForm] = useState(false);
  const [taskForm, setTaskForm] = useState({ subject_code: "", topic: "", exam_number: "1", variant_label: "Вариант 1", question: "", answer: "", difficulty: "medium" });

  const token = () => localStorage.getItem("vb_access_token") || "";

  const loadOverview = useCallback(async (auth: string) => {
    const [summary, ranking, problemTopics] = await Promise.all([
      apiRequest<Overview>("/api/admin/analytics/overview", {}, auth),
      apiRequest<{ students: Student[] }>("/api/admin/analytics/students?limit=8&offset=0", {}, auth),
      apiRequest<{ topics: Topic[] }>("/api/admin/analytics/problem-topics?limit=8", {}, auth),
    ]);
    setOverview(summary);
    setStudents(ranking.students);
    setTopics(problemTopics.topics);
  }, []);

  const loadUsers = useCallback(async (auth: string, search = "") => {
    const params = new URLSearchParams({ limit: "50", offset: "0" });
    if (search.trim()) params.set("q", search.trim());
    const data = await apiRequest<UsersResponse>(`/api/users?${params.toString()}`, {}, auth);
    setUsers(data.users);
    setUserTotal(data.total);
  }, []);

  const loadSubjects = useCallback(async (auth: string) => {
    const data = await apiRequest<{ subjects: Subject[] }>("/api/admin/subjects?include_inactive=true", {}, auth);
    setSubjects(data.subjects);
    if (!taskForm.subject_code && data.subjects.length) setTaskForm((old) => ({ ...old, subject_code: data.subjects[0].subject_code }));
  }, [taskForm.subject_code]);

  const refresh = useCallback(async (auth: string, activeTab: Tab) => {
    setError("");
    if (activeTab === "overview") await loadOverview(auth);
    if (activeTab === "users") await loadUsers(auth, query);
    if (activeTab === "tasks") await loadSubjects(auth);
  }, [loadOverview, loadSubjects, loadUsers, query]);

  useEffect(() => {
    const auth = token();
    if (!auth) { router.replace("/auth"); return; }
    apiRequest<ApiUser>("/api/auth/me", {}, auth)
      .then(async (me) => {
        if (me.role !== "admin") { router.replace("/dashboard"); return; }
        setUser(me);
        await loadOverview(auth);
      })
      .catch((cause) => {
        localStorage.removeItem("vb_access_token");
        localStorage.removeItem("vb_user");
        setError(cause instanceof Error ? cause.message : "Не удалось проверить доступ.");
        router.replace("/auth");
      })
      .finally(() => setLoading(false));
  }, [router, loadOverview]);

  useEffect(() => {
    if (!user || tab === "overview") return;
    refresh(token(), tab).catch((cause) => setError(cause instanceof Error ? cause.message : "Ошибка загрузки раздела."));
  }, [tab, user, refresh]);

  async function logout() {
    const auth = token();
    try { if (auth) await apiRequest("/api/auth/logout", { method: "POST" }, auth); } catch { /* clear local session regardless */ }
    localStorage.removeItem("vb_access_token");
    localStorage.removeItem("vb_user");
    router.replace("/");
  }

  async function updateUser(id: number, path: "role" | "status", body: object) {
    setBusy(true); setError(""); setNotice("");
    try {
      const updated = await apiRequest<{ message: string }>(`/api/users/${id}/${path}`, { method: "PATCH", body: JSON.stringify(body) }, token());
      setNotice(updated.message);
      await loadUsers(token(), query);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Не удалось изменить пользователя."); }
    finally { setBusy(false); }
  }

  async function createTask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(""); setNotice("");
    try {
      const response = await apiRequest<{ message: string }>("/api/admin/tasks", {
        method: "POST",
        body: JSON.stringify({
          subject_code: taskForm.subject_code,
          topic: taskForm.topic,
          question: taskForm.question,
          answer: taskForm.answer,
          difficulty: taskForm.difficulty,
          task_type: "text",
          exam_number: Number(taskForm.exam_number) || null,
          variant_label: taskForm.variant_label || null,
        }),
      }, token());
      setNotice(response.message);
      setTaskForm((old) => ({ ...old, topic: "", question: "", answer: "", variant_label: "Вариант 1" }));
      setShowTaskForm(false);
      await loadSubjects(token());
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Не удалось создать задание."); }
    finally { setBusy(false); }
  }

  return (
    <main className="min-h-screen bg-ink text-white">
      <aside className="fixed inset-y-0 left-0 z-20 hidden w-[250px] flex-col border-r border-white/[0.07] bg-[#10151c] px-5 py-7 lg:flex">
        <Link href="/" className="flex items-center gap-3 px-2"><span className="grid h-10 w-10 place-items-center rounded-xl bg-lime text-ink"><GraduationCap size={22}/></span><span className="text-sm font-black">ВЫСШИЙ<span className="text-lime">БАЛЛ</span></span></Link>
        <div className="mt-12 rounded-xl border border-lime/20 bg-lime/[0.07] px-3 py-3 text-sm font-bold text-lime"><ShieldCheck className="mr-2 inline" size={17}/> Администрирование</div>
        <p className="mb-3 mt-8 px-3 text-[10px] font-black uppercase tracking-[.18em] text-muted">Панель управления</p>
        <nav className="space-y-1">{tabs.map(({id,label,icon:Icon}) => <button key={id} onClick={() => setTab(id)} className={`flex w-full items-center gap-3 rounded-xl px-3 py-3 text-left text-sm font-semibold transition ${tab===id ? "bg-lime/10 text-lime" : "text-muted hover:bg-white/5 hover:text-white"}`}><Icon size={17}/>{label}</button>)}</nav>
        <div className="mt-auto"><Link href="/dashboard" className="flex items-center gap-3 rounded-xl px-3 py-3 text-sm font-semibold text-muted hover:bg-white/5 hover:text-white"><ArrowLeft size={17}/> Обычный кабинет</Link><button onClick={logout} className="mt-2 flex w-full items-center gap-3 rounded-xl px-3 py-3 text-sm font-semibold text-muted hover:bg-white/5 hover:text-white"><LogOut size={17}/> Выйти</button></div>
      </aside>

      <div className="lg:pl-[250px]">
        <header className="flex min-h-[76px] items-center justify-between border-b border-white/[0.07] px-5 sm:px-9">
          <div><p className="text-xs text-muted">Высший балл / Администрирование</p><h1 className="mt-1 text-lg font-extrabold">{tabs.find((item)=>item.id===tab)?.label}</h1></div>
          <div className="flex items-center gap-3"><span className="hidden text-xs text-muted sm:block">{user?.username || "Администратор"}</span><button onClick={() => refresh(token(),tab).catch((e)=>setError(e.message))} className="grid h-10 w-10 place-items-center rounded-xl border border-white/10 text-muted hover:text-white" aria-label="Обновить"><RefreshCw size={16}/></button></div>
        </header>
        <div className="mx-auto max-w-[1400px] px-5 py-8 sm:px-9 sm:py-10">
          <div className="mb-6 flex gap-2 overflow-x-auto lg:hidden">{tabs.map(({id,label})=><button key={id} onClick={()=>setTab(id)} className={`whitespace-nowrap rounded-xl px-4 py-2 text-sm font-bold ${tab===id?"bg-lime text-ink":"bg-panel text-muted"}`}>{label}</button>)}</div>
          {error && <div role="alert" className="mb-5 flex items-start gap-2 rounded-xl border border-red-400/20 bg-red-400/10 p-4 text-sm text-red-200"><AlertTriangle size={17} className="mt-0.5 shrink-0"/>{error}</div>}
          {notice && <div role="status" className="mb-5 flex items-start gap-2 rounded-xl border border-white/10 bg-white/[0.05] p-4 text-sm text-white"><CheckCircle2 size={17} className="mt-0.5 shrink-0 text-lime"/>{notice}<button onClick={()=>setNotice("")} className="ml-auto"><X size={16}/></button></div>}
          {loading ? <div className="grid min-h-60 place-items-center text-sm text-muted">Проверяем доступ администратора…</div> : (
            <>
              {tab==="overview" && overview && <div className="space-y-8">
                <div><p className="eyebrow">СОСТОЯНИЕ ПЛАТФОРМЫ</p><h2 className="mt-2 text-3xl font-black">Общая картина</h2><p className="mt-2 text-sm text-muted">Данные рассчитаны по существующим аккаунтам и проверенным попыткам.</p></div>
                <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                  {[
                    { label: "Пользователи", value: overview.users.total, icon: Users },
                    { label: "Ученики", value: overview.users.students, icon: GraduationCap },
                    { label: "Учителя", value: overview.users.teachers, icon: ClipboardList },
                    { label: "Активные ученики", value: overview.users.active_students, icon: Activity },
                    { label: "Попытки", value: overview.learning.total_attempts, icon: BookOpen },
                    { label: "Точность", value: `${overview.learning.accuracy_percent}%`, icon: Activity },
                    { label: "Задания в банке", value: overview.learning.available_tasks, icon: BookOpen },
                    { label: "Ожидают проверки", value: overview.reviews.pending, icon: AlertTriangle },
                  ].map(({ label, value, icon: Icon }) => <article key={label} className={panelClass}><div className="flex items-center justify-between text-xs font-semibold text-muted">{label}<Icon size={18} className="text-lime"/></div><p className="mt-5 text-3xl font-black tabular-nums">{value}</p></article>)}
                </div>
                <div className="grid gap-5 xl:grid-cols-2">
                  <section className={panelClass}><div className="mb-5 flex items-center justify-between"><h3 className="font-extrabold">Рейтинг учеников</h3><span className="text-xs text-muted">По точности</span></div><div className="space-y-3">{students.map((s)=><div key={s.user_id} className="flex items-center gap-3 border-b border-white/[0.06] pb-3 last:border-0"><span className="grid h-8 w-8 place-items-center rounded-lg bg-white/[0.06] text-xs font-black text-lime">{s.rank}</span><div className="min-w-0 flex-1"><p className="truncate text-sm font-bold">{s.username}</p><p className="text-xs text-muted">{s.total_attempts} ответов</p></div><span className="text-sm font-extrabold tabular-nums">{s.accuracy_percent}%</span></div>)}{!students.length&&<p className="text-sm text-muted">Пока нет проверенных попыток.</p>}</div></section>
                  <section className={panelClass}><div className="mb-5 flex items-center justify-between"><h3 className="font-extrabold">Сложные темы</h3><AlertTriangle size={17} className="text-muted"/></div><div className="space-y-3">{topics.map((t,i)=><div key={t.subject_code+t.topic} className="border-b border-white/[0.06] pb-3 last:border-0"><div className="flex items-center justify-between gap-3"><p className="text-sm font-bold">{t.topic}</p><span className="text-sm font-extrabold tabular-nums">{t.error_percent}% ошибок</span></div><p className="mt-1 text-xs text-muted">{t.subject_code} · {t.total_attempts} попыток · {t.students_count} учеников</p><div className="mt-2 h-1.5 overflow-hidden rounded-full bg-white/10"><div className="h-full rounded-full bg-lime" style={{width:`${Math.min(100,t.error_percent)}%`}}/></div></div>)}{!topics.length&&<p className="text-sm text-muted">Пока недостаточно данных для аналитики.</p>}</div></section>
                </div>
              </div>}
              {tab==="users" && <section className={panelClass}><div className="flex flex-wrap items-center justify-between gap-4"><div><h2 className="text-xl font-black">Пользователи</h2><p className="mt-1 text-xs text-muted">Всего аккаунтов: {userTotal}</p></div><input value={query} onChange={(e)=>setQuery(e.target.value)} onKeyDown={(e)=>{if(e.key==="Enter")loadUsers(token(),query).catch((x)=>setError(x.message));}} placeholder="Поиск по логину или email" className={`${inputClass} max-w-sm`}/></div><div className="mt-6 overflow-x-auto"><table className="w-full min-w-[700px] text-left text-sm"><thead className="text-xs text-muted"><tr><th className="pb-3">Пользователь</th><th className="pb-3">Роль</th><th className="pb-3">Статус</th><th className="pb-3">Изменить роль</th><th className="pb-3">Доступ</th></tr></thead><tbody>{users.map((u)=><tr key={u.id} className="border-t border-white/[0.06]"><td className="py-4"><p className="font-bold">{u.username}</p><p className="mt-1 text-xs text-muted">{u.email||"Без email"} · #{u.id}</p></td><td className="py-4 text-muted">{u.role==="admin"?"Администратор":u.role==="teacher"?"Учитель":"Ученик"}</td><td className="py-4"><span className={u.is_active?"text-lime":"text-red-300"}>{u.is_active?"Активен":"Заблокирован"}</span></td><td className="py-4"><select disabled={busy||u.id===user?.id} value={u.role} onChange={(e)=>updateUser(u.id,"role",{role:e.target.value})} className="rounded-lg border border-white/10 bg-[#10161e] px-2 py-2 text-xs"><option value="student">Ученик</option><option value="teacher">Учитель</option><option value="admin">Администратор</option></select></td><td className="py-4"><button disabled={busy||u.id===user?.id} onClick={()=>updateUser(u.id,"status",{is_active:!u.is_active})} className="rounded-lg border border-white/10 px-3 py-2 text-xs font-bold hover:border-lime/40 disabled:opacity-40">{u.is_active?"Заблокировать":"Разблокировать"}</button></td></tr>)}</tbody></table>{!users.length&&<p className="py-8 text-center text-sm text-muted">Пользователи не найдены.</p>}</div></section>}
              {tab==="tasks" && <section className={panelClass}><div className="flex flex-wrap items-center justify-between gap-4"><div><h2 className="text-xl font-black">Банк заданий</h2><p className="mt-1 text-xs text-muted">Управление предметами и добавление заданий в банк.</p></div><button onClick={()=>setShowTaskForm((v)=>!v)} className="inline-flex items-center gap-2 rounded-xl bg-lime px-4 py-3 text-sm font-black text-ink"><Plus size={16}/>{showTaskForm?"Скрыть форму":"Добавить задание"}</button></div>
                {showTaskForm&&<form onSubmit={createTask} className="mt-6 grid gap-4 rounded-2xl border border-white/10 bg-black/10 p-5 sm:grid-cols-2"><label className="text-xs font-bold text-muted">Предмет<select required value={taskForm.subject_code} onChange={(e)=>setTaskForm({...taskForm,subject_code:e.target.value})} className={`${inputClass} mt-2`}>{subjects.map(s=><option key={s.subject_code} value={s.subject_code}>{s.name}</option>)}</select></label><label className="text-xs font-bold text-muted">Тема<input required value={taskForm.topic} onChange={(e)=>setTaskForm({...taskForm,topic:e.target.value})} className={`${inputClass} mt-2`} placeholder="Например, орфография"/></label><label className="text-xs font-bold text-muted">Номер задания ЕГЭ<input type="number" min="1" max="100" value={taskForm.exam_number} onChange={(e)=>setTaskForm({...taskForm,exam_number:e.target.value})} className={`${inputClass} mt-2`}/></label><label className="text-xs font-bold text-muted">Метка варианта<input value={taskForm.variant_label} onChange={(e)=>setTaskForm({...taskForm,variant_label:e.target.value})} className={`${inputClass} mt-2`}/></label><label className="text-xs font-bold text-muted sm:col-span-2">Условие<textarea required rows={4} value={taskForm.question} onChange={(e)=>setTaskForm({...taskForm,question:e.target.value})} className={`${inputClass} mt-2`}/></label><label className="text-xs font-bold text-muted">Правильный ответ<input required value={taskForm.answer} onChange={(e)=>setTaskForm({...taskForm,answer:e.target.value})} className={`${inputClass} mt-2`}/></label><label className="text-xs font-bold text-muted">Сложность<select value={taskForm.difficulty} onChange={(e)=>setTaskForm({...taskForm,difficulty:e.target.value})} className={`${inputClass} mt-2`}><option value="easy">Базовая</option><option value="medium">Средняя</option><option value="hard">Сложная</option></select></label><div className="sm:col-span-2 flex justify-end"><button disabled={busy} className="rounded-xl bg-lime px-5 py-3 text-sm font-black text-ink disabled:opacity-50">{busy?"Сохраняем…":"Сохранить задание"}</button></div></form>}
                <div className="mt-7 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{subjects.map((s)=><div key={s.subject_code} className="flex items-center gap-3 rounded-xl border border-white/[0.07] bg-black/10 p-4"><span className="grid h-10 w-10 place-items-center rounded-xl bg-white/[0.05] text-lime"><BookOpen size={18}/></span><div className="min-w-0 flex-1"><p className="truncate text-sm font-bold">{s.name}</p><p className="text-xs text-muted">{s.subject_code}</p></div><span className="text-sm font-black tabular-nums">{s.task_count}</span></div>)}</div>
              </section>}
            </>
          )}
        </div>
      </div>
    </main>
  );
}

