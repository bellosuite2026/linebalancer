// Modèles 3D paramétriques légers de la bibliothèque de machines (boîtes et cylindres partagés).
// Repère local : x le long de la table (w), z en profondeur (d, opératrice côté +z), y vers le haut.
import * as THREE from "three";
import { MACHINE_CATALOG } from "./workshop";

export const TABLE_H = 0.76;
const BOX = new THREE.BoxGeometry(1, 1, 1);
const CYL = new THREE.CylinderGeometry(0.5, 0.5, 1, 14);
const SPH = new THREE.SphereGeometry(0.5, 14, 10);
const mats = new Map<string, THREE.MeshStandardMaterial>();
export function mat(color: string, metal = 0.08, rough = 0.7) {
  const k = `${color}|${metal}|${rough}`;
  let m = mats.get(k);
  if (!m) { m = new THREE.MeshStandardMaterial({ color, metalness: metal, roughness: rough }); mats.set(k, m); }
  return m;
}
const STEEL = "#58656b", HEAD = "#8eaaa8", DARK = "#3e474d", CREAM = "#e2e4df", WOOD = "#c9a66b";

function box(g: THREE.Object3D, sx: number, sy: number, sz: number, x: number, y: number, z: number, color: string, metal = 0.08) {
  const m = new THREE.Mesh(BOX, mat(color, metal));
  m.scale.set(sx, sy, sz); m.position.set(x, y, z); m.castShadow = true; m.receiveShadow = true; m.userData.shared = true;
  g.add(m); return m;
}
function cyl(g: THREE.Object3D, r: number, h: number, x: number, y: number, z: number, color: string, axis: "y" | "x" | "z" = "y") {
  const m = new THREE.Mesh(CYL, mat(color, 0.2, 0.5));
  m.scale.set(r * 2, h, r * 2); m.position.set(x, y, z);
  if (axis === "x") m.rotation.z = Math.PI / 2;
  if (axis === "z") m.rotation.x = Math.PI / 2;
  m.userData.shared = true;
  m.castShadow = true; g.add(m); return m;
}
function legs(g: THREE.Object3D, w: number, d: number, h = TABLE_H) {
  const lx = Math.max(0.06, w / 2 - 0.08), lz = Math.max(0.06, d / 2 - 0.07);
  for (const x of [-lx, lx]) for (const z of [-lz, lz]) box(g, 0.05, h, 0.05, x, h / 2, z, STEEL, 0.3);
}
function table(g: THREE.Object3D, w: number, d: number, topColor: string, h = TABLE_H) {
  legs(g, w, d, h);
  return box(g, w, 0.05, d, 0, h, 0, topColor);
}

