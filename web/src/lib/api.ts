import { supabase } from "./supabase";

const BASE = (import.meta.env.VITE_API_URL as string || "").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function token(): Promise<string> {
  const { data } = await supabase.auth.getSession();
  if (!data.session) throw new ApiError(401, "Session expirée, reconnectez-vous.");
  return data.session.access_token;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${await token()}`);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  let res: Response;
  try {
    res = await fetch(BASE + path, { ...init, headers });
  } catch {
    throw new ApiError(0, "Serveur injoignable. S'il était en veille, réessayez dans une minute.");
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  const body = text ? safeJson(text) : null;
  if (!res.ok) {
    const d = body?.detail;
    const msg = typeof d === "string" ? d : Array.isArray(d) ? d.map((e: { msg: string }) => e.msg).join(" ; ") : `Erreur ${res.status}`;
    throw new ApiError(res.status, msg);
  }
  return body as T;
}

function safeJson(t: string) { try { return JSON.parse(t); } catch { return { detail: t.slice(0, 200) }; } }

export const post = <T,>(path: string, body: unknown) => api<T>(path, { method: "POST", body: JSON.stringify(body) });

export async function download(path: string, filename: string) {
  const res = await fetch(BASE + path, { headers: { Authorization: `Bearer ${await token()}` } });
  if (!res.ok) throw new ApiError(res.status, "Export impossible.");
  const url = URL.createObjectURL(await res.blob());
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  a.click();
  URL.revokeObjectURL(url);
}

export const fmt = {
  n: (v: number | null | undefined, d = 2) => (v == null ? "—" : Number(v).toLocaleString("fr-FR", { maximumFractionDigits: d, minimumFractionDigits: 0 })),
  date: (s: string | null | undefined) => (s ? new Date(s).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" }) : "—"),
  day: (s: string | null | undefined) => (s ? new Date(s).toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" }) : "—"),
};

export const ROLE_LABEL: Record<string, string> = {
  owner: "Propriétaire", admin: "Administrateur", methodes: "Méthodes", chef_ligne: "Chef de ligne", lecteur: "Lecteur",
};
export const SOLVER_LABEL: Record<string, string> = { rpw: "RPW (rapide)", cp_sat: "CP-SAT (optimal)" };
