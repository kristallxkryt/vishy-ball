"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowLeft, ArrowRight, ChevronLeft, ChevronRight, Save, Send } from "lucide-react";
import { apiRequest } from "@/lib/api";

type ExamTask = {
  id: number; position: number; exam_number: number; topic: string; question: string;
  task_type: string; options: unknown[]; media: Array<{ url?: string; alt?: string }>;
  answer: unknown; result: { status: string; is_correct: number | null; score: number | null; max_score: number | null } | null;
};
type Attempt = {
  id: number; subject_code: string; mode: string; variant_label: string | null;
  status: "in_progress" | "submitted"; score: number | null; max_score: number | null;
  pending_review_count: number; tasks_count: number; answered_count: number; tasks: ExamTask[];
};

function optionList(options: unknown[]) {
  return options.map((item, index) => {
    if (typeof item === "string") return { id: String(index), label: item };
    if (item && typeof item === "object") {
      const value = item as Record<string, unknown>;
      return { id: String(value.id ?? value.value ?? index), label: String(value.label ?? value.text ?? value.value ?? `Вариант ${index + 1}`) };
    }
    return { id: String(index), label: String(item) };
  });
}

export default function MockExamPage() {
  const params = useParams<{ attempt_id: string }>();
  const router = useRouter();
  const attemptId = Number(params.attempt_id);
  const [attempt, setAttempt] = useState<Attempt | null>(null);
  const [index, setIndex] = useState(0);
  const [answer, setAnswer] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const token = () => localStorage.getItem("vb_access_token") || "";

  const load = useCallback(async () => {
    const auth = token();
    if (!auth) { router.replace("/auth"); return; }
    try {
      const data = await apiRequest<{ attempt: Attempt }>(`/api/mock-exams/attempts/${attemptId}`, {}, auth);
      setAttempt(data.attempt);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Не удалось загрузить вариант.");
    } finally { setLoading(false); }
  }, [attemptId, router]);

  useEffect(() => { if (Number.isFinite(attemptId) && attemptId > 0) void load(); }, [attemptId, load]);

  const task = attempt?.tasks[index] ?? null;
  const options = useMemo(() => optionList(task?.options ?? []), [task]);
  const choice = task?.task_type === "single_choice" || task?.task_type === "multiple_choice";
  const multiple = task?.task_type === "multiple_choice";
  const structured = task?.task_type === "matching" || task?.task_type === "ordering";

  useEffect(() => {
    if (!task) return;
    if (choice) {
      if (Array.isArray(task.answer)) setSelected(task.answer.map(String));
      else if (task.answer !== null && task.answer !== undefined) setSelected([String(task.answer)]);
      else setSelected([]);
      setAnswer("");
    } else if (task.answer !== null && task.answer !== undefined) {
      setAnswer(typeof task.answer === "string" ? task.answer : JSON.stringify(task.answer));
      setSelected([]);
    } else { setSelected([]); setAnswer(""); }
  }, [task, choice]);

  function currentAnswer(): unknown {
    if (choice) return multiple ? selected : (selected[0] ?? "");
    if (structured) {
      try { return JSON.parse(answer); } catch { return answer; }
    }
    return answer;
  }

  async function saveCurrent(): Promise<boolean> {
    if (!attempt || !task || attempt.status !== "in_progress") return false;
    const value = currentAnswer();
    if (value === "" || (Array.isArray(value) && value.length === 0)) {
      setError("Сначала введи ответ.");
      return false;
    }
    setBusy(true); setError("");
    try {
      await apiRequest(`/api/mock-exams/attempts/${attempt.id}/answers/${task.id}`, {
        method: "PUT", body: JSON.stringify({ answer: value }),
      }, token());
      setAttempt((old) => old ? { ...old, tasks: old.tasks.map((item) => item.id === task.id ? { ...item, answer: value } : item), answered_count: old.tasks.filter((item) => item.id !== task.id && item.answer !== null && item.answer !== undefined).length + 1 } : old);
      return true;
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Не удалось сохранить ответ."); return false; }
    finally { setBusy(false); }
  }

  async function submitExam() {
    if (!attempt) return;
    setBusy(true); setError("");
    try {
      const data = await apiRequest<{ attempt: Attempt }>(`/api/mock-exams/attempts/${attempt.id}/submit`, { method: "POST" }, token());
      setAttempt(data.attempt);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "Не удалось завершить вариант."); }
    finally { setBusy(false); }
  }

  if (loading) return <main className="min-h-screen bg-ink p-8 text-white">Загружаем пробный вариант…</main>;
  if (!attempt) return <main className="min-h-screen bg-ink p-8 text-white"><p>{error || "Вариант не найден."}</p><Link href="/dashboard" className="mt-4 inline-block text-lime">В кабинет</Link></main>;

  return (
    <main className="min-h-screen bg-ink text-white">
      <header className="border-b border-white/[0.07] bg-[#10151c]">
        <div className="mx-auto flex h-[72px] max-w-[1100px] items-center justify-between px-5">
          <Link href={`/subjects/${encodeURIComponent(attempt.subject_code)}`} className="inline-flex items-center gap-2 text-sm font-semibold text-muted hover:text-white"><ArrowLeft size={16} /> К предмету</Link>
          <span className="text-xs font-bold text-muted">{attempt.variant_label || (attempt.mode === "bank_mix" ? "Сборный вариант" : "Пробный экзамен")}</span>
        </div>
      </header>
      <div className="mx-auto max-w-[900px] px-5 py-8 sm:py-12">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div><p className="eyebrow">ПРОБНЫЙ ЭКЗАМЕН</p><h1 className="mt-2 text-3xl font-black">{attempt.status === "submitted" ? "Результаты варианта" : "Выполнение варианта"}</h1><p className="mt-2 text-sm text-muted">Задание {Math.min(index + 1, attempt.tasks_count)} из {attempt.tasks_count}</p></div>
          {attempt.status === "submitted" && <div className="rounded-2xl border border-white/10 bg-panel px-5 py-3 text-right"><p className="text-xs text-muted">Результат</p><p className="mt-1 text-2xl font-black tabular-nums">{attempt.score ?? "—"} / {attempt.max_score ?? "—"}</p></div>}
        </div>
        <div className="mt-6 h-2 overflow-hidden rounded-full bg-white/10"><div className="h-full rounded-full bg-lime transition-all" style={{ width: `${((index + 1) / Math.max(attempt.tasks_count, 1)) * 100}%` }} /></div>
        {error && <div role="alert" className="mt-5 rounded-xl border border-red-400/20 bg-red-400/10 p-4 text-sm text-red-200">{error}</div>}
        {task && <section className="mt-7 rounded-3xl border border-white/[0.08] bg-panel p-6 sm:p-8">
          <div className="flex flex-wrap items-center gap-2 text-xs font-bold text-muted"><span className="rounded-full bg-white/[0.07] px-3 py-1.5">Задание №{task.exam_number}</span><span className="rounded-full bg-white/[0.07] px-3 py-1.5">{task.topic}</span></div>
          <div className="mt-6 whitespace-pre-wrap text-base leading-8">{task.question}</div>
          {task.media?.map((media, i) => media.url ? <img key={i} src={media.url} alt={media.alt || "Иллюстрация"} className="mt-5 max-h-[420px] rounded-xl object-contain" /> : null)}
          {choice ? <div className="mt-7 space-y-3">{options.map((option) => {
            const active = selected.includes(option.id);
            return <button key={option.id} type="button" disabled={attempt.status === "submitted"} onClick={() => setSelected((old) => multiple ? (active ? old.filter((v) => v !== option.id) : [...old, option.id]) : [option.id])} className={`flex w-full items-center gap-3 rounded-xl border p-4 text-left text-sm ${active ? "border-lime/50 bg-lime/[0.08]" : "border-white/10 bg-[#111821]"} disabled:opacity-70`}><span className={`h-5 w-5 rounded-${multiple ? "md" : "full"} border ${active ? "border-lime bg-lime" : "border-white/30"}`} />{option.label}</button>;
          })}</div> : <div className="mt-7"><label className="mb-2 block text-sm font-bold">{structured ? "Структурированный ответ (JSON)" : "Твой ответ"}</label><textarea disabled={attempt.status === "submitted"} value={answer} onChange={(e) => setAnswer(e.target.value)} rows={structured ? 5 : 3} placeholder={structured ? "Например: {&quot;1&quot;:&quot;А&quot;}" : "Введи ответ…"} className="w-full rounded-xl border border-white/10 bg-[#111821] p-4 text-sm outline-none focus:border-lime/50 disabled:opacity-70" /></div>}
          {attempt.status === "submitted" && task.result && <div className="mt-6 rounded-xl border border-white/10 bg-[#111821] p-4"><p className="font-bold">{task.result.status === "pending_review" ? "Ожидает ручной проверки" : task.result.is_correct ? "Верно" : "Неверно"}</p><p className="mt-1 text-sm text-muted">Баллы: {task.result.score ?? "—"} / {task.result.max_score ?? "—"}</p></div>}
          <div className="mt-8 flex flex-wrap items-center justify-between gap-3 border-t border-white/[0.07] pt-5">
            <button disabled={index === 0 || busy} onClick={async () => { const value = currentAnswer(); if (value !== "" && !(Array.isArray(value) && value.length === 0) && attempt.status === "in_progress" && !(await saveCurrent())) return; setIndex((v) => Math.max(0, v - 1)); }} className="inline-flex items-center gap-2 rounded-xl border border-white/10 px-4 py-3 text-sm font-bold disabled:opacity-30"><ChevronLeft size={16} /> Назад</button>
            <div className="flex flex-wrap gap-2">
              {attempt.status === "in_progress" && <button disabled={busy} onClick={saveCurrent} className="inline-flex items-center gap-2 rounded-xl border border-white/10 px-4 py-3 text-sm font-bold disabled:opacity-50"><Save size={16} /> {busy ? "Сохраняем…" : "Сохранить"}</button>}
              {index < attempt.tasks.length - 1 ? <button disabled={busy} onClick={async () => { const value = currentAnswer(); if (value !== "" && !(Array.isArray(value) && value.length === 0) && attempt.status === "in_progress" && !(await saveCurrent())) return; setIndex((v) => Math.min(attempt.tasks.length - 1, v + 1)); }} className="inline-flex items-center gap-2 rounded-xl bg-lime px-4 py-3 text-sm font-black text-ink disabled:opacity-50">Далее <ChevronRight size={16} /></button> : attempt.status === "in_progress" ? <button disabled={busy || attempt.answered_count !== attempt.tasks_count} onClick={submitExam} className="inline-flex items-center gap-2 rounded-xl bg-lime px-4 py-3 text-sm font-black text-ink disabled:opacity-40"><Send size={16} /> Завершить</button> : <Link href={`/subjects/${encodeURIComponent(attempt.subject_code)}`} className="inline-flex items-center gap-2 rounded-xl bg-lime px-4 py-3 text-sm font-black text-ink">К пробникам <ArrowRight size={16} /></Link>}
            </div>
          </div>
        </section>}
        {attempt.status === "in_progress" && <p className="mt-4 text-center text-xs text-muted">Сохраняй каждый ответ перед переходом дальше. Прогресс останется доступен после перезагрузки.</p>}
        {attempt.status === "submitted" && attempt.pending_review_count > 0 && <p className="mt-4 rounded-xl border border-amber-300/15 bg-amber-300/[0.05] p-4 text-sm text-amber-200">Часть ответов требует ручной проверки. Итоговые баллы могут измениться.</p>}
      </div>
    </main>
  );
}