/** Ajoute le modèle de la machine au groupe et renvoie la pièce colorable (plateau). */
export function addMachineBody(g: THREE.Group, type: string, w: number, d: number, status: string = "service"): THREE.Mesh {
  const def = MACHINE_CATALOG[type];
  const shape = def?.shape ?? "table";
  const h = def?.h ?? 1.2;
  const topColor = status === "panne" ? "#b94b3d" : status === "reserve" ? "#aeb4b6" : CREAM;
  const hx = w / 2 - 0.3, hz = -d / 2 + 0.2;           // tête : à droite, vers l'arrière
  let top: THREE.Mesh;
  const sewHead = (bed: "flat" | "post" | "arm" | "overlock" | "auto") => {
    const y0 = TABLE_H + 0.025;
    if (bed === "overlock") {
      box(g, 0.3, 0.3, 0.26, hx, y0 + 0.15, hz + 0.05, HEAD);
      box(g, 0.08, 0.05, 0.1, hx - 0.18, y0 + 0.03, hz + 0.18, STEEL, 0.4);
      return;
    }
    if (bed === "auto") {
      box(g, 0.4, 0.42, 0.34, hx, y0 + 0.21, hz + 0.05, HEAD);
      box(g, 0.24, 0.04, 0.18, hx - 0.12, y0 + 0.05, hz + 0.3, STEEL, 0.4);
      box(g, 0.2, 0.2, 0.12, -w / 2 + 0.25, y0 + 0.1, hz, DARK);   // pupitre
      return;
    }
    const lift = bed === "post" ? 0.22 : bed === "arm" ? 0.12 : 0;
    if (bed === "post") cyl(g, 0.05, 0.22, hx - 0.28, y0 + 0.11, hz + 0.22, STEEL);
    if (bed === "arm") box(g, 0.5, 0.11, 0.11, hx - 0.1, y0 + 0.06, hz + 0.22, HEAD);
    box(g, 0.14, 0.32 + lift, 0.18, hx + 0.12, y0 + (0.32 + lift) / 2, hz, HEAD);        // colonne
    box(g, 0.48, 0.12, 0.16, hx - 0.06, y0 + 0.3 + lift, hz + 0.02, HEAD);               // bras
    box(g, 0.1, 0.2, 0.14, hx - 0.28, y0 + 0.2 + lift, hz + 0.05, HEAD);                 // tête d'aiguille
    cyl(g, 0.07, 0.04, hx + 0.21, y0 + 0.28 + lift, hz, STEEL, "x");                     // volant
    cyl(g, 0.012, 0.25, hx + 0.05, y0 + 0.55 + lift, hz - 0.05, "#c8c8c8");              // porte-bobines
  };
  switch (shape) {
    case "sew_flat": top = table(g, w, d, topColor); sewHead("flat"); box(g, 0.25, 0.14, 0.2, hx, TABLE_H - 0.12, 0, DARK); break;
    case "sew_post": top = table(g, w, d, topColor); sewHead("post"); break;
    case "sew_arm": top = table(g, w, d, topColor); sewHead("arm"); break;
    case "sew_overlock": top = table(g, w, d, topColor); sewHead("overlock"); break;
    case "sew_auto": top = table(g, w, d, topColor); sewHead("auto"); break;
    case "sew_station": top = table(g, w, d, topColor); sewHead("auto"); box(g, w * 0.55, 0.02, d * 0.6, -w * 0.15, TABLE_H + 0.04, 0, "#b9c3c9"); break;
    case "cutting_table": {
      top = box(g, w, 0.06, d, 0, 0.9, 0, topColor);
      for (let x = -w / 2 + 0.1; x <= w / 2 - 0.05; x += Math.max(1, w / Math.ceil(w / 1.5))) for (const z of [-d / 2 + 0.08, d / 2 - 0.08]) box(g, 0.06, 0.9, 0.06, x, 0.45, z, STEEL, 0.3);
      box(g, w * 0.7, 0.03, d * 0.8, -w * 0.05, 0.945, 0, "#c7d6e6");     // matelas de tissu
      break;
    }
    case "spreader":
      top = box(g, w, 0.12, d, 0, 1.0, 0, "#d6dadd");
      cyl(g, 0.2, d * 0.9, 0, 1.25, 0, "#5f86b3", "z");
      for (const x of [-w / 2 + 0.1, w / 2 - 0.1]) box(g, 0.08, 1.0, d, x, 0.5, 0, STEEL, 0.3);
      break;
    case "cutter_cad":
      top = box(g, w, 0.08, d, 0, 0.82, 0, topColor);
      box(g, w, 0.78, d * 0.9, 0, 0.39, 0, "#d9dcd8");
      box(g, 0.25, 0.35, d, w * 0.1, 1.05, 0, "#2f5f8f");                // portique
      box(g, 0.3, 0.3, 0.3, w * 0.1, 0.95, 0, DARK);
      break;
    case "bandknife":
      top = box(g, w, 0.05, d, 0, 0.9, 0, topColor);
      box(g, w * 0.9, 0.85, d * 0.9, 0, 0.43, 0, "#cfd4d6");
      box(g, 0.2, 0.9, 0.2, w * 0.35, 1.35, -d * 0.3, "#d6612a");
      box(g, 0.6, 0.15, 0.2, w * 0.1, 1.75, -d * 0.3, "#d6612a");
      break;
    case "fusing":
      top = box(g, w, 0.06, d, 0, 0.85, 0, topColor);
      box(g, w * 0.5, 0.4, d, 0, 1.05, 0, "#c0453a");
      box(g, w, 0.82, d * 0.85, 0, 0.41, 0, "#d7d9d7");
      break;
    case "ironing": {
      legs(g, w * 0.6, d * 0.8, 0.9);
      top = box(g, w * 0.85, 0.06, d * 0.7, -w * 0.05, 0.92, 0, topColor);
      const nose = new THREE.Mesh(CYL, mat(topColor)); nose.scale.set(d * 0.7, 0.06, d * 0.7); nose.position.set(w * 0.35, 0.92, 0); nose.userData.shared = true; g.add(nose);
      box(g, 0.25, 0.08, 0.12, -w * 0.2, 1.0, 0, "#c8c8c8", 0.5);         // fer
      box(g, 0.05, 1.1, 0.05, -w / 2 + 0.05, 1.45, -d * 0.4, STEEL);     // potence
      box(g, w * 0.4, 0.4, d * 0.6, -w * 0.15, 0.4, 0, "#7d8992");        // aspiration
      break;
    }
    case "mannequin":
      top = box(g, w * 0.8, 0.3, d * 0.8, 0, 0.15, 0, "#7d8992");
      cyl(g, 0.05, 0.7, 0, 0.65, 0, STEEL);
      { const t = new THREE.Mesh(SPH, mat("#e8e4da")); t.scale.set(0.45, 0.75, 0.3); t.position.set(0, 1.4, 0); t.userData.shared = true; g.add(t); }
      box(g, 0.5, 0.06, 0.06, 0, 1.72, 0, "#e8e4da");
      break;
    case "press":
      top = box(g, w * 0.8, 0.08, d * 0.55, 0, 0.95, d * 0.1, topColor);
      box(g, w * 0.9, 0.9, d * 0.6, 0, 0.45, d * 0.05, "#9aa4aa");
      box(g, w * 0.75, 0.12, d * 0.5, 0, 1.25, d * 0.05, "#b9c3c9");
      box(g, 0.2, 0.5, 0.2, 0, 1.15, -d * 0.35, DARK);
      break;
    case "inspection":
      top = table(g, w, d, "#f2f2ee", 0.9);
      box(g, 0.04, 0.8, 0.04, -w / 2 + 0.05, 1.3, -d / 2 + 0.05, STEEL);
      box(g, w * 0.9, 0.04, 0.08, 0, 1.7, -d / 2 + 0.05, "#f4e58a");
      break;
    case "detector":
      top = box(g, w, 0.05, d * 0.6, 0, 0.8, 0, "#2b2f33");
      box(g, w, 0.75, d * 0.6, 0, 0.38, 0, "#cfd4d6");
      box(g, 0.5, 0.45, d, 0, 1.0, 0, "#3b7dd8");
      box(g, 0.42, 0.22, d * 1.02, 0, 0.93, 0, "#20262b");
      break;
    case "packing":
      top = table(g, w, d, "#e9e4d6", 0.85);
      box(g, 0.35, 0.25, 0.3, w * 0.25, 1.0, 0, WOOD);
      box(g, 0.3, 0.2, 0.25, w * 0.25, 1.22, 0, WOOD);
      box(g, 0.2, 0.15, 0.15, -w * 0.3, 0.95, -d * 0.2, DARK);
      break;
    case "rack":
      for (const x of [-w / 2 + 0.03, w / 2 - 0.03]) for (const z of [-d / 2 + 0.03, d / 2 - 0.03]) box(g, 0.04, h, 0.04, x, h / 2, z, STEEL, 0.3);
      top = box(g, w, 0.03, d, 0, h * 0.95, 0, "#a9b3b8");
      for (const y of [0.15, h * 0.4, h * 0.67]) box(g, w, 0.03, d, 0, y, 0, "#a9b3b8");
      break;
    case "cart":
      top = box(g, w, 0.04, d, 0, 0.75, 0, "#d8cfb8");
      box(g, w, 0.03, d, 0, 0.25, 0, "#d8cfb8");
      for (const x of [-w / 2 + 0.04, w / 2 - 0.04]) for (const z of [-d / 2 + 0.04, d / 2 - 0.04]) { box(g, 0.03, 0.72, 0.03, x, 0.42, z, STEEL); cyl(g, 0.05, 0.03, x, 0.05, z, DARK, "x"); }
      box(g, 0.03, 0.25, d, -w / 2, 1.0, 0, STEEL);
      break;
    case "conveyor":
      top = box(g, w, 0.06, 0.12, 0, 2.15, 0, "#4f5b62");
      for (const x of [-w / 2 + 0.05, w / 2 - 0.05]) box(g, 0.08, 2.15, 0.08, x, 1.07, -d / 2 + 0.06, STEEL, 0.3);
      for (const x of [-0.3, 0, 0.3]) { box(g, 0.02, 0.5, 0.02, x * w, 1.85, 0, STEEL); box(g, 0.3, 0.02, 0.2, x * w, 1.6, 0, "#5f86b3"); }
      table(g, w * 0.8, d * 0.6, CREAM);
      break;
    case "pallet":
      top = box(g, w, 0.04, d, 0, 0.14, 0, WOOD);
      for (const z of [-d / 2 + 0.05, 0, d / 2 - 0.05]) box(g, w, 0.1, 0.1, 0, 0.06, z, "#a8864f");
      for (const [x, z] of [[-0.3, -0.2], [0.3, -0.2], [-0.3, 0.2], [0.3, 0.2]]) box(g, 0.55, Math.max(0.2, h - 0.2) * 0.5, 0.38, x * w, 0.16 + (h - 0.2) * 0.25, z * d, WOOD);
      break;
    default:
      top = table(g, w, d, topColor);
  }
  return top;
}

