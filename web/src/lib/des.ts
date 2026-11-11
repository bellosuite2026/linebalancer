// Simulation à événements discrets (type FlexSim) : types du modèle / des résultats et lecture de la
// trace (positions des paquets, des opérateurs et des transporteurs à l'instant t, états des postes).
import type { WorkshopPlan } from "./workshop";

export type Dist = { kind: "constant" | "normal" | "triangular" | "lognormal"; cv?: number; low_pct?: number; high_pct?: number };
export interface DesStation {
  id: string; label: string; x: number; y: number; qx: number; qy: number; mx: number; my: number; rot?: number; machine?: string;
  minutes: number; servers: number; operators: string[]; machine_ids: string[]; machine_type: string; operations: string[];
  setup_min?: number; mtbf_min?: number; mttr_min?: number; defect_pct?: number; rework_to?: string | null; queue_capacity?: number;
  handling_min?: number; dist?: Dist; out_capacity?: number;
}
export interface DesOperator { id: string; name: string; efficiency: number; stations: string[] }
export interface DesTransporter { id: string; name: string; capacity: number; speed_m_per_min: number; load_min: number }
export interface Lot { style: string; size: string; qty: number }
export interface Break { start_min: number; minutes: number; label: string }
export interface DesSettings {
  walk_speed_m_per_min: number; efficiency: number; dist: Dist; setup_min: number; handling_min: number; mtbf_min: number;
  mttr_min: number; defect_pct: number; queue_capacity: number; out_capacity: number; transfer: "auto" | "operator" | "transporter" | "handoff";
  carry_threshold_m: number; seed: number; target_per_hour: number | null;
}
/** Convoyeur suspendu (UPS) : réglages + géométrie calculée par le moteur (pts, cum, spurs…). */
export interface DesConveyor {
  enabled: boolean; name?: string; speed_m_per_min?: number; switch_sec?: number; carriers?: number; carrier_capacity?: number;
  station_wip?: number; load_min?: number; unload_min?: number; pitch_m?: number; height_m?: number; corner_radius_m?: number;
  margin_m?: number; dynamic_routing?: boolean; loop?: [number, number][]; pts?: [number, number][]; cum?: number[]; length_m?: number;
  segments?: { kind: "line" | "arc"; s0: number; s1: number }[]; spurs?: Record<string, { s: number; pt: [number, number]; to: [number, number]; len: number }>;
  s_load?: number; s_unload?: number; load_pt?: [number, number]; unload_pt?: [number, number]; capacity?: number;
  alternates?: Record<string, string[]>; auto_loop?: boolean; plan_rail_id?: string;
}
export interface ConveyorRes {
  name: string; length_m: number; capacity: number; carriers: number; carrier_capacity: number; station_wip: number; speed_m_per_min: number;
  switch_sec: number; rail_max: number; circulation_max: number; rail_util_max_pct: number; trips: number; distance_m: number;
  stations: { id: string; assigned: number; recirculations: number }[]; carriers_ids: string[];
}
export interface DesModel {
  name: string; shift: { minutes: number; breaks: Break[] };
  source: { lots: Lot[]; bundle_size: number; interval_min: number; wip_cap_bundles?: number | null; start_wip_bundles: number; x: number; y: number };
  sink: { x: number; y: number }; stations: DesStation[]; route: string[]; operators: DesOperator[]; transporters: DesTransporter[];
  settings: Partial<DesSettings>; breakdowns?: { station: string; start_min: number; duration_min: number }[];
  paths?: Record<string, { m: number; pts: [number, number][] }>; plan_id?: string | null; conveyor?: DesConveyor;
}
export interface CI { mean: number | string | null; sd?: number | null; lo?: number | null; hi?: number | null; n?: number }
export interface StationRes {
  id: string; label: string; servers: number; operators: string[]; minutes: number; pieces: number; defects: number;
  states: Record<string, number>; utilization_pct: number; queue_avg: number; queue_max: number; queue_avg_pieces: number; down_min: number;
}
export interface OperatorRes { id: string; name: string; stations: string[]; states: Record<string, number>; utilization_pct: number; walk_m: number; carry_m: number; gantt: [number, number, number][] }
export interface TransporterRes { id: string; name: string; capacity: number; states: Record<string, number>; utilization_pct: number; distance_m: number; loads: number; gantt: [number, number, number][] }
export interface Trace {
  events: number[][]; paths: [number, number][][]; bundles: [number, number, number][]; truncated: boolean; until: number;
  actors: { id: string; kind: "operator" | "transporter"; name: string; start: [number, number] }[]; stations: string[]; lots: Lot[];
  carriers?: string[];
}
export interface ScenarioResult {
  seed: number; shift_minutes: number; breaks: Break[];
  kpis: { pieces: number; per_hour: number; per_hour_worked: number; lead_time_avg: number | null; lead_time_p90: number | null; wip_avg: number; wip_max: number;
    bottleneck: string; operators: number; operator_util_avg: number; walk_m: number; transport_m: number; defects: number; launched: number; target_per_hour: number | null;
    rail_util_pct?: number | null; carriers_in_circulation?: number | null; rail_time_avg?: number | null; station_time_avg?: number | null;
    rail_share_pct?: number | null; recirculations?: number | null; reassigned?: number | null };
  stations: StationRes[]; operators: OperatorRes[]; transporters: TransporterRes[];
  throughput: { hourly: number[]; cumulative: [number, number][]; target_per_hour: number | null };
  wip_series: [number, number][]; lead_time: { hist: { edges: number[]; counts: number[] }; count: number; sample: number[] };
  conservation: { ok: boolean; initial: number; launched: number; done: number; in_system: number }; notes: string[]; conveyor?: ConveyorRes | null;
  trace?: Trace; replications: { n: number; seeds: number[]; kpis: Record<string, CI> & { bottleneck: string | CI }; station_util: Record<string, CI> }; model: DesModel;
}
export interface DesScenario { name: string; overrides: Record<string, unknown>; absent: string[]; result: ScenarioResult }
export interface DesResults { engine: string; replications: number; scenarios: DesScenario[]; comparison: { key: string; label: string; values: CI[] }[] }
export interface DesSim {
  id: string; name: string; status: "queued" | "running" | "done" | "failed"; kind: string; error?: string; created_at: string;
  results?: DesResults | null; scenarios?: { name: string }[]; layout?: DesModel;
}
export interface DesModelResponse {
  model: DesModel; summary: { stations: number; operators: number; transporters: number; sam_total: number; length_m: number };
  workshop_plan: WorkshopPlan | null; workshop_plans: { id: string; name: string; version: string }[]; simulations: DesSim[];
  problem_name: string; run: { id: string; created_at: string; actual_cycle_time?: number; stations_used?: number };
}

