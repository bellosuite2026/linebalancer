// Icônes d'état et de rôle de la simulation, dessinées au canvas (aucune image externe, aucune police
// d'emoji) : utilisées telles quelles par la vue 2D et comme textures des bulles de la vue 3D.
import { MACHINE_CATALOG } from "./workshop";
import type { DesModel, DesStation } from "./des";

export type Bubble = "wait" | "break" | "setup" | "down";
export type Role = "operatrice" | "liaison" | "controleuse" | "mecanicien";
export type SimStyle = "simple" | "detailed";

export const ROLE_LABEL: Record<Role, string> = { operatrice: "Opératrice", liaison: "Agent de liaison", controleuse: "Contrôleuse", mecanicien: "Mécanicien" };
export const ROLE_COLOR: Record<Role, string> = { operatrice: "#2f7fa6", liaison: "#e67e22", controleuse: "#8e44ad", mecanicien: "#34495e" };
export const BUBBLE_LABEL: Record<Bubble, string> = { wait: "En attente", break: "Pause", setup: "Mise en route", down: "Panne (mécanicien)" };
const BUBBLE_RING: Record<Bubble, string> = { wait: "#f08a24", break: "#7f8c8d", setup: "#3b7dd8", down: "#d64541" };

const STYLE_KEY = "tlb.sim.style";
export function loadStyle(): SimStyle { try { return localStorage.getItem(STYLE_KEY) === "simple" ? "simple" : "detailed"; } catch { return "detailed"; } }
export function saveStyle(s: SimStyle) { try { localStorage.setItem(STYLE_KEY, s); } catch { /* stockage indisponible */ } }

/** Poste assis (machine à coudre) ou debout (table, repassage, contrôle, coupe…). */
export function isSeated(st: DesStation | undefined): boolean {
  if (!st) return false;
  const shape = st.machine ? MACHINE_CATALOG[st.machine]?.shape ?? "" : "";
  if (shape) return shape.startsWith("sew_");
  return /piq|surjet|recouvr|point|boutonn|bride|coud|sew|overlock|plate|zigzag/i.test(st.machine_type || "");
}
export function isInspection(st: DesStation | undefined): boolean {
  if (!st) return false;
  const cat = st.machine ? MACHINE_CATALOG[st.machine]?.category : "";
  return cat === "controle" || /contr[ôo]l|inspect|visite|v[ée]rif/i.test(`${st.label} ${st.machine_type} ${(st.operations || []).join(" ")}`);
}

/** Rôle et poste principal de chaque opérateur du modèle. */
export function operatorRoles(model: DesModel): Map<string, { role: Role; station?: DesStation }> {
  const byId = new Map(model.stations.map((s) => [s.id, s]));
  const out = new Map<string, { role: Role; station?: DesStation }>();
  for (const o of model.operators ?? []) {
    const st = byId.get(o.stations?.[0]);
    out.set(o.id, { role: isInspection(st) ? "controleuse" : "operatrice", station: st });
  }
  for (const s of model.stations) for (const id of s.operators ?? []) if (!out.has(id)) out.set(id, { role: isInspection(s) ? "controleuse" : "operatrice", station: s });
  return out;
}