/** Détails du style « détaillé » : cônes de fil, lampe, pédale, tiroir, bac de pièces (machines à coudre),
 *  fer et centrale vapeur (repassage), table lumineuse (contrôle). Même repère que addMachineBody. */
export function addMachineDetails(g: THREE.Group, type: string, w: number, d: number) {
  const shape = MACHINE_CATALOG[type]?.shape ?? (type === "piqueuse_plate" ? "sew_flat" : "");
  const y0 = TABLE_H + 0.025, hx = w / 2 - 0.3, hz = -d / 2 + 0.2;
  if (shape.startsWith("sew_")) {
    const cones = ["#d64541", "#f4f1ea", "#2c3e50", "#e8c547"];
    const n = shape === "sew_overlock" ? 4 : 2;
    box(g, 0.02, 0.5, 0.02, hx + 0.05, y0 + 0.25, -d / 2 + 0.05, "#c8c8c8");
    for (let i = 0; i < n; i++) {
      const c = new THREE.Mesh(new THREE.CylinderGeometry(0.025, 0.045, 0.11, 8), mat(cones[i % cones.length]));
      c.position.set(hx - 0.05 + i * 0.07, y0 + 0.06, -d / 2 + 0.06); c.castShadow = true; g.add(c);
    }
    box(g, 0.015, 0.3, 0.015, hx - 0.38, y0 + 0.15, hz - 0.05, DARK);                // bras de lampe
    box(g, 0.14, 0.03, 0.05, hx - 0.33, y0 + 0.3, hz + 0.02, "#f7f3d6");             // lampe LED
    box(g, 0.24, 0.05, 0.14, 0.05, 0.05, d / 2 - 0.15, DARK);                         // pédale
    box(g, 0.36, 0.12, Math.max(0.2, d - 0.2), -w / 2 + 0.3, TABLE_H - 0.1, 0, WOOD); // tiroir
    box(g, 0.3, 0.08, 0.22, -w / 2 + 0.25, y0 + 0.04, 0.02, "#6f7780");              // bac de pièces
    box(g, 0.26, 0.05, 0.18, -w / 2 + 0.25, y0 + 0.1, 0.02, "#5b95e0");              // pièces en attente
  } else if (shape === "ironing") {
    box(g, 0.2, 0.08, 0.1, 0.1, y0 + 0.08, 0.05, "#b8455a");
    box(g, 0.3, 0.3, 0.25, -w / 2 + 0.25, 0.15, -d / 2 + 0.2, "#e2e4df");
  } else if (shape === "inspection") {
    box(g, Math.min(0.9, w * 0.7), 0.02, Math.min(0.5, d * 0.6), 0, y0 + 0.02, 0, "#fdfbe8");
    box(g, 0.02, 0.6, 0.02, -w / 2 + 0.1, y0 + 0.3, -d / 2 + 0.1, DARK);
    box(g, 0.6, 0.03, 0.08, -w / 2 + 0.38, y0 + 0.6, -d / 2 + 0.12, "#f7f3d6");
  }
}
