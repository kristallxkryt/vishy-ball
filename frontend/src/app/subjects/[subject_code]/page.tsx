"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import {
  ArrowLeft, ArrowRight, BookOpen, CheckCircle2, ChevronRight,
  Filter, GraduationCap, Search, Target,
} from "lucide-react";
import { apiRequest } from "@/lib/api";

type Topic = {
  topic_id: number | null;
  topic: string;
  description: string | null;
  task_count: number;
};

type TopicsResponse = {
  subject_code: string;
  subject_name: string;
  total_topics: number;
  total_tasks: number;
  topics: Topic[];
};

type Task = {
  id: number;
  subject_code: string;
  topic: string;
  question: string;
  difficulty: string | null;
  task_type: string;
  options: unknown[];
  media: Array<{ url?: string; alt?: string; type?: string }>;
};

const difficultyLabels: Record<string, string> = {
  easy: "Базовый",
  medium: "Средний",
  hard: "Сложный",
};

export default function SubjectPage() {
  const params = useParams<{ subject_code: string }>();
  const router = useRouter();
  const subjectCode = decodeURIComponent(params.subject_code);

  const [catalog, setCatalog] = useState<TopicsResponse | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [selectedTopic, setSelectedTopic] = useState<string | null>(null);
  const [difficulty, setDifficulty] = useState("");
  const [search, setSearch] = useState("");
  const [loadingTopics, setLoadingTopics] = useState(true);
  const [loadingTasks, setLoadingTasks] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const token = localStorage.getItem("vb_access_token");
    if (!token) {
      router.replace("/auth");
      return;
    }

    apiRequest<TopicsResponse>(
      `/api/tasks/topics?subject_code=${encodeURIComponent(subjectCode)}`,
    )
      .then(setCatalog)
      .catch((cause) => {
        setError(cause instanceof Error ? cause.message : "Не удалось загрузить темы.");
      })
      .finally(() => setLoadingTopics(false));
  }, [router, subjectCode]);

  useEffect(() => {
    if (!selectedTopic) {
      setTasks([]);
      return;
    }

    const query = new URLSearchParams({
      subject_code: subjectCode,
      topic: selectedTopic,
      limit: "50",
      offset: "0",
    });
    if (difficulty) query.set("difficulty", difficulty);

    setLoadingTasks(true);
    setError("");
    apiRequest<Task[]>(`/api/tasks/?${query.toString()}`)
      .then(setTasks)
      .catch((cause) => {
        setError(cause instanceof Error ? cause.message : "Не удалось загрузить задания.");
      })
      .finally(() => setLoadingTasks(false));
  }, [subjectCode, selectedTopic, difficulty]);

  const visibleTasks = useMemo(() => {
    const normalized = search.trim().toLocaleLowerCase("ru");
    if (!normalized) return tasks;
    return tasks.filter((task) =>
      task.question.toLocaleLowerCase("ru").includes(normalized),
    );
  }, [tasks, search]);

  return (
    <main className="min-h-screen bg-ink text-white">
      <header className="border-b border-white/[0.07] bg-[#0e1411]">
        <div className="mx-auto flex h-[76px] max-w-[1180px] items-center justify-between px-5 sm:px-8">
          <Link href="/dashboard" className="flex items-center gap-3">
            <span className="grid h-10 w-10 place-items-center rounded-xl bg-lime text-ink">
              <GraduationCap size={22} />
            </span>
            <span className="text-sm font-black tracking-wide">ВЫСШИЙ<span className="text-lime">БАЛЛ</span></span>
          </Link>
          <Link href="/dashboard" className="inline-flex items-center gap-2 text-sm font-semibold text-muted transition hover:text-white">
            <ArrowLeft size={16} /> В кабинет
          </Link>
        </div>
      </header>

      <div className="mx-auto max-w-[1180px] px-5 py-8 sm:px-8 sm:py-12">
        <div className="mb-8">
          <p className="eyebrow">КАТАЛОГ ЕГЭ / ПРЕДМЕТ</p>
          <h1 className="mt-3 text-3xl font-black tracking-tight sm:text-4xl">
            {catalog?.subject_name || "Загрузка предмета…"}
          </h1>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-muted">
            Выбери тему, чтобы открыть задания. Можно тренироваться по отдельным разделам и постепенно закрывать пробелы.
          </p>
        </div>

        {error && (
          <div role="alert" className="mb-6 rounded-2xl border border-red-400/20 bg-red-400/10 p-4 text-sm text-red-200">
            {error}
          </div>
        )}

        {loadingTopics ? (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {[1, 2, 3, 4, 5, 6].map((item) => (
              <div key={item} className="h-36 animate-pulse rounded-2xl border border-white/[0.07] bg-panel" />
            ))}
          </div>
        ) : (
          <>
            <section className="mb-10 grid gap-3 sm:grid-cols-3">
              <article className="rounded-2xl border border-white/[0.07] bg-panel p-5">
                <BookOpen className="text-lime" size={19} />
                <p className="mt-4 text-2xl font-black">{catalog?.total_topics ?? 0}</p>
                <p className="mt-1 text-xs text-muted">Тем в каталоге</p>
              </article>
              <article className="rounded-2xl border border-white/[0.07] bg-panel p-5">
                <Target className="text-lime" size={19} />
                <p className="mt-4 text-2xl font-black">{catalog?.total_tasks ?? 0}</p>
                <p className="mt-1 text-xs text-muted">Заданий доступно</p>
              </article>
              <article className="rounded-2xl border border-white/[0.07] bg-panel p-5">
                <CheckCircle2 className="text-lime" size={19} />
                <p className="mt-4 text-2xl font-black">ЕГЭ</p>
                <p className="mt-1 text-xs text-muted">Практика по темам</p>
              </article>
            </section>

            <section>
              <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
                <div>
                  <p className="eyebrow">СТРУКТУРА ПРЕДМЕТА</p>
                  <h2 className="mt-2 text-2xl font-black">Выбери тему</h2>
                </div>
                {selectedTopic && (
                  <button
                    onClick={() => { setSelectedTopic(null); setSearch(""); setDifficulty(""); }}
                    className="text-sm font-semibold text-lime hover:text-[#d5ff86]"
                  >
                    Все темы
                  </button>
                )}
              </div>

              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {catalog?.topics.map((topic, index) => {
                  const active = selectedTopic === topic.topic;
                  return (
                    <button
                      key={topic.topic_id ?? topic.topic}
                      onClick={() => { setSelectedTopic(topic.topic); setSearch(""); }}
                      className={`group rounded-2xl border p-5 text-left transition hover:-translate-y-0.5 hover:border-lime/30 ${active ? "border-lime/50 bg-lime/[0.08]" : "border-white/[0.07] bg-panel hover:bg-[#16201b]"}`}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <span className="grid h-10 w-10 place-items-center rounded-xl bg-lime/10 text-xs font-black text-lime">
                          {String(index + 1).padStart(2, "0")}
                        </span>
                        <ChevronRight size={18} className={active ? "text-lime" : "text-muted transition group-hover:translate-x-1 group-hover:text-lime"} />
                      </div>
                      <h3 className="mt-5 font-extrabold">{topic.topic}</h3>
                      {topic.description && <p className="mt-2 line-clamp-2 text-xs leading-5 text-muted">{topic.description}</p>}
                      <p className="mt-3 text-xs font-semibold text-lime">{topic.task_count} заданий</p>
                    </button>
                  );
                })}
              </div>

              {catalog?.topics.length === 0 && (
                <div className="rounded-2xl border border-white/[0.07] bg-panel p-8 text-center">
                  <BookOpen className="mx-auto text-muted" size={28} />
                  <p className="mt-4 font-bold">Темы пока не добавлены</p>
                  <p className="mt-2 text-sm text-muted">Когда в каталоге появятся задания, здесь отобразятся доступные разделы.</p>
                </div>
              )}
            </section>
          </>
        )}

        {selectedTopic && (
          <section className="mt-12 border-t border-white/[0.07] pt-9">
            <div className="flex flex-wrap items-end justify-between gap-4">
              <div>
                <p className="eyebrow">ПРАКТИКА ПО ТЕМЕ</p>
                <h2 className="mt-2 text-2xl font-black">{selectedTopic}</h2>
                <p className="mt-2 text-sm text-muted">Выбери задание и переходи к решению.</p>
              </div>
              <span className="rounded-full border border-white/10 px-3 py-1.5 text-xs text-muted">
                {visibleTasks.length} заданий
              </span>
            </div>

            <div className="mt-5 flex flex-col gap-3 sm:flex-row">
              <label className="relative flex-1">
                <Search className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" size={17} />
                <input
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="Найти в условии…"
                  className="w-full rounded-xl border border-white/10 bg-panel py-3 pl-10 pr-4 text-sm outline-none transition placeholder:text-muted focus:border-lime/50"
                />
              </label>
              <label className="flex items-center gap-2 rounded-xl border border-white/10 bg-panel px-3">
                <Filter size={16} className="text-muted" />
                <select
                  value={difficulty}
                  onChange={(event) => setDifficulty(event.target.value)}
                  className="bg-transparent py-3 text-sm outline-none"
                  aria-label="Сложность заданий"
                >
                  <option value="" className="bg-[#111914]">Любая сложность</option>
                  <option value="easy" className="bg-[#111914]">Базовый</option>
                  <option value="medium" className="bg-[#111914]">Средний</option>
                  <option value="hard" className="bg-[#111914]">Сложный</option>
                </select>
              </label>
            </div>

            {loadingTasks ? (
              <div className="mt-5 grid gap-3">{[1, 2, 3].map((item) => <div key={item} className="h-28 animate-pulse rounded-2xl bg-panel" />)}</div>
            ) : (
              <div className="mt-5 grid gap-3">
                {visibleTasks.map((task, index) => (
                  <article key={task.id} className="rounded-2xl border border-white/[0.07] bg-panel p-5 transition hover:border-lime/25 sm:p-6">
                    <div className="flex flex-wrap items-center gap-2 text-[11px] font-bold">
                      <span className="rounded-full bg-lime/10 px-2.5 py-1 text-lime">Задание {index + 1}</span>
                      <span className="rounded-full bg-white/[0.06] px-2.5 py-1 text-muted">{difficultyLabels[task.difficulty || ""] || "Без уровня"}</span>
                    </div>
                    <p className="mt-4 line-clamp-3 whitespace-pre-wrap text-sm leading-6 text-white/90">{task.question}</p>
                    <div className="mt-5 flex justify-end">
                      <Link
                        href={`/practice/${task.id}?subject=${encodeURIComponent(subjectCode)}`}
                        className="inline-flex items-center gap-2 rounded-xl bg-lime px-4 py-2.5 text-xs font-black text-ink transition hover:bg-[#d5ff86]"
                      >
                        Решить задание <ArrowRight size={15} />
                      </Link>
                    </div>
                  </article>
                ))}
                {!visibleTasks.length && (
                  <div className="rounded-2xl border border-white/[0.07] bg-panel p-7 text-center text-sm text-muted">
                    {tasks.length ? "По этому запросу ничего не найдено." : "В этой теме пока нет активных заданий."}
                  </div>
                )}
              </div>
            )}
          </section>
        )}
      </div>
    </main>
  );
}
