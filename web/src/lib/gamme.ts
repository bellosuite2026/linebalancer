// Modèle d'édition d'une gamme (valeurs en texte pour une saisie naturelle) et conversions.
import type { Problem } from "./types";

export interface OpRow { id: string; name: string; duration: string; predecessors: string; machine_type: string; skills: string; section: string; optional: boolean; est?: boolean }
export interface WsRow { id: string; name: string; machine_type: string; max_workers: string; section: string; available: boolean }
export interface WkRow { id: string; name: string; skills: string; efficiency: string; assigned_station: string; available: boolean }
export interface Draft { name: string; cycle: string; lineId: string; garment?: string; ops: OpRow[]; ws: WsRow[]; wk: WkRow[] }

export const MACHINES = [
  "piqueuse_plate", "piqueuse_2_aiguilles", "surjeteuse_3_fils", "surjeteuse_4_fils", "surjeteuse_5_fils",
  "recouvreuse", "piqueuse_boutonniere", "piqueuse_bouton", "bride", "zigzag", "presse_vapeur", "fer_repassage",
  "table_repassage", "presse_thermocollage", "chainette", "table_travail", "table_controle", "manuel",
];

const list = (s: string) => s.split(/[;,]/).map((x) => x.trim()).filter(Boolean);
const num = (s: string) => Number(String(s).replace(",", "."));
const join = (a: string[] | undefined) => (a ?? []).join(", ");

export const emptyOp = (id = ""): OpRow => ({ id, name: "", duration: "", predecessors: "", machine_type: "", skills: "", section: "", optional: false });
export const emptyWs = (id = ""): WsRow => ({ id, name: "", machine_type: "", max_workers: "1", section: "", available: true });
export const emptyWk = (id = ""): WkRow => ({ id, name: "", skills: "", efficiency: "1", assigned_station: "", available: true });
export const emptyDraft = (): Draft => ({ name: "", cycle: "", lineId: "", ops: [emptyOp("OP010")], ws: [], wk: [] });

/** Identifiant suivant : OP010 → OP020, WS01 → WS02, W009 → W010. */
export function nextId(ids: string[], prefix: string, width: number, step: number): string {
  let max = 0;
  const re = new RegExp(`^${prefix}(\\d+)$`, "i");
  for (const id of ids) { const m = re.exec(id.trim()); if (m) max = Math.max(max, Number(m[1])); }
  return prefix + String(max + step).padStart(width, "0");
}

export function fromProblem(p: Problem, lineId = ""): Draft {
  return {
    name: p.name ?? "", cycle: p.target_cycle_time ? String(p.target_cycle_time) : "", lineId,
    ops: p.operations.map((o) => ({ id: o.id, name: o.name ?? "", duration: String(o.duration ?? ""), predecessors: join(o.predecessors),
      machine_type: o.machine_type ?? "", skills: join(o.required_skills), section: o.section ?? "", optional: !!o.optional })),
    ws: (p.workstations ?? []).map((w) => ({ id: w.id, name: w.name ?? "", machine_type: w.machine_type ?? "", max_workers: String(w.max_workers ?? 1),
      section: w.section ?? "", available: w.available !== false })),
    wk: (p.workers ?? []).map((w) => ({ id: w.id, name: w.name ?? "", skills: join(w.skills), efficiency: String(w.efficiency ?? 1),
      assigned_station: w.assigned_station ?? "", available: w.available !== false })),
  };
}

export function toProblem(d: Draft): Problem {
  const keep = <T extends { id: string }>(rows: T[]) => rows.filter((r) => r.id.trim());
  return {
    name: d.name.trim() || "Gamme sans nom",
    target_cycle_time: num(d.cycle),
    operations: keep(d.ops).map((o) => ({ id: o.id.trim(), name: o.name.trim(), duration: num(o.duration) || 0, predecessors: list(o.predecessors),
      machine_type: o.machine_type.trim(), required_skills: list(o.skills), section: o.section.trim(), optional: o.optional, task_type: "VA" })),
    workstations: keep(d.ws).map((w) => ({ id: w.id.trim(), name: w.name.trim() || w.id.trim(), machine_type: w.machine_type.trim(),
      available: w.available, max_workers: Math.max(1, Math.round(num(w.max_workers)) || 1), section: w.section.trim() })),
    workers: keep(d.wk).map((w) => ({ id: w.id.trim(), name: w.name.trim() || w.id.trim(), skills: list(w.skills),
      efficiency: num(w.efficiency) > 0 ? num(w.efficiency) : 1, assigned_station: w.assigned_station.trim() || null, available: w.available })),
  };
}

export interface Check { errors: string[]; warnings: string[]; cells: Set<string> }