const cache = new Map<string, HTMLCanvasElement>();
/** Bulle ronde (blanche, liseré coloré, pointe vers le bas) avec son pictogramme, 128×128 px. */
export function bubbleCanvas(kind: Bubble): HTMLCanvasElement {
  const key = `b:${kind}`; const hit = cache.get(key); if (hit) return hit;
  const c = document.createElement("canvas"); c.width = c.height = 128;
  const g = c.getContext("2d")!; const ring = BUBBLE_RING[kind];
  g.fillStyle = "#ffffff"; g.strokeStyle = ring; g.lineWidth = 8;
  g.beginPath(); g.arc(64, 56, 46, 0, Math.PI * 2); g.fill(); g.stroke();
  g.beginPath(); g.moveTo(52, 98); g.lineTo(64, 122); g.lineTo(76, 98); g.closePath(); g.fillStyle = ring; g.fill();
  g.fillStyle = ring; g.strokeStyle = ring; g.lineCap = "round"; g.lineJoin = "round";
  if (kind === "wait") {             // sablier
    g.lineWidth = 6; g.beginPath(); g.moveTo(42, 30); g.lineTo(86, 30); g.moveTo(42, 82); g.lineTo(86, 82); g.stroke();
    g.beginPath(); g.moveTo(47, 34); g.lineTo(81, 34); g.lineTo(64, 56); g.closePath(); g.fill();
    g.globalAlpha = 0.45; g.beginPath(); g.moveTo(64, 56); g.lineTo(81, 78); g.lineTo(47, 78); g.closePath(); g.fill(); g.globalAlpha = 1;
  } else if (kind === "break") {     // tasse fumante
    g.fillRect(40, 50, 38, 30); g.lineWidth = 6; g.beginPath(); g.arc(80, 64, 9, -Math.PI / 2, Math.PI / 2); g.stroke();
    g.lineWidth = 4; for (const x of [50, 60, 70]) { g.beginPath(); g.moveTo(x, 44); g.quadraticCurveTo(x - 6, 36, x, 28); g.stroke(); }
  } else if (kind === "setup") {     // engrenage
    g.save(); g.translate(64, 56);
    for (let i = 0; i < 8; i++) { g.rotate(Math.PI / 4); g.fillRect(-6, -30, 12, 12); }
    g.beginPath(); g.arc(0, 0, 21, 0, Math.PI * 2); g.fill();
    g.fillStyle = "#fff"; g.beginPath(); g.arc(0, 0, 8, 0, Math.PI * 2); g.fill(); g.restore();
  } else {                           // clé plate (panne)
    g.save(); g.translate(64, 56); g.rotate(-Math.PI / 4);
    g.fillRect(-6, -8, 12, 40);
    g.beginPath(); g.arc(0, -16, 15, 0, Math.PI * 2); g.fill();
    g.fillStyle = "#fff"; g.fillRect(-5, -34, 10, 18); g.restore();
  }
  cache.set(key, c); return c;
}

/** Pictogramme de rôle vu de dessus pour la vue 2D (silhouette tête + épaules orientée). */
export function drawPerson2D(g: CanvasRenderingContext2D, x: number, y: number, r: number, heading: number, role: Role, stateColor: string, carrying = false) {
  g.save(); g.translate(x, y); g.rotate(heading);
  // épaules (ellipse perpendiculaire au regard) couleur du rôle, liseré = état
  g.beginPath(); g.ellipse(0, 0, r * 0.62, r * 1.05, 0, 0, Math.PI * 2);
  g.fillStyle = ROLE_COLOR[role]; g.fill(); g.lineWidth = Math.max(1.5, r * 0.28); g.strokeStyle = stateColor; g.stroke();
  if (carrying) { g.fillStyle = "#f4e2b8"; g.fillRect(r * 0.55, -r * 0.55, r * 0.7, r * 1.1); }
  g.beginPath(); g.arc(r * 0.12, 0, r * 0.46, 0, Math.PI * 2); g.fillStyle = "#d9aa87"; g.fill();
  g.beginPath(); g.arc(-r * 0.05, 0, r * 0.4, Math.PI * 0.5, Math.PI * 1.5); g.fillStyle = role === "mecanicien" ? "#1f2a37" : "#3b2a20"; g.fill();
  g.restore();
  if (role === "controleuse") {      // petit ✓
    g.save(); g.strokeStyle = "#fff"; g.lineWidth = Math.max(1.2, r * 0.22); g.lineCap = "round";
    g.beginPath(); g.moveTo(x + r * 0.7, y - r * 1.05); g.lineTo(x + r * 0.95, y - r * 0.8); g.lineTo(x + r * 1.4, y - r * 1.35); g.stroke();
    g.strokeStyle = ROLE_COLOR.controleuse; g.lineWidth = Math.max(0.8, r * 0.12); g.stroke(); g.restore();
  }
}
