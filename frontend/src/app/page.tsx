"use client";

import Link from "next/link";
import {
  ArrowDownRight,
  ArrowRight,
  BookOpen,
  Brain,
  ChartNoAxesCombined,
  Check,
  GraduationCap,
  Sparkles,
  Target,
  UserRound,
} from "lucide-react";
import { useEffect, useState } from "react";

const features = [
  {
    icon: BookOpen,
    number: "01",
    title: "Тренируйся на заданиях ЕГЭ",
    description:
      "Предметы, темы и задания собраны в одном месте. Выбирай направление и занимайся в своём темпе.",
  },
  {
    icon: ChartNoAxesCombined,
    number: "02",
    title: "Видь свой прогресс",
    description:
      "Статистика показывает точность ответов, набранные баллы и темы, которым стоит уделить внимание.",
  },
  {
    icon: Brain,
    number: "03",
    title: "Учись осознанно",
    description:
      "Разбирай ошибки, возвращайся к сложным темам и превращай подготовку в понятную систему.",
  },
];

const subjects = [
  ["РУ", "Русский язык", "russian"],
  ["МП", "Математика · профиль", "math-profile"],
  ["ИН", "Информатика", "informatics"],
  ["ФИ", "Физика", "physics"],
  ["ХИ", "Химия", "chemistry"],
  ["ОБ", "Обществознание", "social-studies"],
];

