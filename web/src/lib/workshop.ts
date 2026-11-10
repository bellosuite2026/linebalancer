// Plan d'atelier (cartographie) : types, bibliothèque de machines, géométrie, contrôles, fond de plan,
// exports. Même catalogue et mêmes conventions que engine/workshop.py (mètres, y vers le bas, rotation horaire).
import { supabase } from "./supabase";
import { MACHINE_CATEGORIES, MACHINE_LIBRARY, MACHINE_SOURCES } from "./machineLibrary";

export type MachineStatus = "service" | "panne" | "reserve";
export type OperatorSide = "front" | "back" | "left" | "right";
export interface Wall { id: string; kind: "wall"; x1: number; y1: number; x2: number; y2: number; thickness: number }
export interface Pillar { id: string; kind: "pillar"; x: number; y: number; w: number; d: number }
export interface Door { id: string; kind: "door"; x: number; y: number; width: number; rot: number; exit: boolean }
export interface Aisle { id: string; kind: "aisle"; x: number; y: number; w: number; h: number; main: boolean }
export interface Zone { id: string; kind: "zone"; x: number; y: number; w: number; h: number; zone: string; name: string }
export interface Machine {
  id: string; kind: "machine"; type: string; x: number; y: number; w: number; d: number; rot: number;
  label: string; operator: OperatorSide; status: MachineStatus; ws_id?: string;
}
/** Cote gardée sur le plan (outil Mesure) : distance, chaîne, surface (2 coins) ou chemin à pied (tracé). */
export type DimMode = "dist" | "chain" | "area" | "walk";
export interface Dim { id: string; kind: "dim"; mode: DimMode; pts: P[]; note?: string }
export type El = Wall | Pillar | Door | Aisle | Zone | Machine | Dim;
export interface Background { path: string; x: number; y: number; width_m: number; height_m: number; opacity: number; source?: string }
export interface PlanSettings { grid: number; snap: boolean; main_aisle_min: number; secondary_aisle_min: number; exit_max_m: number; wall_height: number }
export interface WorkshopPlan {
  id?: string; org_id?: string; name: string; version: "actuel" | "projet" | "archive"; width_m: number; length_m: number;
  background: Background | null; elements: El[]; settings: Partial<PlanSettings>; updated_at?: string; machine_count?: number;
}
export type PlanSummary = Omit<WorkshopPlan, "elements" | "settings"> & { id: string; machine_count: number; updated_at: string };

export const DEFAULT_SETTINGS: PlanSettings = { grid: 0.1, snap: true, main_aisle_min: 1.2, secondary_aisle_min: 0.8, exit_max_m: 40, wall_height: 3 };
export const settingsOf = (p: WorkshopPlan): PlanSettings => ({ ...DEFAULT_SETTINGS, ...(p.settings || {}) });

/** Bibliothèque de machines (générée depuis engine/machine_library.py : encombrement réel par défaut,
 * catégorie, familles d'opérations du catalogue, modèle 3D paramétrique). */
export const MACHINE_CATALOG: Record<string, { label: string; w: number; d: number; h: number; machine_type: string; short: string;
  category: string; shape: string; ops: string[]; source: string }> = MACHINE_LIBRARY;
export const CATEGORY_COLOR: Record<string, string> = {
  piqure: "#4a7fb5", surjet: "#7a5fb0", auto: "#c06a2b", coupe: "#8a7a3a", repassage: "#b8455a", controle: "#2f8f7f", logistique: "#6f7780",
};
export { MACHINE_CATEGORIES, MACHINE_SOURCES };
export const ZONES: Record<string, { label: string; color: string }> = {
  coupe: { label: "Coupe", color: "#f4d6a0" }, preparation: { label: "Préparation", color: "#d8e8c8" },
  montage: { label: "Montage", color: "#cfe0f3" }, finition: { label: "Finition", color: "#e6d5f0" },
  repassage: { label: "Repassage", color: "#f6d0d0" }, controle: { label: "Contrôle", color: "#d3efe9" },
  stock: { label: "Stock / magasin", color: "#e6e1d3" }, expedition: { label: "Expédition", color: "#f0e6b8" },
};
export const STATUS_LABEL: Record<MachineStatus, string> = { service: "En service", panne: "En panne", reserve: "Réserve" };
export const machineType = (m: Machine) => MACHINE_CATALOG[m.type]?.machine_type ?? m.type;

