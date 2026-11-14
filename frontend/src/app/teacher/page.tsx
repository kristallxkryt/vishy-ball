"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowLeft, BookOpen, Check, ChevronDown, ClipboardList, Plus, RefreshCw, Send, Users } from "lucide-react";
import { apiRequest, ApiUser } from "@/lib/api";

type ClassItem = { id: number; name: string; subject_code: string; subject_name: string; is_active: boolean; members_count?: number };
type TaskItem = { id: number; subject_code: string; topic: string; question: string; exam_number: number | null; variant_label: string | null; task_type: string; difficulty: string | null };
type TaskResponse = TaskItem[];

const fieldClass = "w-full rounded-xl border border-white/10 bg-[#111821] px-3.5 py-3 text-sm text-white outline-none focus:border-lime/50";
const typeNames: Record<string, string> = { text: "Краткий ответ", single_choice: "Один вариант", multiple_choice: "Несколько вариантов", matching: "Соответствие", ordering: "Последовательность", long_text: "Развёрнутый ответ" };

export default function TeacherPage() {
  const router = useRouter();
  const [user, setUser] = useState<ApiUser | null>(null);
  const [classes, setClasses] = useState<ClassItem[]>([]);
  const [classId, setClassId] = useState("");
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const [selected, setSelected] = useState<number[]>([]);
  const [numberFilter, setNumberFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [name, setName] = useState("Новый вариант");
  const [description, setDescription] = useState("");
  const [assignNow, setAssignNow] = useState(true);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const token = () => localStorage.getItem("vb_access_token") || "";
  const activeClass = classes.find((item) => String(item.id) === classId) ?? null;

  useEffect(() => {
    const auth = token();
    if (!auth) { router.replace("/auth"); return; }
    Promise.all([
      apiRequest<ApiUser>("/api/auth/me", {}, auth),
      apiRequest<{ classes: ClassItem[] }>("/api/classes", {}, auth),
    ]).then(([me, data]) => {
      if (me.role !== "teacher") { router.replace(me.role === "admin" ? "/admin" : "/dashboard"); return; }
      setUser(me);
      setClasses(data.classes.filter((item) => item.is_active));
      if (data.classes.length) setClassId(String(data.classes.find((item) => item.is_active)?.id ?? ""));
    }).catch((cause) => setError(cause instanceof Error ? cause.message : "Не удалось загрузить классы."))
      .finally(() => setLoading(false));
  }, [router]);

  const loadTasks = useCallback(async (reset = false) => {
    if (!activeClass) return;
    const nextOffset = reset ? 0 : offset;
    setBusy(true); setError("");
    try {
      const data = await apiRequest<TaskResponse>(
        `/api/tasks/?subject_code=${encodeURIComponent(activeClass.subject_code)}&limit=50&offset=${nextOffset}`,
        {}, token(),
      );
      setTasks((old) => reset ? data : [...old, ...data]);
      setOffset(nextOffset + data.length);
      setHasMore(data.length === 50);
      if (reset) setSelected([]);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Не удалось загрузить банк заданий."); }
    finally { setBusy(false); }
  }, [activeClass, offset]);

  useEffect(() => {
    if (activeClass) { setTasks([]); setOffset(0); setSelected([]); void loadTasks(true); }
  // loadTasks is intentionally triggered when the selected class changes.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [classId]);

  const numbers = useMemo(() => Array.from(new Set(tasks.map((task) => task.exam_number).filter((value): value is number => value !== null))).sort((a, b) => a - b), [tasks]);
  const visibleTasks = useMemo(() => tasks.filter((task) => {
    const matchesNumber = numberFilter === "all" || String(task.exam_number) === numberFilter;
    const needle = query.trim().toLocaleLowerCase("ru");
    return matchesNumber && (!needle || task.question.toLocaleLowerCase("ru").includes(needle) || task.topic.toLocaleLowerCase("ru").includes(needle));
  }), [tasks, numberFilter, query]);
  const grouped = useMemo(() => {
    const map = new Map<string, TaskItem[]>();
    visibleTasks.forEach((task) => {
      const key = task.exam_number === null ? "Без номера" : String(task.exam_number);
      map.set(key, [...(map.get(key) ?? []), task]);
    });
    return Array.from(map.entries()).sort((a, b) => a[0] === "Без номера" ? 1 : b[0] === "Без номера" ? -1 : Number(a[0]) - Number(b[0]));
  }, [visibleTasks]);

  function toggleTask(id: number) {
    setSelected((old) => old.includes(id) ? old.filter((value) => value !== id) : [...old, id]);
  }
  function selectVisibleNumber(ids: number[]) {
    setSelected((old) => Array.from(new Set([...old, ...ids])));
  }
  async function createVariant() {
    if (!activeClass || selected.length === 0) { setError("Выбери класс и хотя бы одно задание."); return; }
    if (name.trim().length < 2) { setError("Название должно содержать не менее двух символов."); return; }
    setBusy(true); setError(""); setNotice("");
    try {
      const created = await apiRequest<{ variant: { id: number; name: string } }>("/api/variants", {
        method: "POST",
        body: JSON.stringify({ class_id: activeClass.id, name: name.trim(), description: description.trim() || null, task_ids: selected }),
      }, token());
      if (assignNow) {
        await apiRequest("/api/assignments", { method: "POST", body: JSON.stringify({ variant_id: created.variant.id }) }, token());
      }
      setNotice(assignNow ? "Вариант создан и назначен классу." : "Вариант сохранён. Его можно назначить позже.");
      setSelected([]);
      setName("Новый вариант");
      setDescription("");
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Не удалось создать вариант."); }
    finally { setBusy(false); }
  }

  if (loading) return <main className="min-h-screen bg-ink p-8 text-white">Загружаем кабинет учителя…</main>;

  return (
    <main className="min-h-screen bg-ink text-white">
      <header className="border-b border-white/[0.07] bg-[#10151c]">
        <div className="mx-auto flex h-[72px] max-w-[1250px] items-center justify-between px-5 sm:px-8">
          <Link href="/dashboard" className="inline-flex items-center gap-2 text-sm font-semibold text-muted hover:text-white"><ArrowLeft size={16} /> В кабинет</Link>
          <span className="text-sm font-black">КОНСТРУКТОР УЧИТЕЛЯ</span>
        </div>
      </header>
      <div className="mx-auto max-w-[1250px] px-5 py-8 sm:px-8 sm:py-11">
        <p className="eyebrow">УПРАВЛЕНИЕ РАБОТАМИ</p>
        <h1 className="mt-2 text-3xl font-black sm:text-4xl">Составить вариант</h1>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-muted">Выбирай отдельные задания или собирай работу по номерам ЕГЭ. Вариант будет сформирован из существующего банка и привязан к выбранному классу.</p>
        {error && <div role="alert" className="mt-6 rounded-xl border border-red-400/20 bg-red-400/10 p-4 text-sm text-red-200">{error}</div>}
        {notice && <div role="status" className="mt-6 rounded-xl border border-lime/20 bg-lime/[0.06] p-4 text-sm text-lime">{notice}</div>}
        <section className="mt-8 grid gap-4 lg:grid-cols-[.8fr_1.2fr]">
          <div className="space-y-4">
            <article className="rounded-2xl border border-white/[0.08] bg-panel p-5">
              <div className="mb-4 flex items-center gap-2"><Users size={18} className="text-lime" /><h2 className="font-extrabold">Класс и параметры</h2></div>
              <label className="mb-2 block text-xs font-bold text-muted">Класс</label>
              <select value={classId} onChange={(e) => setClassId(e.target.value)} className={fieldClass}>
                <option value="">Выбери класс</option>
                {classes.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.subject_name}</option>)}
              </select>
              {!classes.length && <p className="mt-3 text-xs leading-5 text-muted">Сначала создай класс в разделе управления классами.</p>}
              {activeClass && <p className="mt-3 text-xs text-muted">Предмет банка: <span className="font-bold text-white">{activeClass.subject_name}</span></p>}
              <div className="mt-5 space-y-3">
                <label className="block"><span className="mb-2 block text-xs font-bold text-muted">Название варианта</span><input value={name} onChange={(e) => setName(e.target.value)} className={fieldClass} maxLength={150} /></label>
                <label className="block"><span className="mb-2 block text-xs font-bold text-muted">Описание (необязательно)</span><textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={3} className={fieldClass} maxLength={2000} /></label>
                <label className="flex items-center gap-3 text-sm"><input type="checkbox" checked={assignNow} onChange={(e) => setAssignNow(e.target.checked)} className="accent-lime" /> Сразу назначить выбранному классу</label>
              </div>
            </article>
            <article className="rounded-2xl border border-white/[0.08] bg-panel p-5">
              <div className="flex items-center justify-between"><div className="flex items-center gap-2"><ClipboardList size={18} className="text-lime" /><h2 className="font-extrabold">Состав варианта</h2></div><span className="text-xs text-muted">{selected.length} выбрано</span></div>
              <p className="mt-3 text-xs leading-5 text-muted">Выбери конкретные задания в списке справа. Можно брать несколько заданий одного номера или смешивать разные номера.</p>
              <button onClick={() => setSelected([])} disabled={!selected.length} className="mt-4 text-xs font-bold text-muted hover:text-white disabled:opacity-30">Сбросить выбор</button>
              <button onClick={createVariant} disabled={busy || !activeClass || !selected.length} className="mt-4 flex w-full items-center justify-center gap-2 rounded-xl bg-lime px-4 py-3 text-sm font-black text-ink disabled:opacity-40">{busy ? "Сохраняем…" : assignNow ? "Создать и назначить" : "Сохранить вариант"} <Send size={16} /></button>
            </article>
          </div>
          <section className="rounded-2xl border border-white/[0.08] bg-panel p-5 sm:p-6">
            <div className="flex flex-wrap items-end justify-between gap-3"><div><p className="eyebrow">БАНК ЗАДАНИЙ</p><h2 className="mt-2 text-xl font-black">Выбор по типам ЕГЭ</h2></div><span className="text-xs text-muted">{tasks.length} загружено</span></div>
            <div className="mt-5 grid gap-3 sm:grid-cols-[1fr_190px]">
              <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Поиск по условию или теме…" className={fieldClass} />
              <div className="relative"><select value={numberFilter} onChange={(e) => setNumberFilter(e.target.value)} className={fieldClass}><option value="all">Все номера</option>{numbers.map((number) => <option key={number} value={number}>Задание №{number}</option>}</select><ChevronDown size={14} className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-muted" /></div>
            </div>
            {!activeClass ? <p className="mt-8 text-center text-sm text-muted">Выбери класс, чтобы загрузить задания его предмета.</p> : !tasks.length && busy ? <p className="mt-8 text-center text-sm text-muted">Загружаем банк…</p> : (
              <div className="mt-6 space-y-7">
                {grouped.map(([number, group]) => {
                  const groupIds = group.map((task) => task.id);
                  const allSelected = groupIds.every((id) => selected.includes(id));
                  return <div key={number}>
                    <div className="mb-3 flex items-center justify-between gap-3 border-b border-white/[0.08] pb-3"><h3 className="font-extrabold">{number === "Без номера" ? "Без номера ЕГЭ" : `Задание №${number}`} <span className="ml-1 text-xs font-medium text-muted">{group.length}</span></h3><button onClick={() => selectVisibleNumber(groupIds)} className="text-xs font-bold text-lime hover:text-white">{allSelected ? "Все выбраны" : "Выбрать все"}</button></div>
                    <div className="space-y-2">{group.map((task) => {
                      const active = selected.includes(task.id);
                      return <button type="button" key={task.id} onClick={() => toggleTask(task.id)} className={`flex w-full items-start gap-3 rounded-xl border p-3 text-left transition ${active ? "border-lime/40 bg-lime/[0.06]" : "border-white/[0.07] bg-[#111821] hover:border-white/20"}`}>
                        <span className={`mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-md border ${active ? "border-lime bg-lime text-ink" : "border-white/25 text-transparent"}`}>{active && <Check size={13} />}</span>
                        <span className="min-w-0 flex-1"><span className="block text-sm font-bold">{task.topic} <span className="font-normal text-muted">· {typeNames[task.task_type] || task.task_type}</span></span><span className="mt-1 block line-clamp-2 whitespace-pre-wrap text-xs leading-5 text-muted">{task.question}</span><span className="mt-2 block text-[10px] text-muted">{task.variant_label || "Без метки варианта"} · ID {task.id}</span></span>
                      </button>;
                    })}</div>
                  </div>;
                })}
                {!grouped.length && <p className="py-8 text-center text-sm text-muted">По фильтру заданий нет.</p>}
              </div>
            )}
            {hasMore && activeClass && <button disabled={busy} onClick={() => void loadTasks(false)} className="mt-6 flex w-full items-center justify-center gap-2 rounded-xl border border-white/10 px-4 py-3 text-sm font-bold text-muted hover:border-lime/30 hover:text-white disabled:opacity-40"><RefreshCw size={15} /> {busy ? "Загружаем…" : "Загрузить ещё задания"}</button>}
          </section>
        </section>
      </div>
    </main>
  );
}
