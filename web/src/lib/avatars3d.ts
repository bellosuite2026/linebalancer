// Ouvriers low-poly procéduraux de la vue 3D (style « détaillé ») : chaque partie du corps est un
// InstancedMesh partagé par tous les personnages (≈ 14 appels de dessin quel que soit l'effectif).
// Modèles entièrement générés par le code (boîtes, cylindres, icosaèdres) : aucune ressource externe,
// aucune licence tierce. Chargé à la demande (chunk séparé) seulement quand le style détaillé est choisi.
//
// Repère local d'un personnage : x = devant, y = haut, z = côté ; pieds en y = 0.
import * as THREE from "three";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import { bubbleCanvas, ROLE_COLOR, type Bubble, type Role } from "./simIcons";

export type Pose = "idle" | "walk" | "sew" | "stand_work" | "carry" | "push" | "wait" | "break" | "repair";

const SKIN = ["#e0b08c", "#c98f68", "#a8714f", "#f0c8a8"];
const HAIR = ["#2b1d14", "#4a3020", "#151515", "#6b4a2b", "#8a6b4a"];
const PANTS = ["#2c3e50", "#3d4b5c", "#4b3b47", "#2f4a3a"];

const THIGH = 0.43, SHIN = 0.42, ARM = 0.56, HIP_Y = 0.86;

interface PoseParams { hipY: number; lean: number; tl: number; sl: number; tr: number; sr: number; al: number; ar: number; head: number }

function pose(p: Pose, ph: number): PoseParams {
  const s = Math.sin(ph), c = Math.cos(ph);
  switch (p) {
    case "walk": return { hipY: HIP_Y + Math.abs(c) * 0.03, lean: 0.04, tl: 0.5 * s, sl: Math.min(0, -0.6 * c) + 0.1 * s, tr: -0.5 * s, sr: Math.min(0, 0.6 * c) - 0.1 * s, al: -0.45 * s, ar: 0.45 * s, head: 0 };
    case "carry": return { hipY: HIP_Y + Math.abs(c) * 0.025, lean: 0.02, tl: 0.42 * s, sl: Math.min(0, -0.5 * c), tr: -0.42 * s, sr: Math.min(0, 0.5 * c), al: 1.15, ar: 1.15, head: 0 };
    case "push": return { hipY: HIP_Y - 0.02 + Math.abs(c) * 0.02, lean: 0.22, tl: 0.38 * s, sl: Math.min(0, -0.5 * c), tr: -0.38 * s, sr: Math.min(0, 0.5 * c), al: 1.25, ar: 1.25, head: -0.15 };
    case "sew": return { hipY: 0.5, lean: 0.12, tl: 1.5, sl: -1.45, tr: 1.5, sr: -1.45, al: 1.05 + 0.08 * s, ar: 1.0 - 0.08 * Math.sin(ph * 1.3), head: 0.25 };
    case "stand_work": return { hipY: HIP_Y, lean: 0.16, tl: 0.03, sl: 0, tr: -0.03, sr: 0, al: 0.95 + 0.12 * s, ar: 0.85 - 0.12 * s, head: 0.3 };
    case "repair": return { hipY: 0.52, lean: 0.35, tl: 1.5, sl: -1.5, tr: -0.15, sr: -1.4, al: 1.3 + 0.25 * s, ar: 1.0, head: 0.2 };
    case "break": return { hipY: 0.5, lean: -0.08, tl: 1.45, sl: -1.35, tr: 1.45, sr: -1.35, al: 0.15, ar: 0.6, head: -0.1 };
    case "wait": return { hipY: HIP_Y, lean: 0.02 * s, tl: 0.02, sl: 0, tr: -0.06, sr: 0, al: -0.25, ar: -0.25, head: 0.15 * Math.sin(ph * 0.5) };
    default: return { hipY: HIP_Y, lean: 0, tl: 0, sl: 0, tr: 0, sr: 0, al: 0.05, ar: 0.05, head: 0 };
  }
}

function geo(g: THREE.BufferGeometry, ty = 0): THREE.BufferGeometry { g.translate(0, ty, 0); return g; }