export const uid = () => (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`).slice(0, 12);
export const r2 = (v: number) => Math.round(v * 100) / 100;

export const emptyPlan = (name = "Atelier actuel"): WorkshopPlan => ({
  name, version: "actuel", width_m: 30, length_m: 20, background: null, settings: { ...DEFAULT_SETTINGS },
  elements: [
    { id: uid(), kind: "wall", x1: 0, y1: 0, x2: 30, y2: 0, thickness: 0.2 },
    { id: uid(), kind: "wall", x1: 30, y1: 0, x2: 30, y2: 20, thickness: 0.2 },
    { id: uid(), kind: "wall", x1: 30, y1: 20, x2: 0, y2: 20, thickness: 0.2 },
    { id: uid(), kind: "wall", x1: 0, y1: 20, x2: 0, y2: 0, thickness: 0.2 },
  ],
});

/** Change la taille de la salle ; les murs posés sur l'ancien contour (droite / bas) suivent. */
export function resizeRoom(p: WorkshopPlan, width: number, length: number): WorkshopPlan {
  const W0 = p.width_m, L0 = p.length_m, W = Math.max(2, width), L = Math.max(2, length);
  const fx = (v: number) => (Math.abs(v - W0) < 1e-6 ? W : v), fy = (v: number) => (Math.abs(v - L0) < 1e-6 ? L : v);
  const onEdge = (w: Wall) => [w.x1, w.x2].some((v) => Math.abs(v - W0) < 1e-6 || Math.abs(v) < 1e-6) && [w.y1, w.y2].some((v) => Math.abs(v - L0) < 1e-6 || Math.abs(v) < 1e-6);
  return { ...p, width_m: W, length_m: L, elements: p.elements.map((e) => (e.kind === "wall" && onEdge(e)
    ? { ...e, x1: fx(e.x1), x2: fx(e.x2), y1: fy(e.y1), y2: fy(e.y2) } : e)) };
}

export function newMachine(type: string, x: number, y: number, label: string): Machine {
  const c = MACHINE_CATALOG[type] ?? MACHINE_CATALOG.piqueuse_plate;
  return { id: uid(), kind: "machine", type, x: r2(x), y: r2(y), w: c.w, d: c.d, rot: 0, label, operator: "front", status: "service" };
}

/** Numéro suivant : M01, M02… (le n° le plus grand + 1). */
export function nextLabel(els: El[]): string {
  let max = 0;
  for (const e of els) if (e.kind === "machine") { const m = /(\d+)\s*$/.exec(e.label); if (m) max = Math.max(max, +m[1]); }
  return `M${String(max + 1).padStart(2, "0")}`;
}

// ------------------------------------------------------------------ géométrie
export type P = [number, number];
const rot = (lx: number, ly: number, deg: number): P => {
  const a = (deg * Math.PI) / 180;
  return [lx * Math.cos(a) - ly * Math.sin(a), lx * Math.sin(a) + ly * Math.cos(a)];
};
export function rectCorners(cx: number, cy: number, w: number, d: number, deg: number): P[] {
  return ([[-w / 2, -d / 2], [w / 2, -d / 2], [w / 2, d / 2], [-w / 2, d / 2]] as P[]).map(([lx, ly]) => {
    const [dx, dy] = rot(lx, ly, deg); return [cx + dx, cy + dy];
  });
}
export const machineCorners = (m: Machine) => rectCorners(m.x, m.y, m.w, m.d, m.rot);
export function operatorPoint(m: Machine): P {
  const g = 0.45;
  const [lx, ly] = ({ front: [0, m.d / 2 + g], back: [0, -m.d / 2 - g], left: [-m.w / 2 - g, 0], right: [m.w / 2 + g, 0] } as Record<OperatorSide, P>)[m.operator ?? "front"];
  const [dx, dy] = rot(lx, ly, m.rot);
  return [m.x + dx, m.y + dy];
}
const boxPoly = (x: number, y: number, w: number, h: number): P[] => [[x, y], [x + w, y], [x + w, y + h], [x, y + h]];
export function wallPoly(w: Wall): P[] {
  const dx = w.x2 - w.x1, dy = w.y2 - w.y1, L = Math.hypot(dx, dy) || 1, t = (w.thickness || 0.2) / 2;
  const nx = (-dy / L) * t, ny = (dx / L) * t;
  return [[w.x1 + nx, w.y1 + ny], [w.x2 + nx, w.y2 + ny], [w.x2 - nx, w.y2 - ny], [w.x1 - nx, w.y1 - ny]];
}
export function elPoly(e: El): P[] {
  switch (e.kind) {
    case "machine": return machineCorners(e);
    case "wall": return wallPoly(e);
    case "pillar": return boxPoly(e.x - e.w / 2, e.y - e.d / 2, e.w, e.d);
    case "door": return rectCorners(e.x, e.y, e.width, 0.3, e.rot);
    case "aisle": case "zone": return boxPoly(e.x, e.y, e.w, e.h);
    case "dim": {
      const xs = e.pts.map((p) => p[0]), ys = e.pts.map((p) => p[1]);
      const x0 = Math.min(...xs), y0 = Math.min(...ys);
      return boxPoly(x0, y0, Math.max(0.01, Math.max(...xs) - x0), Math.max(0.01, Math.max(...ys) - y0));
    }
  }
}
/** Recouvrement de deux polygones convexes (axes séparateurs), avec une tolérance en mètres. */
export function overlap(a: P[], b: P[], tol = 0.02): boolean {
  for (const poly of [a, b]) {
    for (let i = 0; i < poly.length; i++) {
      const [x1, y1] = poly[i], [x2, y2] = poly[(i + 1) % poly.length];
      const nx = y2 - y1, ny = x1 - x2, L = Math.hypot(nx, ny) || 1;
      const pa = a.map(([x, y]) => (x * nx + y * ny) / L), pb = b.map(([x, y]) => (x * nx + y * ny) / L);
      if (Math.max(...pa) - tol <= Math.min(...pb) || Math.max(...pb) - tol <= Math.min(...pa)) return false;
    }
  }
  return true;
}
export function elCenter(e: El): P {
  if (e.kind === "dim") { const b = elPoly(e); return [(b[0][0] + b[2][0]) / 2, (b[0][1] + b[2][1]) / 2]; }
  if (e.kind === "wall") return [(e.x1 + e.x2) / 2, (e.y1 + e.y2) / 2];
  if (e.kind === "aisle" || e.kind === "zone") return [e.x + e.w / 2, e.y + e.h / 2];
  return [e.x, e.y];
}
export function moveEl<T extends El>(e: T, dx: number, dy: number): T {
  if (e.kind === "wall") return { ...e, x1: r2(e.x1 + dx), y1: r2(e.y1 + dy), x2: r2(e.x2 + dx), y2: r2(e.y2 + dy) };
  if (e.kind === "dim") return { ...e, pts: e.pts.map(([x, y]) => [r2(x + dx), r2(y + dy)] as P) };
  return { ...e, x: r2((e as Machine).x + dx), y: r2((e as Machine).y + dy) };
}
export function hitTest(els: El[], x: number, y: number, tol = 0.15): El | null {
  const order: El["kind"][] = ["dim", "machine", "pillar", "door", "wall", "aisle", "zone"];
  for (const k of order) {
    for (let i = els.length - 1; i >= 0; i--) {
      const e = els[i]; if (e.kind !== k) continue;
      if (k === "dim") { if (dimSegments(e as Dim).some(([a, b]) => segDist(x, y, a[0], a[1], b[0], b[1]) <= tol) || Math.hypot(x - dimLabelAt(e as Dim)[0], y - dimLabelAt(e as Dim)[1]) <= tol * 2) return e; continue; }
      if (k === "wall") { const w = e as Wall; if (segDist(x, y, w.x1, w.y1, w.x2, w.y2) <= Math.max(0.15, w.thickness / 2 + 0.05)) return e; continue; }
      if (k === "door") { if (Math.hypot(x - (e as Door).x, y - (e as Door).y) <= Math.max(0.4, (e as Door).width / 2)) return e; continue; }
      if (pointIn(elPoly(e), x, y)) return e;
    }
  }
  return null;
}
export function pointIn(poly: P[], x: number, y: number): boolean {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}
export function segDist(px: number, py: number, x1: number, y1: number, x2: number, y2: number) {
  const vx = x2 - x1, vy = y2 - y1, L2 = vx * vx + vy * vy;
  const t = L2 ? Math.max(0, Math.min(1, ((px - x1) * vx + (py - y1) * vy) / L2)) : 0;
  return Math.hypot(px - (x1 + t * vx), py - (y1 + t * vy));
}
// ------------------------------------------------------------------ cotes / mesures
export const polyLen = (pts: P[]) => pts.slice(1).reduce((a, p, i) => a + Math.hypot(p[0] - pts[i][0], p[1] - pts[i][1]), 0);
/** Segments dessinés d'une cote (surface : les 4 côtés du rectangle). */
export function dimSegments(d: Dim): [P, P][] {
  if (d.mode === "area" && d.pts.length >= 2) {
    const [[x0, y0], [x1, y1]] = d.pts; const c: P[] = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]];
    return c.map((p, i) => [p, c[(i + 1) % 4]] as [P, P]);
  }
  return d.pts.slice(1).map((p, i) => [d.pts[i], p] as [P, P]);
}
export function dimLabelAt(d: Dim): P {
  if (d.mode === "area" && d.pts.length >= 2) return [(d.pts[0][0] + d.pts[1][0]) / 2, (d.pts[0][1] + d.pts[1][1]) / 2];
  // milieu (en longueur) de la polyligne
  let L = polyLen(d.pts) / 2;
  for (let i = 1; i < d.pts.length; i++) {
    const a = d.pts[i - 1], b = d.pts[i], s = Math.hypot(b[0] - a[0], b[1] - a[1]);
    if (L <= s || i === d.pts.length - 1) { const k = s ? Math.min(1, L / s) : 0; return [a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k]; }
    L -= s;
  }
  return d.pts[0] ?? [0, 0];
}
const nf = (v: number, n = 2) => v.toLocaleString("fr-FR", { minimumFractionDigits: n, maximumFractionDigits: n });
/** Texte de la cote, en mètres (le plan est en mètres : l'échelle calibrée du fond s'y applique déjà). */
export function dimText(d: Dim): string {
  if (d.mode === "area" && d.pts.length >= 2) {
    const w = Math.abs(d.pts[1][0] - d.pts[0][0]), h = Math.abs(d.pts[1][1] - d.pts[0][1]);
    return `${nf(w)} × ${nf(h)} m = ${nf(w * h, 1)} m²`;
  }
  const L = polyLen(d.pts);
  if (d.mode === "walk") return `à pied ${nf(L, 1)} m`;
  return `${nf(L)} m`;
}
/** Points d'aimantation de l'outil Mesure : coins et centres des machines, poteaux, extrémités et milieux des murs, coins des allées/zones. */
export function snapTargets(els: El[]): P[] {
  const out: P[] = [];
  for (const e of els) {
    if (e.kind === "machine") { out.push([e.x, e.y], ...machineCorners(e), operatorPoint(e)); }
    else if (e.kind === "pillar") out.push([e.x, e.y], ...elPoly(e));
    else if (e.kind === "wall") out.push([e.x1, e.y1], [e.x2, e.y2], [(e.x1 + e.x2) / 2, (e.y1 + e.y2) / 2]);
    else if (e.kind === "aisle" || e.kind === "zone") out.push(...elPoly(e));
    else if (e.kind === "door") out.push([e.x, e.y]);
    else if (e.kind === "dim") out.push(...e.pts);
  }
  return out;
}
/** Aimante un point : sur un point remarquable proche, sinon sur la face d'un mur (projection), sinon rien. */
export function snapMeasure(els: El[], p: P, radius: number): { p: P; label: string } | null {
  let best: P | null = null, bd = radius;
  for (const q of snapTargets(els)) { const d = Math.hypot(q[0] - p[0], q[1] - p[1]); if (d < bd) { bd = d; best = q; } }
  if (best) return { p: [r2(best[0]), r2(best[1])], label: "point" };
  let wb: P | null = null, wd = radius * 0.8;
  for (const e of els) if (e.kind === "wall") {
    // projection sur l'axe du mur, décalée sur la face la plus proche
    const vx = e.x2 - e.x1, vy = e.y2 - e.y1, L2 = vx * vx + vy * vy || 1, L = Math.sqrt(L2);
    const t = Math.max(0, Math.min(1, ((p[0] - e.x1) * vx + (p[1] - e.y1) * vy) / L2));
    const cx = e.x1 + t * vx, cy = e.y1 + t * vy, nx = -vy / L, ny = vx / L, side = (p[0] - cx) * nx + (p[1] - cy) * ny >= 0 ? 1 : -1;
    const fx = cx + nx * side * (e.thickness / 2), fy = cy + ny * side * (e.thickness / 2);
    const d = Math.hypot(p[0] - fx, p[1] - fy);
    if (d < wd) { wd = d; wb = [fx, fy]; }
  }
  return wb ? { p: [r2(wb[0]), r2(wb[1])], label: "mur" } : null;
}

/** Chemin à pied le plus court entre les places opératrices de deux machines (grille 10–25 cm,
 * murs, poteaux et autres machines = obstacles, portes ouvertes). Même principe que les distances aux issues. */
export function walkRoute(plan: WorkshopPlan, aId: string, bId: string): { pts: P[]; length: number } | null {
  const A = plan.elements.find((e): e is Machine => e.id === aId && e.kind === "machine");
  const B = plan.elements.find((e): e is Machine => e.id === bId && e.kind === "machine");
  if (!A || !B) return null;
  const c = Math.max(0.1, Math.min(0.25, Math.sqrt((plan.width_m * plan.length_m) / 60000)));
  const nx = Math.ceil(plan.width_m / c), ny = Math.ceil(plan.length_m / c);
  const block = new Uint8Array(nx * ny);
  const mark = (poly: P[], v: number) => {
    const xs = poly.map((p) => p[0]), ys = poly.map((p) => p[1]);
    for (let j = Math.max(0, Math.floor(Math.min(...ys) / c)); j <= Math.min(ny - 1, Math.floor(Math.max(...ys) / c)); j++)
      for (let i = Math.max(0, Math.floor(Math.min(...xs) / c)); i <= Math.min(nx - 1, Math.floor(Math.max(...xs) / c)); i++)
        if (pointIn(poly, (i + 0.5) * c, (j + 0.5) * c)) block[j * nx + i] = v;
  };
  for (const e of plan.elements) {
    if (e.kind === "wall") mark(wallPoly({ ...e, thickness: Math.max(e.thickness, c * 1.2) }), 1);
    else if (e.kind === "pillar" || (e.kind === "machine" && e.id !== aId && e.id !== bId)) mark(elPoly(e), 1);
  }
  for (const d of plan.elements) if (d.kind === "door") mark(rectCorners(d.x, d.y, d.width, 0.6, d.rot), 0);
  const cell = (p: P) => [Math.min(nx - 1, Math.max(0, Math.floor(p[0] / c))), Math.min(ny - 1, Math.max(0, Math.floor(p[1] / c)))];
  const pa = operatorPoint(A), pb = operatorPoint(B);
  const [ai, aj] = cell(pa), [bi, bj] = cell(pb);
  const start = aj * nx + ai, goal = bj * nx + bi;
  block[start] = 0; block[goal] = 0;
  const dist = new Float64Array(nx * ny).fill(Infinity), prev = new Int32Array(nx * ny).fill(-1);
  const heap: [number, number][] = [];
  const h = (k: number) => Math.hypot((k % nx) - bi, ((k / nx) | 0) - bj);
  const push = (f: number, k: number) => { heap.push([f, k]); let i = heap.length - 1; while (i > 0) { const p = (i - 1) >> 1; if (heap[p][0] <= heap[i][0]) break; [heap[p], heap[i]] = [heap[i], heap[p]]; i = p; } };
  const pop = () => { const top = heap[0]; const last = heap.pop()!; if (heap.length) { heap[0] = last; let i = 0; for (;;) { const l = 2 * i + 1, r = l + 1; let m = i; if (l < heap.length && heap[l][0] < heap[m][0]) m = l; if (r < heap.length && heap[r][0] < heap[m][0]) m = r; if (m === i) break; [heap[m], heap[i]] = [heap[i], heap[m]]; i = m; } } return top; };
  dist[start] = 0; push(h(start), start);
  const S2 = Math.SQRT2;
  while (heap.length) {
    const [, k] = pop(); if (k === goal) break;
    const i = k % nx, j = (k / nx) | 0, dk = dist[k];
    for (const [di, dj] of [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [1, -1], [-1, 1], [-1, -1]]) {
      const ni = i + di, nj = j + dj; if (ni < 0 || nj < 0 || ni >= nx || nj >= ny) continue;
      const nk = nj * nx + ni; if (block[nk]) continue;
      if (di && dj && (block[j * nx + ni] || block[nj * nx + i])) continue;
      const nd = dk + (di && dj ? S2 : 1);
      if (nd < dist[nk]) { dist[nk] = nd; prev[nk] = k; push(nd + h(nk), nk); }
    }
  }
  if (!isFinite(dist[goal])) return null;
  const cells: P[] = [];
  for (let k = goal; k !== -1; k = prev[k]) cells.push([((k % nx) + 0.5) * c, (((k / nx) | 0) + 0.5) * c]);
  cells.reverse();
  // simplification : on garde les points où la direction change, puis on raccourcit en ligne droite quand c'est libre
  const free = (p: P, q: P) => {
    const n = Math.ceil(Math.hypot(q[0] - p[0], q[1] - p[1]) / (c / 2));
    for (let s = 0; s <= n; s++) { const x = p[0] + ((q[0] - p[0]) * s) / Math.max(1, n), y = p[1] + ((q[1] - p[1]) * s) / Math.max(1, n); const [ci, cj] = cell([x, y]); if (block[cj * nx + ci]) return false; }
    return true;
  };
  const pts: P[] = [pa];
  let anchor = pa;
  for (let i = 1; i < cells.length; i++) if (!free(anchor, cells[i])) { anchor = cells[i - 1]; pts.push(anchor); }
  pts.push(pb);
  const out = pts.map(([x, y]) => [r2(x), r2(y)] as P);
  return { pts: out, length: polyLen(out) };
}

/** Orientation du mur le plus proche (pour poser une porte dans l'axe du mur). */
export function nearestWallAngle(els: El[], x: number, y: number): { angle: number; x: number; y: number } | null {
  let best: { d: number; angle: number; x: number; y: number } | null = null;
  for (const e of els) {
    if (e.kind !== "wall") continue;
    const d = segDist(x, y, e.x1, e.y1, e.x2, e.y2);
    if (d < 0.8 && (!best || d < best.d)) {
      const vx = e.x2 - e.x1, vy = e.y2 - e.y1, L2 = vx * vx + vy * vy || 1;
      const t = Math.max(0, Math.min(1, ((x - e.x1) * vx + (y - e.y1) * vy) / L2));
      best = { d, angle: (Math.atan2(vy, vx) * 180) / Math.PI, x: e.x1 + t * vx, y: e.y1 + t * vy };
    }
  }
  return best && { angle: best.angle, x: r2(best.x), y: r2(best.y) };
}

// ------------------------------------------------------------------ contrôles (repères, pas une norme)
export interface Issue { level: "err" | "warn" | "info"; msg: string; ids: string[] }

/** Distances à pied jusqu'à l'issue la plus proche (grille 25 cm, murs/poteaux/machines = obstacles). */
export function exitDistances(plan: WorkshopPlan): Map<string, number> | null {
  const exits = plan.elements.filter((e): e is Door => e.kind === "door" && e.exit);
  if (!exits.length) return null;
  const c = Math.max(0.25, Math.sqrt((plan.width_m * plan.length_m) / 40000));
  const nx = Math.ceil(plan.width_m / c), ny = Math.ceil(plan.length_m / c);
  const block = new Uint8Array(nx * ny);
  const mark = (poly: P[], v: number) => {
    const xs = poly.map((p) => p[0]), ys = poly.map((p) => p[1]);
    for (let j = Math.max(0, Math.floor(Math.min(...ys) / c)); j <= Math.min(ny - 1, Math.floor(Math.max(...ys) / c)); j++)
      for (let i = Math.max(0, Math.floor(Math.min(...xs) / c)); i <= Math.min(nx - 1, Math.floor(Math.max(...xs) / c)); i++)
        if (pointIn(poly, (i + 0.5) * c, (j + 0.5) * c)) block[j * nx + i] = v;
  };
  for (const e of plan.elements) {
    if (e.kind === "wall") mark(wallPoly({ ...e, thickness: Math.max(e.thickness, c * 1.2) }), 1);
    else if (e.kind === "pillar" || e.kind === "machine") mark(elPoly(e), 1);
  }
  const dist = new Float64Array(nx * ny).fill(Infinity);
  const heap: [number, number][] = [];
  const push = (d: number, k: number) => { heap.push([d, k]); let i = heap.length - 1; while (i > 0) { const p = (i - 1) >> 1; if (heap[p][0] <= heap[i][0]) break; [heap[p], heap[i]] = [heap[i], heap[p]]; i = p; } };
  const pop = () => { const top = heap[0]; const last = heap.pop()!; if (heap.length) { heap[0] = last; let i = 0; for (;;) { const l = 2 * i + 1, r = l + 1; let m = i; if (l < heap.length && heap[l][0] < heap[m][0]) m = l; if (r < heap.length && heap[r][0] < heap[m][0]) m = r; if (m === i) break; [heap[m], heap[i]] = [heap[i], heap[m]]; i = m; } } return top; };
  for (const d of exits) {
    for (const [px, py] of rectCorners(d.x, d.y, d.width, 0.6, d.rot).concat([[d.x, d.y]])) {
      const i = Math.min(nx - 1, Math.max(0, Math.floor(px / c))), j = Math.min(ny - 1, Math.max(0, Math.floor(py / c)));
      const k = j * nx + i; block[k] = 0; dist[k] = 0; push(0, k);
    }
  }
  const S2 = Math.SQRT2;
  while (heap.length) {
    const [dk, k] = pop(); if (dk > dist[k]) continue;
    const i = k % nx, j = (k / nx) | 0;
    for (const [di, dj] of [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [1, -1], [-1, 1], [-1, -1]]) {
      const ni = i + di, nj = j + dj; if (ni < 0 || nj < 0 || ni >= nx || nj >= ny) continue;
      const nk = nj * nx + ni; if (block[nk]) continue;
      if (di && dj && (block[j * nx + ni] || block[nj * nx + i])) continue;
      const nd = dk + (di && dj ? S2 : 1);
      if (nd < dist[nk]) { dist[nk] = nd; push(nd, nk); }
    }
  }
  const out = new Map<string, number>();
  for (const e of plan.elements) {
    if (e.kind !== "machine") continue;
    const [px, py] = operatorPoint(e);
    const i = Math.min(nx - 1, Math.max(0, Math.floor(px / c))), j = Math.min(ny - 1, Math.max(0, Math.floor(py / c)));
    let best = Infinity;
    for (let dj = -1; dj <= 1; dj++) for (let di = -1; di <= 1; di++) {
      const ni = i + di, nj = j + dj; if (ni < 0 || nj < 0 || ni >= nx || nj >= ny) continue;
      best = Math.min(best, dist[nj * nx + ni] + Math.hypot(di, dj));
    }
    out.set(e.id, best * c);
  }
  return out;
}

export function checkPlan(plan: WorkshopPlan): Issue[] {
  const s = settingsOf(plan);
  const out: Issue[] = [];
  const ms = plan.elements.filter((e): e is Machine => e.kind === "machine");
  const polys = new Map(plan.elements.map((e) => [e.id, elPoly(e)]));
  for (let i = 0; i < ms.length; i++) for (let j = i + 1; j < ms.length; j++)
    if (overlap(polys.get(ms[i].id)!, polys.get(ms[j].id)!)) out.push({ level: "err", msg: `${ms[i].label} et ${ms[j].label} se chevauchent.`, ids: [ms[i].id, ms[j].id] });
  for (const m of ms) {
    for (const e of plan.elements) {
      if ((e.kind === "wall" || e.kind === "pillar") && overlap(polys.get(m.id)!, polys.get(e.id)!))
        out.push({ level: "err", msg: `${m.label} empiète sur ${e.kind === "wall" ? "un mur" : "un poteau"}.`, ids: [m.id, e.id] });
      if (e.kind === "aisle" && overlap(polys.get(m.id)!, polys.get(e.id)!, 0.05))
        out.push({ level: "warn", msg: `${m.label} déborde dans une allée${e.main ? " principale" : ""}.`, ids: [m.id, e.id] });
    }
    if (machineCorners(m).some(([x, y]) => x < -0.01 || y < -0.01 || x > plan.width_m + 0.01 || y > plan.length_m + 0.01))
      out.push({ level: "warn", msg: `${m.label} sort de la salle.`, ids: [m.id] });
  }
  for (const a of plan.elements) {
    if (a.kind !== "aisle") continue;
    const width = Math.min(a.w, a.h), min = a.main ? s.main_aisle_min : s.secondary_aisle_min;
    if (width < min - 1e-6) out.push({ level: "warn", msg: `Allée ${a.main ? "principale" : "secondaire"} de ${width.toFixed(2)} m (repère ${min.toFixed(2)} m).`, ids: [a.id] });
  }
  const seen = new Map<string, string>();
  for (const m of ms) {
    const k = m.label.trim().toLowerCase();
    if (k && seen.has(k)) out.push({ level: "warn", msg: `N° de machine en double : ${m.label}.`, ids: [m.id, seen.get(k)!] });
    seen.set(k, m.id);
  }
  const ex = exitDistances(plan);
  if (!ex) { if (ms.length) out.push({ level: "warn", msg: "Aucune issue de secours dessinée : ajoutez une porte et cochez « issue de secours ».", ids: [] }); }
  else {
    const far = ms.filter((m) => (ex.get(m.id) ?? 0) > s.exit_max_m);
    const blocked = far.filter((m) => !isFinite(ex.get(m.id) ?? 0));
    if (blocked.length) out.push({ level: "err", msg: `Aucun passage vers une issue depuis : ${blocked.map((m) => m.label).join(", ")}.`, ids: blocked.map((m) => m.id) });
    const tooFar = far.filter((m) => isFinite(ex.get(m.id) ?? 0));
    if (tooFar.length) out.push({ level: "warn", msg: `Issue à plus de ${s.exit_max_m} m à pied pour : ${tooFar.map((m) => `${m.label} (${(ex.get(m.id) ?? 0).toFixed(0)} m)`).join(", ")}.`, ids: tooFar.map((m) => m.id) });
    const max = Math.max(0, ...[...ex.values()].filter(isFinite));
    if (ms.length) out.push({ level: "info", msg: `Distance à pied maximale jusqu'à une issue : ${max.toFixed(0)} m (repère ${s.exit_max_m} m).`, ids: [] });
  }
  return out;
}

