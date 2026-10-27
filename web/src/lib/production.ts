// Suivi de production : types, file locale hors ligne et petits utilitaires.
import { api, ApiError, post } from "./api";

export type Reason = "panne" | "manque_fourniture" | "absence" | "changement_modele" | "autre";
export const REASONS: { code: Reason; label: string; icon: string }[] = [
  { code: "panne", label: "Panne machine", icon: "🔧" },
  { code: "manque_fourniture", label: "Manque fourniture", icon: "📦" },
  { code: "absence", label: "Absence", icon: "👤" },
  { code: "changement_modele", label: "Changement de modèle", icon: "🔄" },
  { code: "autre", label: "Autre", icon: "•" },
];
export const REASON_LABEL: Record<string, string> = Object.fromEntries(REASONS.map((r) => [r.code, r.label]));

export interface PlanStation {
  station: number; operations: { id: string; name: string; minutes: number; shared?: boolean }[];
  workers: string[]; worker_ids: string[]; operators: number; minutes: number; load_pct: number | null;
  machine_types?: string[];
}
export interface Plan {
  stations: PlanStation[]; cycle_time: number | null; takt_time: number | null; sam_total: number;
  operators: number; bottleneck_station: number | null; problem_name?: string;
}
export interface ProdSession {
  id: string; org_id: string; line_id: string | null; run_id: string | null; problem_id: string | null;
  line_name: string; model: string; session_date: string; timezone: string; shift_start: string; shift_hours: number;
  target_per_hour: number; cycle_time: number | null; takt_time: number | null; status: "open" | "closed";
  closed_at: string | null; created_at: string; plan?: Plan;
}
export interface Entry {
  id?: string; client_id: string; station: number; slot_hour: number; worker_id?: string | null;
  pieces: number; defects: number; rework: number; downtime_reason?: Reason | null; downtime_start?: string | null;
  downtime_minutes?: number | null; comment?: string; voided?: boolean; entered_at: string;
}
export interface StationRow {
  station: number; operations: string[]; workers: string[]; operators: number; planned_minutes: number;
  planned_per_operator: number; pieces: number; expected: number | null; pct_target: number | null;
  defects: number; rework: number; downtime_minutes: number; produced_minutes: number; presence_minutes: number;
  efficiency: number | null; real_minutes_per_piece: number | null;
  by_hour: { hour: number; pieces: number; target: number }[];
  ongoing_stop: Stop | null;
}
export interface Stop { station: number; reason: Reason; label: string; minutes: number; ongoing: boolean; start: string; slot_hour: number; comment: string; id: string; client_id: string }
export interface Dashboard {
  status: string; now: string; shift_start: string; shift_end: string; elapsed_minutes: number; shift_minutes: number;
  current_hour: number; target_per_hour: number; target_shift: number; expected_to_date: number; output: number;
  pct_target: number | null; efficiency: number | null; bottleneck_planned: number | null; bottleneck_observed: number | null;
  wip: { between: [number, number]; pieces: number }[]; wip_total: number; defects: number; rework: number;
  defect_rate: number | null; downtime_by_reason: { reason: Reason; label: string; minutes: number }[]; downtime_total: number;
  hourly: { hour: number; target: number; output: number; downtime_minutes: number }[];
  stations: StationRow[]; stops: Stop[]; alerts: { level: "danger" | "warning"; kind: string; station: number; message: string }[];
  cycle_time: number | null; takt_time: number | null;
}

export const sessionsPath = (org: string) => `/v1/orgs/${org}/production/sessions`;

export function uuid(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}

function part(tz: string, d: Date, type: "hour" | "minute"): number | null {
  try {
    const p = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: tz })
      .formatToParts(d).find((x) => x.type === type);
    const n = p ? parseInt(p.value, 10) : NaN;
    return Number.isFinite(n) ? n : null;
  } catch { return null; }
}
/** Heure locale de l'atelier (fuseau de la session), 0–23. */
export function localHour(tz: string, d = new Date()): number {
  return (part(tz, d, "hour") ?? d.getHours()) % 24;
}
export function localMinute(tz: string, d = new Date()): number {
  return part(tz, d, "minute") ?? d.getMinutes();
}
export function clock(tz: string, d = new Date()): string {
  try { return new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit", timeZone: tz }).format(d); } catch { return d.toLocaleTimeString(); }
}
export const minutesSince = (iso: string | null | undefined, now = Date.now()) => (iso ? Math.max(0, (now - new Date(iso).getTime()) / 60000) : 0);

// ---------------------------------------------------------------- file hors ligne
// Chaque saisie a un client_id : on garde dans localStorage le dernier état de chaque saisie
// non encore confirmée par le serveur ; l'envoi est idempotent (renvoyer = mettre à jour).
export class OfflineQueue {
  private key: string;
  constructor(sessionId: string) { this.key = `tlb.prod.queue.${sessionId}`; }
  all(): Record<string, Entry> {
    try { return JSON.parse(localStorage.getItem(this.key) || "{}"); } catch { return {}; }
  }
  private save(m: Record<string, Entry>) { localStorage.setItem(this.key, JSON.stringify(m)); }
  put(e: Entry) { const m = this.all(); m[e.client_id] = e; this.save(m); }
  size() { return Object.keys(this.all()).length; }
  /** Retire les saisies envoyées si elles n'ont pas changé entre-temps. */
  ack(sent: Entry[]) {
    const m = this.all();
    for (const e of sent) if (m[e.client_id] && JSON.stringify(m[e.client_id]) === JSON.stringify(e)) delete m[e.client_id];
    this.save(m);
  }
  drop(ids: string[]) { const m = this.all(); ids.forEach((i) => delete m[i]); this.save(m); }
}

export type SyncResult = { ok: true; saved: Entry[] } | { ok: false; offline: boolean; message: string; fatal: boolean };

export async function pushEntries(org: string, sessionId: string, entries: Entry[]): Promise<SyncResult> {
  try {
    const r = await post<{ saved: number; entries: Entry[] }>(`${sessionsPath(org)}/${sessionId}/entries`, {
      entries: entries.map(({ id: _id, ...e }) => e),
    });
    return { ok: true, saved: r.entries };
  } catch (e) {
    const err = e as ApiError;
    const offline = !navigator.onLine || err.status === 0 || err.status >= 500;
    return { ok: false, offline, message: err.message, fatal: err.status === 422 || err.status === 409 };
  }
}

export const fetchEntries = (org: string, sessionId: string) => api<Entry[]>(`${sessionsPath(org)}/${sessionId}/entries`);
