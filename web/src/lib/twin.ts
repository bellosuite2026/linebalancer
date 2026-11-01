// Jumeau numérique : types de l'API, implantations par défaut et lecture de la trace d'animation.
import type { ProdSession } from "./production";
import type { PlanSummary } from "./workshop";

export type LayoutKind = "line" | "u" | "free";
export interface Pt { x: number; y: number }
export interface Layout {
  kind: LayoutKind; positions: Record<string, Pt>;
  plan_id?: string | null; assignment?: Record<string, string[]>; distances?: Record<string, number>;
}
/** Stations d'un calcul placées sur les machines d'un plan d'atelier (réponse de l'API). */
export interface Placement {
  plan_id: string; plan_name: string; layout: Layout; assignment: Record<string, string[]>;
  missing: { station: number; type: string }[]; unused: string[]; notes: string[]; virtual: number[];
  routes: Record<string, number[][]>;
  flow: { transfers: { from: number; to: number; meters: number; straight: number }[]; meters_per_bundle: number;
          backtracks: { from: number; to: number; meters: number }[]; u_cell: boolean; entry_exit_m: number; extent_m: number;
          warnings: LeanWarning[] };
  travel: { neighbour_m: number | null; minutes: number };
}

export interface TwinStation {
  station: number; minutes: number; operators: number; worker_ids: string[]; workers: string[];
  operations: { id: string; name: string; minutes: number; skills: string[]; machine_type: string }[];
  machine_types?: string[]; load_pct?: number | null;
}
export interface TwinPlan {
  stations: TwinStation[]; workers: Record<string, { name: string; skills: string[]; efficiency: number }>;
  cycle_time: number | null; takt_time: number | null; bottleneck_station: number | null; problem_name?: string;
}
export interface OtherRun { id: string; created_at: string; stations_used: number; actual_cycle_time: number | null; solver: string }
export interface SimSummary { id: string; name: string; status: "queued" | "running" | "done" | "failed"; created_at: string; error: string; scenarios: Scenario[] }
export interface Twin {
  run: { id: string; created_at: string; solver: string; actual_cycle_time: number | null; stations_used: number | null; problem_id?: string | null };
  plan: TwinPlan; problem_name: string; layout: Layout; layout_saved: boolean;
  placement: Placement | null; workshop_plans: PlanSummary[];
  sessions: ProdSession[]; simulations: SimSummary[]; other_runs: OtherRun[];
}

export interface Breakdown { station: number; start_min: number; duration_min: number }
export interface Scenario {
  name: string; run_id?: string | null; absent: string[]; reassign: boolean; operators: Record<string, number>;
  breakdowns: Breakdown[]; bundle_size: number; efficiency_pct: number; variability_pct: number; shift_minutes: number; seed?: number;
}
export const newScenario = (name: string, over: Partial<Scenario> = {}): Scenario => ({
  name, run_id: null, absent: [], reassign: true, operators: {}, breakdowns: [], bundle_size: 10,
  efficiency_pct: 100, variability_pct: 10, shift_minutes: 480, ...over,
});

export interface SimStation {
  station: number; operators: number; workers: string[]; pieces: number; utilization_pct: number; worker_util_max: number;
  avg_wait_min: number; max_wip: number; avg_wip: number; down_min: number; minutes_per_piece: number; load_per_operator: number | null;
}
export interface LeanWarning { kind: string; message: string; stations?: number[]; worker?: string }
export interface SimResult {
  success: boolean; pieces: number; per_hour: number; shift_minutes: number; bottleneck: number | null; blocked_stations: number[];
  wip_max: number; wip_avg: number; lead_time_min: number | null; avg_wait_min: number; transport_m: number; walk_m: number;
  hourly: number[]; stations: SimStation[];
  workers: { id: string; name: string; stations: number[]; utilization_pct: number; walk_m: number }[];
  snapshots: [number, number[], number][];
  trace: { events: (number | string)[][]; bundles: Record<string, number>; truncated: boolean };
  notes: string[]; lean: { kind: string; transfers: { from: number; to: number; meters: number }[]; meters_per_bundle: number; line_length_m: number; warnings: LeanWarning[] };
  plan: { stations: { station: number; worker_ids: string[]; workers: string[]; operators: number; minutes: number }[]; unqualified: Record<string, number[]> };
  utilization_avg?: number; operators?: number;
  config?: { bundle_size: number; efficiency: number; variability: number };
}
export interface Simulation extends SimSummary {
  run_id: string; layout: Layout | null;
  results: { scenarios: { name: string; params: Scenario; run_id: string; result: SimResult }[];
             comparison: { key: string; label: string; values: (number | null)[] }[] } | null;
}
export interface Sync {
  elapsed_minutes: number; shift_minutes: number; real_efficiency: number | null; efficiency_used_pct: number;
  output: number; target_shift: number; planned_day: number; calibrated_day: number; forecast_end_of_day: number;
  forecast_linear: number | null; bottleneck_planned: number | null; bottleneck_observed: number | null;
  hourly: { hour: number; target: number; real: number; simulated: number | null; simulated_calibrated: number | null }[];
  stations: { station: number; real: number; simulated_to_date: number; simulated_day: number; real_efficiency: number | null; downtime_minutes: number }[];
  notes: string[];
  order?: { quantity: number; done_before: number; left_after_today: number; pieces_per_day: number; extra_days: number; finish_date: string };
}

