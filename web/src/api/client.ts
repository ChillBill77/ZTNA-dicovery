import type { Problem } from "./types";

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!resp.ok) {
    let problem: Problem;
    try { problem = await resp.json(); } catch { problem = { title: resp.statusText, status: resp.status }; }
    throw new Error(problem.detail ?? problem.title);
  }
  return (await resp.json()) as T;
}