// ------------------------------------------------------------------ libellés et couleurs
export const STATION_STATES = ["work", "starved", "blocked", "down", "setup", "wait_operator", "break", "transfer"] as const;
export const STATE_LABEL: Record<string, string> = {
  work: "Travail", starved: "Attente matière", blocked: "Bloqué aval", down: "Panne", setup: "Mise en route",
  wait_operator: "Attente opérateur", break: "Pause", transfer: "Transfert",
};
// vert travail, jaune attente, orange bloqué, rouge panne, bleu mise en route
export const STATE_COLOR: Record<string, string> = {
  work: "#2e9e5b", starved: "#e8c547", blocked: "#f08a24", down: "#d64541", setup: "#3b7dd8",
  wait_operator: "#9b59b6", break: "#95a5a6", transfer: "#16a085",
};
export const OP_STATES = ["idle", "walk", "work", "setup", "carry", "break", "wait"] as const;
export const OP_LABEL: Record<string, string> = { idle: "Inactif", walk: "Marche", work: "Travail", setup: "Mise en route", carry: "Porte un paquet", break: "Pause", wait: "Attente" };
export const OP_COLOR: Record<string, string> = { idle: "#d5d9dd", walk: "#e8c547", work: "#2e9e5b", setup: "#3b7dd8", carry: "#16a085", break: "#95a5a6", wait: "#f08a24" };
export const TR_STATES = ["idle", "empty", "loaded", "loading", "wait", "break"] as const;
export const TR_LABEL: Record<string, string> = { idle: "Inactif", empty: "À vide", loaded: "Chargé", loading: "Chargement", wait: "Attente", break: "Pause" };
export const LOT_COLORS = ["#3b7dd8", "#e67e22", "#8e44ad", "#16a085", "#c0392b", "#2c3e50", "#d35400", "#27ae60", "#7f8c8d", "#f1c40f"];
export const lotColor = (i: number) => LOT_COLORS[i % LOT_COLORS.length];

