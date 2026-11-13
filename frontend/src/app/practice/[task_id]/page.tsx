"use client";

import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, CheckCircle2, GraduationCap, Send, Target } from "lucide-react";
import { apiRequest } from "@/lib/api";

type Option = { id?: string | number; value?: string | number; label?: string; text?: string; content?: string };
type Task = {
  id: number;
  subject_code: string;
  topic: string;
  question: string;
  difficulty: string | null;
  task_type: string;
  options: Option[];
  media: Array<{ url?: string; alt?: string; type?: string }>;
};
type CheckResult = {
  status: string;
  is_correct: boolean | null;
  score: number | null;
  max_score: number | null;
  message: string;
  hint?: string;
  explanation?: string;
};

export default function PracticePage() {
  const params = useParams<{ task_id: string }>();
  const searchParams = useSearchParams();
  const router = useRouter();
  const taskId = Number(params.task_id);
  const subjectCode = searchParams.get("subject") || "";

  const [task, setTask] = useState<Task | null>(null);
  const [answer, setAnswer] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [result, setResult] = useState<CheckResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const token = localStorage.getItem("vb_access_token");
    if (!token) { router.replace("/auth"); return; }
    if (!subjectCode || !Number.isInteger(taskId) || taskId < 1) {
      setError("Не удалось определить предмет или номер задания. Вернись в каталог и открой задание оттуда.");
      setLoading(false);
      return;
    }
    const query = new URLSearchParams({ subject_code: subjectCode, limit: "50", offset: "0" });
    apiRequest<Task[]>(`/api/tasks/?${query.toString()}`)
      .then((items) => {
        const found = items.find((item) => item.id === taskId);
        if (!found) throw new Error("Задание не найдено в каталоге.");
        setTask(found);
      })
      .catch((cause) => setError(cause instanceof Error ? cause.message : "Не удалось загрузить задание."))
      .finally(() => setLoading(false));
  }, [router, subjectCode, taskId]);

  const isSingleChoice = task?.task_type === "single_choice";
  const isMultipleChoice = task?.task_type === "multiple_choice";
  const isStructured = task && ["matching", "ordering"].includes(task.task_type);

  const normalizedOptions = useMemo(() => (task?.options || []).map((option, index) => ({
    id: String(option.id ?? option.value ?? index + 1),
    label: String(option.label ?? option.text ?? option.content ?? option.value ?? option.id ?? `Вариант ${index + 1}`),
  })), [task]);

  function toggleOption(id: string) {
    if (isSingleChoice) setSelected([id]);
    else setSelected((current) => current.includes(id) ? current.filter((value) => value !== id) : [...current, id]);
  }

  async function submitAnswer() {
    const token = localStorage.getItem("vb_access_token");
    if (!token || !task) { router.replace("/auth"); return; }
    let submitted: string | string[] = answer.trim();
    if (isSingleChoice) submitted = selected[0] || "";
    if (isMultipleChoice) submitted = selected;
    if (!submitted || (Array.isArray(submitted) && submitted.length === 0)) {
      setError("Сначала введи ответ или выбери вариант.");
      return;
    }
    setSubmitting(true);
    setError("");
    setResult(null);
    try {
      const response = await apiRequest<CheckResult>("/api/checking/answer", {
        method: "POST",
        body: JSON.stringify({ task_id: task.id, answer: submitted }),
      }, token);
      setResult(response);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Не удалось отправить ответ.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="min-h-screen bg-ink text-white">
      <header className="border-b border-white/[0.07] bg-[#0e1411]">
        <div className="mx-auto flex h-[76px] max-w-[1000px] items-center justify-between px-5 sm:px-8">
          <Link href="/dashboard" className="flex items-center gap-3">
            <span className="grid h-10 w-10 place-items-center rounded-xl bg-lime text-ink"><GraduationCap size={22} /></span>
            <span className="text-sm font-black tracking-wide">ВЫСШИЙ<span className="text-lime">БАЛЛ</span></span>
          </Link>
          <Link href={subjectCode ? `/subjects/${encodeURIComponent(subjectCode)}` : "/dashboard"} className="inline-flex items-center gap-2 text-sm font-semibold text-muted hover:text-white">
            <ArrowLeft size={16} /> К каталогу
          </Link>
        </div>
      </header>

      <div className="mx-auto max-w-[850px] px-5 py-9 sm:px-8 sm:py-12">
        <p className="eyebrow">САМОСТОЯТЕЛЬНАЯ ПРАКТИКА</p>
        <h1 className="mt-3 text-3xl font-black tracking-tight">Решение задания</h1>
        {loading ? (
          <div className="mt-8 h-64 animate-pulse rounded-3xl border border-white/[0.07] bg-panel" />
        ) : error && !task ? (
          <div role="alert" className="mt-8 rounded-2xl border border-red-400/20 bg-red-400/10 p-5 text-sm text-red-200">{error}</div>
        ) : task ? (
          <section className="mt-8 rounded-3xl border border-white/[0.08] bg-panel p-6 sm:p-9">
            <div className="flex flex-wrap items-center gap-2 text-xs font-bold text-muted">
              <span className="rounded-full bg-lime/10 px-3 py-1.5 text-lime">{task.topic}</span>
              <span className="rounded-full bg-white/[0.06] px-3 py-1.5">Задание №{task.id}</span>
              <span className="rounded-full bg-white/[0.06] px-3 py-1.5">{task.difficulty === "easy" ? "Базовый" : task.difficulty === "hard" ? "Сложный" : "Средний"}</span>
            </div>
            <div className="mt-7 whitespace-pre-wrap text-base leading-8 text-white/95">{task.question}</div>

            {task.media?.map((media, index) => media.url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img key={index} src={media.url} alt={media.alt || "Иллюстрация к заданию"} className="mt-6 max-h-[420px] rounded-2xl object-contain" />
            ) : null)}

            {isSingleChoice || isMultipleChoice ? (
              <div className="mt-8 space-y-3">
                <p className="text-sm font-bold">{isMultipleChoice ? "Выбери все подходящие варианты" : "Выбери один вариант"}</p>
                {normalizedOptions.map((option) => {
                  const active = selected.includes(option.id);
                  return (
                    <button key={option.id} type="button" onClick={() => toggleOption(option.id)} className={`flex w-full items-center gap-3 rounded-xl border p-4 text-left text-sm transition ${active ? "border-lime/50 bg-lime/[0.08] text-white" : "border-white/10 bg-[#101713] text-white/80 hover:border-white/20"}`}>
                      <span className={`grid h-5 w-5 shrink-0 place-items-center rounded-${isMultipleChoice ? "md" : "full"} border ${active ? "border-lime bg-lime text-ink" : "border-white/25"}`}>{active ? <CheckCircle2 size={14} /> : null}</span>
                      {option.label}
                    </button>
                  );
                })}
              </div>
            ) : (
              <div className="mt-8">
                <label htmlFor="answer" className="mb-2 block text-sm font-bold">
                  {isStructured ? "Ответ в формате JSON" : "Твой ответ"}
                </label>
                <textarea id="answer" value={answer} onChange={(event) => setAnswer(event.target.value)} rows={isStructured ? 5 : 3} placeholder={isStructured ? "Введи структуру ответа согласно условию…" : "Введи ответ здесь…"} className="w-full rounded-2xl border border-white/10 bg-[#101713] p-4 text-sm leading-6 outline-none transition placeholder:text-muted focus:border-lime/50" />
                {isStructured && <p className="mt-2 text-xs text-muted">Для заданий на сопоставление и порядок backend ожидает структурированный ответ. Введи корректный JSON.</p>}
              </div>
            )}

            {error && <p role="alert" className="mt-5 rounded-xl border border-red-400/20 bg-red-400/10 p-3 text-sm text-red-200">{error}</p>}

            <div className="mt-7 flex flex-wrap items-center justify-between gap-4 border-t border-white/[0.07] pt-6">
              <p className="inline-flex items-center gap-2 text-xs text-muted"><Target size={15} className="text-lime" /> Ответ будет сохранён в твоей статистике</p>
              <button onClick={submitAnswer} disabled={submitting} className="inline-flex items-center gap-2 rounded-xl bg-lime px-5 py-3 text-sm font-black text-ink transition hover:bg-[#d5ff86] disabled:cursor-not-allowed disabled:opacity-60">
                <Send size={16} /> {submitting ? "Проверяем…" : "Проверить ответ"}
              </button>
            </div>

            {result && (
              <div className={`mt-7 rounded-2xl border p-5 ${result.status === "correct" ? "border-lime/25 bg-lime/[0.07]" : result.status === "pending_review" ? "border-amber-300/20 bg-amber-300/[0.06]" : "border-red-300/20 bg-red-300/[0.06]"}`}>
                <p className="font-extrabold">{result.message}</p>
                {result.score !== null && result.max_score !== null && <p className="mt-2 text-sm text-muted">Баллы: {result.score} из {result.max_score}</p>}
                {result.hint && <p className="mt-3 text-sm leading-6 text-muted">Подсказка: {result.hint}</p>}
                {result.explanation && <p className="mt-3 text-sm leading-6 text-muted">Решение: {result.explanation}</p>}
                {result.status === "pending_review" && <p className="mt-2 text-sm text-muted">Ответ ожидает ручной проверки.</p>}
                <button onClick={() => { setAnswer(""); setSelected([]); setResult(null); }} className="mt-4 text-sm font-bold text-lime hover:text-[#d5ff86]">Попробовать ещё раз</button>
              </div>
            )}
          </section>
        ) : null}
      </div>
    </main>
  );
}