/** Foule de personnages : begin(), add(...) pour chacun, end(). */
export class AvatarCrowd {
  private parts: Record<string, THREE.InstancedMesh> = {};
  private n = 0;
  private bubbles: Record<Bubble, { mesh: THREE.InstancedMesh; pos: THREE.Vector3[] }>;
  private m = new THREE.Matrix4(); private a = new THREE.Matrix4(); private b = new THREE.Matrix4(); private u = new THREE.Matrix4();
  private col = new THREE.Color();
  private q = new THREE.Quaternion(); private one = new THREE.Vector3(1, 1, 1); private v = new THREE.Vector3();
  readonly group = new THREE.Group();

  constructor(private max: number) {
    const std = (rough = 0.85) => new THREE.MeshStandardMaterial({ color: "#ffffff", roughness: rough, flatShading: true });
    const mk = (name: string, g: THREE.BufferGeometry, cap = max) => {
      const im = new THREE.InstancedMesh(g, std(), cap); im.castShadow = true; im.count = 0; im.frustumCulled = false;
      for (let i = 0; i < cap; i++) im.setColorAt(i, new THREE.Color("#ffffff"));
      this.parts[name] = im; this.group.add(im);
    };
    const torso = new THREE.CylinderGeometry(0.16, 0.14, 0.5, 6); torso.scale(0.72, 1, 1); geo(torso, 0.27);
    mk("torso", torso);
    mk("pelvis", geo(new THREE.BoxGeometry(0.17, 0.15, 0.3)));
    mk("head", new THREE.IcosahedronGeometry(0.11, 1));
    const hair = new THREE.SphereGeometry(0.118, 8, 5, 0, Math.PI * 2, 0, Math.PI * 0.55); hair.translate(-0.012, 0.012, 0);
    mk("hair", hair);
    const bun = new THREE.IcosahedronGeometry(0.055, 0); bun.translate(-0.11, 0.03, 0);
    mk("bun", bun);
    const cap = new THREE.CylinderGeometry(0.12, 0.12, 0.06, 10); cap.translate(0, 0.07, 0);
    const brim = new THREE.BoxGeometry(0.12, 0.015, 0.16); brim.translate(0.12, 0.045, 0);
    mk("cap", mergeGeometries([cap, brim])!);
    mk("thigh", geo(new THREE.BoxGeometry(0.11, THIGH, 0.12), -THIGH / 2), max * 2);
    const shin = new THREE.BoxGeometry(0.095, SHIN, 0.1); shin.translate(0, -SHIN / 2, 0);
    const shoe = new THREE.BoxGeometry(0.2, 0.06, 0.1); shoe.translate(0.05, -SHIN - 0.01, 0);
    mk("shin", mergeGeometries([shin.toNonIndexed(), shoe.toNonIndexed()])!, max * 2);
    const arm = new THREE.BoxGeometry(0.075, ARM, 0.075); arm.translate(0, -ARM / 2, 0);
    const hand = new THREE.IcosahedronGeometry(0.042, 0); hand.translate(0, -ARM - 0.02, 0);
    mk("arm", arm, max * 2); mk("hand", hand, max * 2);
    const apron = new THREE.BoxGeometry(0.02, 0.5, 0.26); apron.translate(0.125, 0.12, 0);
    mk("apron", apron);
    const clip = new THREE.BoxGeometry(0.02, 0.24, 0.18); mk("clip", clip);
    const tb = new THREE.BoxGeometry(0.36, 0.17, 0.18); tb.translate(0, 0.085, 0);
    const handle = new THREE.BoxGeometry(0.2, 0.03, 0.03); handle.translate(0, 0.2, 0);
    mk("toolbox", mergeGeometries([tb.toNonIndexed(), handle.toNonIndexed()])!);
    const seat = new THREE.CylinderGeometry(0.18, 0.18, 0.05, 12); seat.translate(0, 0.46, 0);
    const post = new THREE.CylinderGeometry(0.025, 0.025, 0.44, 6); post.translate(0, 0.22, 0);
    const foot = new THREE.CylinderGeometry(0.2, 0.22, 0.03, 10); foot.translate(0, 0.015, 0);
    mk("stool", mergeGeometries([seat.toNonIndexed(), post.toNonIndexed(), foot.toNonIndexed()])!);
    // bulles d'état (toujours face caméra, au-dessus de tout)
    const plane = new THREE.PlaneGeometry(0.55, 0.55);
    const mkB = (k: Bubble) => {
      const tex = new THREE.CanvasTexture(bubbleCanvas(k)); tex.colorSpace = THREE.SRGBColorSpace;
      const mesh = new THREE.InstancedMesh(plane, new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthTest: false }), max);
      mesh.count = 0; mesh.renderOrder = 10; mesh.frustumCulled = false; this.group.add(mesh);
      return { mesh, pos: [] as THREE.Vector3[] };
    };
    this.bubbles = { wait: mkB("wait"), break: mkB("break"), setup: mkB("setup"), down: mkB("down") };
  }

  begin() { this.n = 0; for (const k of Object.keys(this.parts)) this.parts[k].count = 0; for (const b of Object.values(this.bubbles)) b.pos.length = 0; }

  private put(name: string, mat: THREE.Matrix4, color: string) {
    const im = this.parts[name]; const i = im.count; if (i >= im.instanceMatrix.count) return;
    im.setMatrixAt(i, mat); im.setColorAt(i, this.col.set(color)); im.count = i + 1;
  }

  bubble(kind: Bubble, x: number, y: number, z: number) { const b = this.bubbles[kind]; if (b.pos.length < this.max) b.pos.push(new THREE.Vector3(x, y, z)); }

  /** Ajoute un personnage. heading : angle dans le plan (même convention que la vue 2D). seed : variété stable. */
  add(x: number, z: number, heading: number, role: Role, p: Pose, phase: number, seed: number) {
    if (this.n >= this.max) return; this.n++;
    const P = pose(p, phase);
    const skin = SKIN[seed % SKIN.length], hair = HAIR[(seed >> 2) % HAIR.length], pants = PANTS[(seed >> 3) % PANTS.length];
    const shirt = ROLE_COLOR[role];
    const root = this.m.makeRotationY(-heading).setPosition(x, 0, z);
    if (p === "sew" || p === "break") this.put("stool", this.a.copy(root).multiply(this.b.makeTranslation(-0.05, 0, 0)), "#3e474d");
    // bassin + jambes
    const hip = this.u.copy(root).multiply(this.b.makeTranslation(0, P.hipY, 0));
    this.put("pelvis", hip, pants);
    const leg = (side: number, t: number, s: number) => {
      const th = this.a.copy(hip).multiply(this.b.makeTranslation(0, 0, side * 0.08)).multiply(this.b.makeRotationZ(t));
      this.put("thigh", th, pants);
      const sh = th.multiply(this.b.makeTranslation(0, -THIGH, 0)).multiply(this.b.makeRotationZ(s));
      this.put("shin", sh, "#2a2a2a");
    };
    leg(1, P.tl, P.sl); leg(-1, P.tr, P.sr);
    // haut du corps penché autour de la hanche
    const up = new THREE.Matrix4().copy(hip).multiply(this.b.makeRotationZ(-P.lean));
    this.put("torso", up, shirt);
    if (role === "operatrice" || role === "controleuse") this.put("apron", up, role === "controleuse" ? "#f4f1ea" : "#dfe9ee");
    const arm = (side: number, ang: number) => {
      const am = this.a.copy(up).multiply(this.b.makeTranslation(0, 0.5, side * 0.2)).multiply(this.b.makeRotationZ(ang)).multiply(this.b.makeRotationX(side * -0.08));
      this.put("arm", am, shirt); this.put("hand", am, skin);
      if (role === "controleuse" && side === 1 && (p === "stand_work" || p === "idle" || p === "wait"))
        this.put("clip", this.a.copy(am).multiply(this.b.makeTranslation(0.06, -ARM, 0)), "#7a5230");
    };
    arm(1, P.al); arm(-1, P.ar);
    const hd = this.a.copy(up).multiply(this.b.makeTranslation(0.01, 0.67, 0)).multiply(this.b.makeRotationZ(-P.head));
    this.put("head", hd, skin);
    if (role === "mecanicien" || role === "liaison") this.put("cap", hd, role === "mecanicien" ? "#c0392b" : "#f39c12");
    else { this.put("hair", hd, hair); this.put("bun", hd, hair); }
    if (role === "mecanicien") this.put("toolbox", this.a.copy(root).multiply(this.b.makeTranslation(0.15, 0, 0.45)), "#c0392b");
  }

  end() {
    for (const im of Object.values(this.parts)) { im.instanceMatrix.needsUpdate = true; if (im.instanceColor) im.instanceColor.needsUpdate = true; }
  }

  /** À appeler à chaque image : oriente les bulles vers la caméra. */
  face(camera: THREE.Camera) {
    camera.getWorldQuaternion(this.q);
    for (const b of Object.values(this.bubbles)) {
      b.pos.forEach((p, i) => { this.m.compose(this.v.copy(p), this.q, this.one); b.mesh.setMatrixAt(i, this.m); });
      b.mesh.count = b.pos.length; b.mesh.instanceMatrix.needsUpdate = true;
    }
  }

  dispose() {
    for (const im of Object.values(this.parts)) { im.geometry.dispose(); (im.material as THREE.Material).dispose(); }
    for (const b of Object.values(this.bubbles)) { const mt = b.mesh.material as THREE.MeshBasicMaterial; mt.map?.dispose(); mt.dispose(); }
  }
}