// ------------------------------------------------------------------ lecture de la trace
export interface BundleView { id: number; x: number; y: number; qty: number; lot: number; rework: boolean; kind: number; z: number }
export interface ActorView { id: string; kind: "operator" | "transporter"; name: string; x: number; y: number; state: number; heading: number; load: number }
export interface CarrierView { id: number; x: number; y: number; loaded: boolean; moving: boolean }
export interface Frame { t: number; stations: number[]; bundles: BundleView[]; actors: ActorView[]; done: number; wip: number; carriers: CarrierView[] }

/** Point de la boucle du convoyeur à l'abscisse curviligne s (modulo la longueur). */
export function railPoint(cv: DesConveyor, s: number): [number, number] {
  const pts = cv.pts!, cum = cv.cum!, L = cum[cum.length - 1];
  let u = L > 0 ? ((s % L) + L) % L : 0;
  let lo = 1, hi = cum.length - 1;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (cum[mid] < u) lo = mid + 1; else hi = mid; }
  const seg = cum[lo] - cum[lo - 1]; u = seg > 0 ? (u - cum[lo - 1]) / seg : 0;
  const a = pts[lo - 1], b = pts[lo];
  return [a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u];
}

interface CursorState {
  i: number; st: Int8Array; bLoc: Int16Array; bRef: Int16Array; bT: Float32Array; bPrev: Float32Array; aState: Int8Array;
  aMove: { t0: number; t1: number; path: number }[]; aPos: Float32Array; done: number; bQty: Int16Array;
  cT0: Float32Array; cT1: Float32Array; cS0: Float32Array; cS1: Float32Array; cPark: Int8Array; cRef: Int16Array; cLoad: Int8Array;
}

const KEY_EVERY = 3000;

/** Rejoue la trace vers l'avant ; points de reprise tous les 3 000 événements pour les sauts arrière. */
export class TraceCursor {
  private s: CursorState;
  private keys: { t: number; s: CursorState }[] = [];
  readonly pos: Map<string, { x: number; y: number; qx: number; qy: number; mx: number; my: number }>;
  readonly src: [number, number]; readonly sink: [number, number];
  readonly sidx: string[];
  readonly cv: DesConveyor | null;

  constructor(public trace: Trace, model: DesModel) {
    this.cv = model.conveyor?.enabled && model.conveyor.pts?.length ? model.conveyor : null;
    this.sidx = trace.stations;
    this.pos = new Map(model.stations.map((s) => [s.id, { x: s.x, y: s.y, qx: s.qx, qy: s.qy, mx: s.mx ?? s.x, my: s.my ?? s.y - 0.75 }]));
    this.src = [model.source.x, model.source.y];
    this.sink = [model.sink.x, model.sink.y];
    this.s = this.fresh();
    this.keys.push({ t: -1, s: this.clone(this.s) });
  }

  private fresh(): CursorState {
    const nB = this.trace.bundles.length, nA = this.trace.actors.length;
    const aPos = new Float32Array(nA * 2);
    this.trace.actors.forEach((a, k) => { aPos[2 * k] = a.start[0]; aPos[2 * k + 1] = a.start[1]; });
    const bQty = new Int16Array(nB);
    this.trace.bundles.forEach((b, k) => { bQty[k] = b[1]; });
    const nC = this.trace.carriers?.length ?? 0;
    return {
      cT0: new Float32Array(nC), cT1: new Float32Array(nC), cS0: new Float32Array(nC), cS1: new Float32Array(nC), cPark: new Int8Array(nC), cRef: new Int16Array(nC), cLoad: new Int8Array(nC),
      i: 0, st: new Int8Array(this.sidx.length).fill(1), bLoc: new Int16Array(nB).fill(-1), bRef: new Int16Array(nB), bT: new Float32Array(nB),
      bPrev: new Float32Array(nB * 2), aState: new Int8Array(nA), aMove: this.trace.actors.map(() => ({ t0: 0, t1: 0, path: -1 })), aPos, done: 0, bQty,
    };
  }
  private clone(s: CursorState): CursorState {
    return { i: s.i, st: s.st.slice(), bLoc: s.bLoc.slice(), bRef: s.bRef.slice(), bT: s.bT.slice(), bPrev: s.bPrev.slice(), aState: s.aState.slice(),
      aMove: s.aMove.map((m) => ({ ...m })), aPos: s.aPos.slice(), done: s.done, bQty: s.bQty.slice(),
      cT0: s.cT0.slice(), cT1: s.cT1.slice(), cS0: s.cS0.slice(), cS1: s.cS1.slice(), cPark: s.cPark.slice(), cRef: s.cRef.slice(), cLoad: s.cLoad.slice() };
  }