export const SPACING = 1.6, AISLE = 1.4;

/** Même règle que engine.simulation.default_layout. */
export function defaultLayout(ids: number[], kind: LayoutKind): Layout {
  const pos: Record<string, Pt> = {};
  if (kind === "u" && ids.length > 2) {
    const half = Math.ceil(ids.length / 2);
    ids.forEach((sid, i) => {
      if (i < half) pos[sid] = { x: +(i * SPACING).toFixed(2), y: 0 };
      else {
        const j = ids.length - 1 - i;
        pos[sid] = { x: +(j * SPACING + (ids.length % 2 ? SPACING / 2 : 0)).toFixed(2), y: AISLE };
      }
    });
    return { kind: "u", positions: pos };
  }
  ids.forEach((sid, i) => { pos[sid] = { x: +(i * SPACING).toFixed(2), y: 0 }; });
  return { kind: "line", positions: pos };
}

// --------------------------------------------------------------- trace -> positions
export interface Seg { st: number; a: number; s: number; e: number; w: string }
export interface BundleTrack { id: number; size: number; segs: Seg[] }
export interface WorkerVisit { station: number; start: number; end: number }
export interface WorkerTrack { id: string; visits: WorkerVisit[] }

export type WorkerState =
  | { kind: "idle" | "work"; station: number }
  | { kind: "walk"; from: number; to: number; f: number };

export function buildTracks(res: SimResult): BundleTrack[] {
  const map = new Map<number, BundleTrack>();
  for (const ev of res.trace.events) {
    const [t, bid, st, code, w] = ev as [number, number, number, number, string?];
    let b = map.get(bid);
    if (!b) { b = { id: bid, size: res.trace.bundles[String(bid)] ?? 1, segs: [] }; map.set(bid, b); }
    if (code === 0) b.segs.push({ st, a: t, s: Infinity, e: Infinity, w: "" });
    else {
      const seg = b.segs[b.segs.length - 1];
      if (!seg) continue;
      if (code === 1) { seg.s = t; seg.w = String(w ?? ""); } else seg.e = t;
    }
  }
  return [...map.values()];
}

export type BundleState =
  | { kind: "queue"; st: number }
  | { kind: "work"; st: number; w: string }
  | { kind: "move"; from: number; to: number; f: number };

export function bundleAt(b: BundleTrack, t: number): BundleState | null {
  const s = b.segs;
  if (!s.length || t < s[0].a) return null;
  for (let i = 0; i < s.length; i++) {
    const g = s[i];
    if (t < g.s) return { kind: "queue", st: g.st };
    if (t < g.e) return { kind: "work", st: g.st, w: g.w };
    const nx = s[i + 1];
    if (nx && t < nx.a) return { kind: "move", from: g.st, to: nx.st, f: (t - g.e) / Math.max(0.01, nx.a - g.e) };
  }
  return null;
}

export function buildWorkerTracks(res: SimResult): WorkerTrack[] {
  const tracks = new Map<string, WorkerTrack>();
  for (const bundle of buildTracks(res)) for (const segment of bundle.segs) {
    if (!segment.w || !Number.isFinite(segment.s) || !Number.isFinite(segment.e)) continue;
    let track = tracks.get(segment.w);
    if (!track) { track = { id: segment.w, visits: [] }; tracks.set(segment.w, track); }
    track.visits.push({ station: segment.st, start: segment.s, end: segment.e });
  }
  return [...tracks.values()].map((track) => ({
    ...track,
    visits: track.visits.sort((a, b) => a.start - b.start || a.end - b.end),
  }));
}

export function workerAt(track: WorkerTrack, t: number, walkMinutes = 0): WorkerState | null {
  const { visits } = track;
  if (!visits.length) return null;
  const active = visits.find((visit) => visit.start <= t && t < visit.end);
  if (active) return { kind: "work", station: active.station };

  const nextIndex = visits.findIndex((visit) => visit.start > t);
  if (nextIndex === 0) return { kind: "idle", station: visits[0].station };
  if (nextIndex < 0) return { kind: "idle", station: visits[visits.length - 1].station };

  const previous = visits[nextIndex - 1];
  const next = visits[nextIndex];
  if (previous.station === next.station) return { kind: "idle", station: previous.station };
  const gap = next.start - previous.end;
  if (gap <= 0) return { kind: "idle", station: next.station };
  const duration = Math.min(gap, Math.max(0, walkMinutes));
  const start = next.start - duration;
  if (duration <= 0 || t < start) return { kind: "idle", station: previous.station };
  return { kind: "walk", from: previous.station, to: next.station, f: Math.max(0, Math.min(1, (t - start) / duration)) };
}

export function finishedAt(res: SimResult, t: number): number {
  let best = 0;
  for (const sn of res.snapshots) { if (sn[0] <= t) best = sn[2]; else break; }
  return best;
}

export const clock = (startHHMM: string, min: number) => {
  const [h, m] = startHHMM.split(":").map(Number);
  const tot = Math.round((h || 0) * 60 + (m || 0) + min);
  return `${String(Math.floor(tot / 60) % 24).padStart(2, "0")}:${String(tot % 60).padStart(2, "0")}`;
};