// ------------------------------------------------------------------ inventaire -> postes de la gamme
export interface WsOut { id: string; name: string; machine_type: string; max_workers: string; section: string; available: boolean }
export function zoneAt(plan: WorkshopPlan, x: number, y: number): string {
  const z = plan.elements.find((e): e is Zone => e.kind === "zone" && x >= e.x && x <= e.x + e.w && y >= e.y && y <= e.y + e.h);
  return z ? z.name || ZONES[z.zone]?.label || "" : "";
}
/** Une machine = un poste (chariots exclus) ; id = poste lié sinon n° de machine. Même règle que l'API. */
export function inventory(plan: WorkshopPlan): { rows: WsOut[]; links: Record<string, string> } {
  const rows: WsOut[] = [], links: Record<string, string> = {}, seen = new Set<string>();
  plan.elements.forEach((e, k) => {
    if (e.kind !== "machine" || !machineType(e)) return;
    const base = (e.ws_id || e.label || `M${String(k + 1).padStart(2, "0")}`).trim().slice(0, 40);
    let id = base, n = 2; while (seen.has(id)) id = `${base}-${n++}`;
    seen.add(id); links[e.id] = id;
    rows.push({ id, name: `${e.label} ${MACHINE_CATALOG[e.type]?.label ?? ""}`.trim(), machine_type: machineType(e), max_workers: "1",
      section: zoneAt(plan, e.x, e.y), available: e.status === "service" });
  });
  return { rows, links };
}