/** Chariot de l'agent de liaison (plateau, montants, roues, poignée), x = sens de marche. */
export function cartGeometry(): THREE.BufferGeometry {
  const parts: THREE.BufferGeometry[] = [];
  const add = (g: THREE.BufferGeometry, x: number, y: number, z: number) => { g.translate(x, y, z); parts.push(g.index ? g.toNonIndexed() : g); };
  add(new THREE.BoxGeometry(0.9, 0.04, 0.56), 0, 0.42, 0);
  add(new THREE.BoxGeometry(0.9, 0.03, 0.56), 0, 0.14, 0);
  for (const x of [-0.42, 0.42]) for (const z of [-0.25, 0.25]) {
    add(new THREE.BoxGeometry(0.03, 0.3, 0.03), x, 0.28, z);
    const w = new THREE.CylinderGeometry(0.06, 0.06, 0.04, 10); w.rotateX(Math.PI / 2); add(w, x, 0.06, z);
  }
  for (const z of [-0.25, 0.25]) add(new THREE.BoxGeometry(0.03, 0.55, 0.03), -0.45, 0.7, z);
  add(new THREE.BoxGeometry(0.03, 0.03, 0.56), -0.45, 0.97, 0);
  return mergeGeometries(parts)!;
}

/** Paquet de pièces pliées avec son ticket (bon de paquet). */
export function bundleGeometry(): THREE.BufferGeometry {
  const parts: THREE.BufferGeometry[] = [];
  for (let i = 0; i < 3; i++) { const g = new THREE.BoxGeometry(0.36 - i * 0.012, 0.034, 0.26 - i * 0.01); g.translate(i % 2 ? 0.006 : -0.006, -0.04 + i * 0.037, 0); parts.push(g.toNonIndexed()); }
  const tie = new THREE.BoxGeometry(0.03, 0.118, 0.27); parts.push(tie.toNonIndexed());
  return mergeGeometries(parts)!;
}

