export const API_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ||
  "http://127.0.0.1:8000";

export type ApiUser = {
  id: number;
  username: string;
  email: string | null;
  role: "student" | "teacher" | "admin";
};

export type LoginResponse = {
  access_token: string;
  token_type: string;
  expires_in_days: number;
  user: ApiUser;
};

export async function apiRequest<T>(
  path: string,
  options: RequestInit = {},
  token?: string,
): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers,
    cache: "no-store",
  });

  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const detail =
      payload && typeof payload.detail === "string"
        ? payload.detail
        : "Не удалось выполнить запрос. Попробуйте ещё раз.";
    throw new Error(detail);
  }
  return payload as T;
}