/** Contrôles immédiats côté navigateur (le diagnostic complet reste côté serveur). */
export function check(d: Draft): Check {
  const errors: string[] = [], warnings: string[] = [], cells = new Set<string>();
  const ops = d.ops.filter((o) => o.id.trim() || o.name.trim() || o.duration.trim());
  if (!(num(d.cycle) > 0)) errors.push("Indiquez une cadence cible (minutes par pièce).");
  if (!ops.length) errors.push("Ajoutez au moins une opération.");
  const seen = new Map<string, number>();
  ops.forEach((o, i) => {
    const id = o.id.trim();
    if (!id) { errors.push(`Ligne ${i + 1} : identifiant manquant.`); cells.add(`op:${i}:id`); return; }
    if (seen.has(id)) { errors.push(`${id} : identifiant en double.`); cells.add(`op:${i}:id`); }
    seen.set(id, i);
    if (!(num(o.duration) > 0)) { errors.push(`${id} : temps SAM manquant ou nul.`); cells.add(`op:${i}:duration`); }
  });
  ops.forEach((o, i) => {
    for (const p of list(o.predecessors)) {
      if (!seen.has(p)) { errors.push(`${o.id || "Ligne " + (i + 1)} : prédécesseur « ${p} » inconnu.`); cells.add(`op:${i}:predecessors`); }
      else if (p === o.id.trim()) { errors.push(`${o.id} : ne peut pas être son propre prédécesseur.`); cells.add(`op:${i}:predecessors`); }
    }
  });
  // boucle d'antériorité
  const graph = new Map(ops.map((o) => [o.id.trim(), list(o.predecessors)]));
  const state = new Map<string, number>();
  const visit = (n: string): boolean => {
    if (state.get(n) === 1) return true;
    if (state.get(n) === 2) return false;
    state.set(n, 1);
    for (const p of graph.get(n) ?? []) if (graph.has(p) && visit(p)) return true;
    state.set(n, 2); return false;
  };
  for (const n of graph.keys()) if (visit(n)) { errors.push("Les antériorités forment une boucle : vérifiez la colonne Prédécesseurs."); break; }

  const wsIds = new Set<string>();
  d.ws.forEach((w, i) => {
    const id = w.id.trim(); if (!id) return;
    if (wsIds.has(id)) { errors.push(`Poste ${id} : identifiant en double.`); cells.add(`ws:${i}:id`); }
    wsIds.add(id);
  });
  const wkIds = new Set<string>();
  d.wk.forEach((w, i) => {
    const id = w.id.trim(); if (!id) return;
    if (wkIds.has(id)) { errors.push(`Ouvrier ${id} : identifiant en double.`); cells.add(`wk:${i}:id`); }
    wkIds.add(id);
    if (w.assigned_station.trim() && !wsIds.has(w.assigned_station.trim())) {
      warnings.push(`Ouvrier ${id} : poste « ${w.assigned_station} » inconnu.`); cells.add(`wk:${i}:assigned_station`);
    }
  });
  const est = ops.filter((o) => o.est).length;
  if (est) warnings.push(`${est} temps ${est > 1 ? "proviennent" : "provient"} du catalogue (valeurs publiées, indicatives) : à confirmer par chronométrage dans votre atelier.`);
  if (wsIds.size) {
    const types = new Set(d.ws.filter((w) => w.available).map((w) => w.machine_type.trim()).filter(Boolean));
    const missing = [...new Set(ops.map((o) => o.machine_type.trim()).filter((m) => m && !types.has(m)))];
    if (missing.length) warnings.push(`Aucun poste disponible pour : ${missing.join(", ")}.`);
  }
  if (wkIds.size) {
    const have = new Set(d.wk.filter((w) => w.available).flatMap((w) => list(w.skills)));
    const missing = [...new Set(ops.flatMap((o) => list(o.skills)).filter((s) => !have.has(s)))];
    if (missing.length) warnings.push(`Aucun ouvrier disponible n'a la compétence : ${missing.join(", ")}.`);
    const avail = d.wk.filter((w) => w.available).map((w) => new Set(list(w.skills)));
    const combo = ops.filter((o) => list(o.skills).length > 1 && list(o.skills).every((s) => have.has(s)) && !avail.some((w) => list(o.skills).every((s) => w.has(s))));
    if (combo.length) warnings.push(`Aucun ouvrier ne cumule toutes les compétences de : ${combo.map((o) => o.id).join(", ")} (le calcul exige un même ouvrier).`);
  }
  return { errors, warnings, cells };
}

/** Lignes collées depuis Excel (tabulations), dans l'ordre des colonnes du tableau. */
export function parsePasted(text: string): string[][] {
  return text.replace(/\r/g, "").split("\n").filter((l) => l.trim()).map((l) => l.split("\t").map((c) => c.trim()));
}
const yes = (s: string | undefined, dflt: boolean) => (s === undefined || s === "" ? dflt : /^(1|true|vrai|oui|yes|x)$/i.test(s));
const isHeader = (r: string[]) => r[0] !== undefined && /id|code|n°|num/i.test(r[0]) && !/\d/.test(r[0]);
export const pasteOps = (rows: string[][]): OpRow[] => rows.filter((r) => !isHeader(r)).map((r) => ({
  id: r[0] ?? "", name: r[1] ?? "", duration: r[2] ?? "", predecessors: r[3] ?? "", machine_type: r[4] ?? "", skills: r[5] ?? "", section: r[6] ?? "", optional: yes(r[7], false) }));
export const pasteWs = (rows: string[][]): WsRow[] => rows.filter((r) => !isHeader(r)).map((r) => ({
  id: r[0] ?? "", name: r[1] ?? "", machine_type: r[2] ?? "", max_workers: r[3] || "1", section: r[4] ?? "", available: yes(r[5], true) }));
export const pasteWk = (rows: string[][]): WkRow[] => rows.filter((r) => !isHeader(r)).map((r) => ({
  id: r[0] ?? "", name: r[1] ?? "", skills: r[2] ?? "", efficiency: r[3] || "1", assigned_station: r[4] ?? "", available: yes(r[5], true) }));