/** Décor détaillé statique : matelas de coupe (source) et palette de cartons (sortie). */
export function addSourceSink(g: THREE.Group, src: { x: number; y: number }, sink: { x: number; y: number }) {
  const mat = (c: string) => new THREE.MeshStandardMaterial({ color: c, roughness: 0.85 });
  const box = (w: number, h: number, d: number, x: number, y: number, z: number, c: string) => {
    const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat(c)); m.position.set(x, y, z); m.castShadow = true; m.receiveShadow = true; g.add(m);
  };
  // table de coupe + matelas (plis de tissu alternés)
  box(1.6, 0.05, 0.9, src.x, 0.86, src.y, "#cfc6b4");
  for (const dx of [-0.72, 0.72]) for (const dz of [-0.38, 0.38]) box(0.05, 0.86, 0.05, src.x + dx, 0.43, src.y + dz, "#58656b");
  const cols = ["#3b7dd8", "#5b95e0", "#2f6dbf", "#e6e6e0"];
  for (let i = 0; i < 8; i++) box(1.45, 0.018, 0.78, src.x, 0.9 + i * 0.019, src.y, cols[i % cols.length]);
  // palette + cartons
  box(1.0, 0.12, 0.8, sink.x, 0.06, sink.y, "#b48a52");
  for (let l = 0; l < 3; l++) for (let i = 0; i < 2; i++) for (let j = 0; j < 2; j++)
    box(0.44, 0.3, 0.36, sink.x - 0.24 + i * 0.48, 0.28 + l * 0.31, sink.y - 0.19 + j * 0.38, l % 2 ? "#c49a66" : "#b98c57");
}