// ------------------------------------------------------------------ fond de plan
export const BUCKET = "workshop-plans";

/** Image ou PDF (1re page rendue par pdf.js) -> PNG/JPEG prêt à déposer. */
export async function fileToImage(file: File): Promise<{ blob: Blob; w: number; h: number; ext: string; source: string }> {
  if (file.type === "application/pdf" || /\.pdf$/i.test(file.name)) {
    const pdfjs = await import("pdfjs-dist");
    const worker = (await import("pdfjs-dist/build/pdf.worker.min.mjs?url")).default;
    pdfjs.GlobalWorkerOptions.workerSrc = worker;
    const doc = await pdfjs.getDocument({ data: await file.arrayBuffer() }).promise;
    const page = await doc.getPage(1);
    const base = page.getViewport({ scale: 1 });
    const scale = Math.min(4, 3000 / Math.max(base.width, base.height));
    const vp = page.getViewport({ scale });
    const canvas = Object.assign(document.createElement("canvas"), { width: Math.round(vp.width), height: Math.round(vp.height) });
    const ctx = canvas.getContext("2d")!;
    ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, canvas.width, canvas.height);
    await page.render({ canvasContext: ctx, viewport: vp }).promise;
    const blob = await new Promise<Blob>((ok, ko) => canvas.toBlob((b) => (b ? ok(b) : ko(new Error("Rendu PDF impossible"))), "image/png"));
    return { blob, w: canvas.width, h: canvas.height, ext: "png", source: `${file.name} (page 1)` };
  }
  if (!/^image\/(png|jpeg|webp)$/.test(file.type)) throw new Error("Format accepté : PNG, JPG, WEBP ou PDF.");
  const url = URL.createObjectURL(file);
  try {
    const img = await loadImage(url);
    // image très grande : réduite à 4000 px pour rester sous 10 Mo
    if (Math.max(img.width, img.height) > 4000 || file.size > 9.5e6) {
      const k = 4000 / Math.max(img.width, img.height);
      const canvas = Object.assign(document.createElement("canvas"), { width: Math.round(img.width * Math.min(1, k)), height: Math.round(img.height * Math.min(1, k)) });
      canvas.getContext("2d")!.drawImage(img, 0, 0, canvas.width, canvas.height);
      const blob = await new Promise<Blob>((ok, ko) => canvas.toBlob((b) => (b ? ok(b) : ko(new Error("Conversion impossible"))), "image/jpeg", 0.85));
      return { blob, w: canvas.width, h: canvas.height, ext: "jpg", source: file.name };
    }
    return { blob: file, w: img.width, h: img.height, ext: file.type === "image/png" ? "png" : file.type === "image/webp" ? "webp" : "jpg", source: file.name };
  } finally { URL.revokeObjectURL(url); }
}
export const loadImage = (src: string) => new Promise<HTMLImageElement>((ok, ko) => {
  const img = new Image(); img.onload = () => ok(img); img.onerror = () => ko(new Error("Image illisible")); img.src = src;
});
export async function uploadBackground(orgId: string, blob: Blob, ext: string): Promise<string> {
  const path = `${orgId}/${uid()}-${Date.now()}.${ext}`;
  const type = ext === "png" ? "image/png" : ext === "webp" ? "image/webp" : "image/jpeg";
  const { error } = await supabase.storage.from(BUCKET).upload(path, blob, { contentType: type, upsert: false });
  if (error) throw new Error(`Envoi du fond de plan impossible : ${error.message}`);
  return path;
}
/** Fond de plan en URL locale (blob:) : affichage et export sans souci de CORS. */
export async function backgroundUrl(path: string): Promise<string> {
  const { data, error } = await supabase.storage.from(BUCKET).download(path);
  if (error || !data) throw new Error(`Fond de plan illisible : ${error?.message ?? "introuvable"}`);
  return URL.createObjectURL(data);
}

