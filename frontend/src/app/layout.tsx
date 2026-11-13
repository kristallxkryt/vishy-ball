import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Высший балл — подготовка к ЕГЭ",
  description:
    "Тренируйся системно, отслеживай прогресс и приближайся к своему высшему баллу.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ru">
      <body>{children}</body>
    </html>
  );
}