export default function HomePage() {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [authChecked, setAuthChecked] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem("vb_access_token");
    if (!token) {
      setAuthChecked(true);
      return;
    }
    fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000"}/api/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    }).then((response) => {
      if (response.ok) setIsAuthenticated(true);
      else {
        localStorage.removeItem("vb_access_token");
        localStorage.removeItem("vb_user");
      }
    }).catch(() => setIsAuthenticated(false)).finally(() => setAuthChecked(true));
  }, []);

  return (
    <main className="overflow-hidden">
      <div className="pointer-events-none fixed inset-0 -z-10">
        <div className="grid-glow absolute inset-0" />
        <div className="absolute -right-40 top-20 h-[520px] w-[520px] rounded-full bg-lime/10 blur-[140px]" />
        <div className="absolute -left-48 top-[520px] h-[420px] w-[420px] rounded-full bg-slate-500/10 blur-[130px]" />
      </div>

      <header className="shell flex h-20 items-center justify-between border-b border-white/[0.07]">
        <Link href="/" className="flex items-center gap-3">
          <span className="grid h-10 w-10 place-items-center rounded-xl bg-lime text-ink">
            <GraduationCap size={23} strokeWidth={2.4} />
          </span>
          <span className="text-[15px] font-black tracking-tight">
            ВЫСШИЙ<span className="text-lime">БАЛЛ</span>
          </span>
        </Link>
        <nav className="hidden items-center gap-8 text-sm text-muted md:flex">
          <a href="#features" className="transition hover:text-white">Возможности</a>
          <a href="#subjects" className="transition hover:text-white">Предметы</a>
          <a href="#about" className="transition hover:text-white">О платформе</a>
        </nav>
        <div className="flex items-center gap-3">
          {!authChecked ? null : isAuthenticated ? (
            <Link href="/dashboard" className="inline-flex items-center gap-2 rounded-xl bg-lime px-4 py-2.5 text-sm font-extrabold text-ink transition hover:bg-[#e1e5eb]">
              <UserRound size={16} /> Личный кабинет
            </Link>
          ) : (
            <>
              <Link href="/auth" className="hidden rounded-xl px-4 py-2.5 text-sm font-semibold text-white/80 transition hover:text-white sm:block">
                Войти
              </Link>
              <Link href="/auth?mode=register" className="rounded-xl bg-lime px-4 py-2.5 text-sm font-extrabold text-ink transition hover:bg-[#e1e5eb]">
                Начать бесплатно <ArrowRight className="ml-1 inline" size={15} />
              </Link>
            </>
          )}
        </div>
      </header>

      <section className="shell relative grid min-h-[680px] items-center gap-14 py-20 lg:grid-cols-[1.05fr_.95fr] lg:py-28">
        <div className="relative z-10">
          <div className="mb-7 inline-flex items-center gap-2 rounded-full border border-lime/20 bg-lime/[0.07] px-3 py-2 text-xs font-semibold text-lime">
            <Sparkles size={14} /> Твоя подготовка начинается здесь
          </div>
          <h1 className="max-w-[700px] text-5xl font-black leading-[1.04] tracking-[-.055em] sm:text-6xl lg:text-[76px]">
            Не просто готовься.
            <span className="gradient-text block">Бери свой балл.</span>
          </h1>
          <p className="mt-7 max-w-[510px] text-base leading-8 text-muted sm:text-lg">
            Понятная система подготовки к ЕГЭ: практикуйся, разбирай ошибки и следи за тем, как растёт твой результат.
          </p>
          <div className="mt-10 flex flex-wrap items-center gap-4">
            <Link href="/auth?mode=register" className="group inline-flex items-center gap-3 rounded-2xl bg-lime px-6 py-4 text-sm font-black text-ink shadow-glow transition hover:-translate-y-0.5 hover:bg-[#e1e5eb]">
              Создать аккаунт <ArrowRight size={17} className="transition group-hover:translate-x-1" />
            </Link>
            <a href="#features" className="inline-flex items-center gap-2 rounded-2xl border border-white/10 px-6 py-4 text-sm font-bold text-white/75 transition hover:border-white/25 hover:text-white">
              Изучить платформу <ArrowDownRight size={16} />
            </a>
          </div>
          <div className="mt-12 flex flex-wrap gap-x-7 gap-y-3 text-xs font-medium text-muted">
            {["Своя траектория", "Честная статистика", "Подготовка без хаоса"].map((item) => (
              <span key={item} className="inline-flex items-center gap-2"><Check size={14} className="text-lime" />{item}</span>
            ))}
          </div>
        </div>

        <div className="relative mx-auto w-full max-w-[500px]">
          <div className="absolute -inset-8 rounded-full bg-lime/[0.08] blur-3xl" />
          <div className="glass relative rounded-[30px] p-5 sm:p-7">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs font-semibold text-muted">ТВОЯ ПОДГОТОВКА</p>
                <p className="mt-1 text-lg font-extrabold">Всё под контролем</p>
              </div>
              <span className="rounded-xl border border-lime/20 bg-lime/10 p-3 text-lime"><Target size={21} /></span>
            </div>
            <div className="mt-7 rounded-2xl border border-white/[0.07] bg-black/20 p-5">
              <div className="flex items-end justify-between">
                <div>
                  <p className="text-sm text-muted">Средняя точность</p>
                  <p className="mt-2 text-5xl font-black tracking-tight">84<span className="text-2xl text-lime">%</span></p>
                </div>
                <span className="rounded-full bg-lime/10 px-3 py-1.5 text-xs font-bold text-lime">+12% за месяц</span>
              </div>
              <div className="mt-6 flex h-24 items-end gap-2">
                {[32, 43, 39, 57, 51, 68, 61, 78, 72, 88, 80, 96].map((height, index) => (
                  <div key={index} className="flex-1 rounded-t-md bg-lime/20" style={{ height: `${height}%` }}>
                    <div className="h-full rounded-t-md bg-gradient-to-t from-lime/30 to-lime/90 opacity-80" />
                  </div>
                ))}
              </div>
              <div className="mt-3 flex justify-between text-[10px] font-semibold uppercase tracking-wider text-muted">
                <span>Неделя 1</span><span>Неделя 4</span>
              </div>
            </div>
            <div className="mt-4 grid grid-cols-2 gap-3">
              <div className="rounded-2xl border border-white/[0.07] bg-white/[0.025] p-4">
                <p className="text-xs text-muted">Решено заданий</p>
                <p className="mt-2 text-2xl font-extrabold">248</p>
                <p className="mt-1 text-[11px] text-lime">Продолжай в том же духе</p>
              </div>
              <div className="rounded-2xl border border-white/[0.07] bg-white/[0.025] p-4">
                <p className="text-xs text-muted">Активных предметов</p>
                <p className="mt-2 text-2xl font-extrabold">4</p>
                <p className="mt-1 text-[11px] text-muted">Твой учебный фокус</p>
              </div>
            </div>
            <p className="mt-4 text-center text-[10px] text-muted">Иллюстрация интерфейса · пример данных</p>
          </div>
          <div className="absolute -bottom-7 -left-8 hidden rounded-2xl border border-white/10 bg-[#171e27] px-4 py-3 shadow-xl sm:block">
            <div className="flex items-center gap-3"><span className="grid h-9 w-9 place-items-center rounded-xl bg-lime/10 text-lime"><ChartNoAxesCombined size={18} /></span><div><p className="text-xs font-bold">Прогресс растёт</p><p className="text-[10px] text-muted">Шаг за шагом</p></div></div>
          </div>
        </div>
      </section>

      <section id="features" className="shell py-24">
        <div className="max-w-xl">
          <p className="eyebrow">Меньше хаоса — больше результата</p>
          <h2 className="mt-4 text-3xl font-black tracking-tight sm:text-4xl">Подготовка, которая работает на тебя</h2>
          <p className="mt-4 leading-7 text-muted">Не нужно держать всё в голове. Платформа помогает сосредоточиться на следующем шаге.</p>
        </div>
        <div className="mt-12 grid gap-4 md:grid-cols-3">
          {features.map(({ icon: Icon, number, title, description }) => (
            <article key={number} className="glass rounded-3xl p-7 transition hover:-translate-y-1 hover:border-lime/25">
              <div className="flex items-center justify-between"><span className="grid h-12 w-12 place-items-center rounded-2xl bg-lime/10 text-lime"><Icon size={22} /></span><span className="text-xs font-bold tracking-widest text-muted">{number}</span></div>
              <h3 className="mt-8 text-xl font-extrabold">{title}</h3>
              <p className="mt-3 text-sm leading-7 text-muted">{description}</p>
            </article>
          ))}
        </div>
      </section>

      <section id="subjects" className="border-y border-white/[0.06] bg-white/[0.015] py-24">
        <div className="shell">
          <div className="flex flex-wrap items-end justify-between gap-5">
            <div><p className="eyebrow">Выбирай направление</p><h2 className="mt-4 text-3xl font-black tracking-tight sm:text-4xl">Твой предмет — твой маршрут</h2></div>
            <Link href="/auth?mode=register" className="text-sm font-bold text-lime transition hover:text-white">Начать подготовку <ArrowRight className="ml-1 inline" size={15} /></Link>
          </div>
          <div className="mt-10 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            {subjects.map(([code, name]) => (
              <div key={code} className="rounded-2xl border border-white/[0.07] bg-panel p-4 transition hover:border-lime/30 hover:bg-surface-soft">
                <span className="grid h-10 w-10 place-items-center rounded-xl bg-white/[0.05] text-xs font-black text-lime">{code}</span>
                <p className="mt-5 min-h-10 text-sm font-bold leading-5">{name}</p>
              </div>
            ))}
          </div>
          <p className="mt-5 text-xs text-muted">Список предметов на главной — демонстрация. Полный каталог загружается из API после входа.</p>
        </div>
      </section>

      <section id="about" className="shell py-24">
        <div className="glass relative overflow-hidden rounded-[32px] p-8 sm:p-12">
          <div className="absolute -right-24 -top-24 h-72 w-72 rounded-full bg-lime/10 blur-3xl" />
          <div className="relative max-w-2xl">
            <p className="eyebrow">Твой следующий шаг</p>
            <h2 className="mt-4 text-3xl font-black tracking-tight sm:text-5xl">Большой результат начинается с одного задания.</h2>
            <p className="mt-5 max-w-xl leading-7 text-muted">Создай аккаунт, выбери предмет и начни двигаться к своей цели — спокойно и последовательно.</p>
            <Link href="/auth?mode=register" className="mt-8 inline-flex items-center gap-3 rounded-2xl bg-lime px-6 py-4 text-sm font-black text-ink transition hover:bg-[#e1e5eb]">Начать бесплатно <ArrowRight size={17} /></Link>
          </div>
        </div>
      </section>

      <footer className="shell flex flex-col gap-3 border-t border-white/[0.07] py-8 text-xs text-muted sm:flex-row sm:items-center sm:justify-between">
        <span>© {new Date().getFullYear()} Высший балл</span>
        <span>Подготовка к ЕГЭ без лишнего шума.</span>
      </footer>
    </main>
  );
}