  /** Position statique d'un lieu (file, poste, sortie de poste, source, sortie). */
  private locPoint(kind: number, ref: number): [number, number] {
    if (kind === 6) return this.src;
    if (kind === 5) return this.sink;
    const p = this.pos.get(this.sidx[ref]);
    if (!p) return [0, 0];
    if (kind === 0) return [p.qx, p.qy];
    if (kind === 1) return [p.x + (p.mx - p.x) * 0.55, p.y + (p.my - p.y) * 0.55];
    return [2 * p.mx - p.qx, 2 * p.my - p.qy];
  }

  private actorAt(k: number, t: number): [number, number, number] {
    const m = this.s.aMove[k];
    if (m.path < 0) return [this.s.aPos[2 * k], this.s.aPos[2 * k + 1], 0];
    const pts = this.trace.paths[m.path];
    if (t >= m.t1 || m.t1 <= m.t0) { const e = pts[pts.length - 1]; return [e[0], e[1], 0]; }
    const f = Math.max(0, (t - m.t0) / (m.t1 - m.t0));
    let L = 0;
    const seg: number[] = [];
    for (let i = 1; i < pts.length; i++) { const d = Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]); seg.push(d); L += d; }
    let target = f * L;
    for (let i = 1; i < pts.length; i++) {
      if (target <= seg[i - 1] || i === pts.length - 1) {
        const u = seg[i - 1] > 0 ? Math.min(1, target / seg[i - 1]) : 1;
        const a = pts[i - 1], b = pts[i];
        return [a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u, Math.atan2(b[1] - a[1], b[0] - a[0])];
      }
      target -= seg[i - 1];
    }
    const e = pts[pts.length - 1];
    return [e[0], e[1], 0];
  }

  private apply(ev: number[]) {
    const s = this.s;
    const t = ev[0], code = ev[1];
    if (code === 0) s.st[ev[2]] = ev[3];
    else if (code === 1) {
      const b = ev[2];
      // position de départ pour l'animation d'un saut file → file
      const [px, py] = s.bLoc[b] >= 0 && s.bLoc[b] !== 3 && s.bLoc[b] !== 4 ? this.locPoint(s.bLoc[b], s.bRef[b]) : [NaN, NaN];
      s.bPrev[2 * b] = px; s.bPrev[2 * b + 1] = py;
      if (ev[3] === 5 && s.bLoc[b] !== 5) s.done += s.bQty[b];
      if (ev[3] === 7) s.cLoad[ev[4]] = 1;
      s.bLoc[b] = ev[3]; s.bRef[b] = ev[4]; s.bT[b] = t;
    } else if (code === 2) {
      const k = ev[2];
      const pts = this.trace.paths[ev[4]];
      s.aMove[k] = { t0: t, t1: ev[3], path: ev[4] };
      const e = pts[pts.length - 1]; s.aPos[2 * k] = e[0]; s.aPos[2 * k + 1] = e[1];
    } else if (code === 3) s.aState[ev[2]] = ev[3];
    else if (code === 4) { const c = ev[2]; s.cT0[c] = t; s.cT1[c] = ev[3]; s.cS0[c] = ev[4]; s.cS1[c] = ev[5]; s.cPark[c] = -1; }
    else if (code === 5) {
      const c = ev[2]; s.cPark[c] = ev[3]; s.cRef[c] = ev[4];
      if (ev[3] === 0 || ev[3] === 5) s.cLoad[c] = 0; else s.cLoad[c] = 1;
    }
  }

  /** Positions des cintres : sur la boucle (interpolées), dans les dérivations (empilés), aux postes. */
  private carriers(t: number): CarrierView[] {
    const cv = this.cv; if (!cv) return [];
    const s = this.s, out: CarrierView[] = [];
    const slots = new Map<string, number>();
    const pitch = Math.max(0.12, cv.pitch_m ?? 0.3);
    for (let c = 0; c < s.cPark.length; c++) {
      const park = s.cPark[c];
      let x = 0, y = 0;
      if (park === -1) {
        const f = s.cT1[c] > s.cT0[c] ? Math.min(1, Math.max(0, (t - s.cT0[c]) / (s.cT1[c] - s.cT0[c]))) : 1;
        [x, y] = railPoint(cv, s.cS0[c] + (s.cS1[c] - s.cS0[c]) * f);
      } else if (park === 1 || park === 2 || park === 3) {
        const sp = cv.spurs?.[this.sidx[s.cRef[c]]]; if (!sp) continue;
        const key = `${park === 3 ? "m" : "q"}${s.cRef[c]}`;
        const k = slots.get(key) ?? 0; slots.set(key, k + 1);
        const L = Math.max(0.01, sp.len), from = park === 3 ? sp.pt : sp.to, to = park === 3 ? sp.to : sp.pt;
        const u = park === 2 ? 0 : Math.min(1, ((park === 3 ? 0.15 : 0.25) + k * pitch) / L);
        x = from[0] + (to[0] - from[0]) * u; y = from[1] + (to[1] - from[1]) * u;
        if (park === 2) { const p = this.pos.get(this.sidx[s.cRef[c]]); if (p) { x = (sp.to[0] + p.x) / 2; y = (sp.to[1] + p.y) / 2; } }
      } else {
        const base = park === 5 ? cv.unload_pt : cv.load_pt; if (!base) continue;
        const key = `p${park}`; const k = slots.get(key) ?? 0; slots.set(key, k + 1);
        // stock de cintres vides : en file le long de la boucle avant le chargement
        if (park === 0) [x, y] = railPoint(cv, (cv.s_load ?? 0) - 0.4 - (k % 40) * pitch * 0.5);
        else [x, y] = base;
        if (park === 0 && k >= 40) continue;
      }
      out.push({ id: c, x, y, loaded: s.cLoad[c] === 1, moving: park === -1 });
    }
    return out;
  }

  seek(t: number) {
    const ev = this.trace.events;
    if (ev.length && this.s.i > 0 && ev[this.s.i - 1][0] > t) {
      let key = this.keys[0];
      for (const k of this.keys) if (k.t <= t) key = k;
      this.s = this.clone(key.s);
    }
    while (this.s.i < ev.length && ev[this.s.i][0] <= t) {
      this.apply(ev[this.s.i]);
      this.s.i++;
      if (this.s.i % KEY_EVERY === 0 && this.keys[this.keys.length - 1].s.i < this.s.i) this.keys.push({ t: ev[this.s.i - 1][0], s: this.clone(this.s) });
    }
  }

  frame(t: number): Frame {
    this.seek(t);
    const s = this.s;
    const actors: ActorView[] = this.trace.actors.map((a, k) => {
      const [x, y, h] = this.actorAt(k, t);
      return { id: a.id, kind: a.kind, name: a.name, x, y, heading: h, state: s.aState[k], load: 0 };
    });
    const carriers = this.carriers(t);
    const bundles: BundleView[] = [];
    const stack = new Map<string, number>();
    let wip = 0;
    for (let b = 0; b < s.bLoc.length; b++) {
      const kind = s.bLoc[b];
      if (kind < 0 || kind === 5) continue;
      const meta = this.trace.bundles[b];
      const qty = s.bQty[b] || meta[1];
      wip += qty;
      let x: number, y: number, z = 0;
      if (kind === 7) {
        const c = carriers.find((k) => k.id === s.bRef[b]);
        if (!c) continue;
        x = c.x; y = c.y; z = 0;
      } else if (kind === 3 || kind === 4) {
        const a = actors[s.bRef[b]];
        a.load += 1;
        x = a.x; y = a.y; z = a.load;
      } else {
        [x, y] = this.locPoint(kind, s.bRef[b]);
        const key = `${kind}:${s.bRef[b]}`;
        z = stack.get(key) ?? 0; stack.set(key, z + 1);
        const px = s.bPrev[2 * b], py = s.bPrev[2 * b + 1], dt = t - s.bT[b];
        if (!Number.isNaN(px) && dt < 0.35) { const u = dt / 0.35; x = px + (x - px) * u; y = py + (y - py) * u; }
      }
      bundles.push({ id: b, x, y, z, qty, lot: meta[0], rework: meta[2] === 1, kind });
    }
    return { t, stations: Array.from(s.st), bundles, actors, done: s.done, wip, carriers };
  }
}

export function fmtClock(min: number, startHour = 8) {
  const m = Math.max(0, Math.floor(min));
  const h = startHour + Math.floor(m / 60), mm = m % 60;
  const sec = Math.floor((min - m) * 60);
  return `${String(h).padStart(2, "0")}:${String(mm).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
}