// ------------------------------------------------------------------ DXF (murs)
export async function dxfToWalls(text: string, unit: "auto" | "mm" | "cm" | "m"): Promise<{ walls: Wall[]; width: number; length: number; unit: string }> {
  const { default: DxfParser } = await import("dxf-parser");
  const dxf = new DxfParser().parseSync(text) as { header?: Record<string, unknown>; entities?: { type: string; vertices?: { x: number; y: number }[]; shape?: boolean }[] } | null;
  if (!dxf) throw new Error("Fichier DXF illisible.");
  const ins = Number(dxf.header?.["$INSUNITS"] ?? 0);
  const u = unit !== "auto" ? unit : ins === 4 ? "mm" : ins === 5 ? "cm" : ins === 6 ? "m" : "mm";
  const k = u === "mm" ? 0.001 : u === "cm" ? 0.01 : 1;
  const segs: [number, number, number, number][] = [];
  for (const e of dxf.entities ?? []) {
    const v = e.vertices ?? [];
    if (e.type === "LINE" && v.length >= 2) segs.push([v[0].x, v[0].y, v[1].x, v[1].y]);
    else if ((e.type === "LWPOLYLINE" || e.type === "POLYLINE") && v.length >= 2) {
      for (let i = 0; i < v.length - 1; i++) segs.push([v[i].x, v[i].y, v[i + 1].x, v[i + 1].y]);
      if (e.shape) segs.push([v[v.length - 1].x, v[v.length - 1].y, v[0].x, v[0].y]);
    }
  }
  if (!segs.length) throw new Error("Aucune ligne (LINE / LWPOLYLINE) trouvée dans le DXF.");
  if (segs.length > 3000) throw new Error(`DXF trop détaillé (${segs.length} segments, 3000 max) : exportez seulement le calque des murs.`);
  const xs = segs.flatMap((s) => [s[0], s[2]]), ys = segs.flatMap((s) => [s[1], s[3]]);
  const minX = Math.min(...xs), maxY = Math.max(...ys);
  // DXF : y vers le haut -> plan : y vers le bas ; marge de 0,5 m
  const walls = segs.map(([x1, y1, x2, y2]) => ({ id: uid(), kind: "wall" as const, thickness: 0.15,
    x1: r2((x1 - minX) * k + 0.5), y1: r2((maxY - y1) * k + 0.5), x2: r2((x2 - minX) * k + 0.5), y2: r2((maxY - y2) * k + 0.5) }))
    .filter((w) => Math.hypot(w.x2 - w.x1, w.y2 - w.y1) >= 0.05);
  return { walls, width: r2((Math.max(...xs) - minX) * k + 1), length: r2((maxY - Math.min(...ys)) * k + 1), unit: u };
}

// ------------------------------------------------------------------ exports
export async function svgToPng(svg: SVGSVGElement, widthPx: number, heightPx: number, bgHref?: string | null): Promise<Blob> {
  const clone = svg.cloneNode(true) as SVGSVGElement;
  clone.setAttribute("width", String(widthPx)); clone.setAttribute("height", String(heightPx));
  clone.querySelectorAll("[data-noexport]").forEach((n) => n.remove());
  if (bgHref) {
    const img = clone.querySelector("image[data-bg]");
    if (img) {
      const data = await fetch(bgHref).then((r) => r.blob()).then((b) => new Promise<string>((ok) => { const fr = new FileReader(); fr.onload = () => ok(String(fr.result)); fr.readAsDataURL(b); }));
      img.setAttribute("href", data);
    }
  }
  const xml = new XMLSerializer().serializeToString(clone);
  const url = URL.createObjectURL(new Blob([xml], { type: "image/svg+xml;charset=utf-8" }));
  try {
    const img = await loadImage(url);
    const canvas = Object.assign(document.createElement("canvas"), { width: widthPx, height: heightPx });
    const ctx = canvas.getContext("2d")!;
    ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, widthPx, heightPx); ctx.drawImage(img, 0, 0, widthPx, heightPx);
    return await new Promise<Blob>((ok, ko) => canvas.toBlob((b) => (b ? ok(b) : ko(new Error("Export impossible"))), "image/png"));
  } finally { URL.revokeObjectURL(url); }
}
export function saveBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  Object.assign(document.createElement("a"), { href: url, download: name }).click();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}
export async function pngToPdf(png: Blob, title: string, subtitle: string, ratio: number): Promise<Blob> {
  const { jsPDF } = await import("jspdf");
  const landscape = ratio >= 1;
  const doc = new jsPDF({ orientation: landscape ? "landscape" : "portrait", unit: "mm", format: "a4" });
  const W = doc.internal.pageSize.getWidth(), H = doc.internal.pageSize.getHeight();
  doc.setFontSize(14); doc.text(title, 12, 14);
  doc.setFontSize(9); doc.setTextColor(100); doc.text(subtitle, 12, 20);
  const data = await new Promise<string>((ok) => { const fr = new FileReader(); fr.onload = () => ok(String(fr.result)); fr.readAsDataURL(png); });
  const maxW = W - 24, maxH = H - 34;
  let w = maxW, h = w / ratio; if (h > maxH) { h = maxH; w = h * ratio; }
  doc.addImage(data, "PNG", 12, 26, w, h);
  return doc.output("blob");
}
