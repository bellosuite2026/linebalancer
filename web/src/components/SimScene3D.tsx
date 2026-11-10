// Vue 3D de la simulation (three.js, chargée à la demande) : décor statique fusionné par matériau,
// paquets / opérateurs / transporteurs / voyants d'état en InstancedMesh (fluide avec 60 postes,
// 60 opérateurs et 300 paquets sur tablette).
import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import { addMachineBody } from "../lib/machines3d";
import { STATE_COLOR, STATION_STATES, lotColor, type DesModel, type Frame } from "../lib/des";
import type { Machine, WorkshopPlan } from "../lib/workshop";

interface Props { model: DesModel; plan: WorkshopPlan | null; frame: Frame | null; className?: string }

const MAX_BUNDLES = 1200, MAX_ACTORS = 260;

function label(text: string) {
  const c = document.createElement("canvas"); c.width = 128; c.height = 64;
  const g = c.getContext("2d")!;
  g.fillStyle = "rgba(255,255,255,.92)"; g.fillRect(2, 2, 124, 60); g.strokeStyle = "#9aa3ad"; g.lineWidth = 3; g.strokeRect(2, 2, 124, 60);
  g.fillStyle = "#1d2b38"; g.font = "700 38px sans-serif"; g.textAlign = "center"; g.textBaseline = "middle"; g.fillText(text, 64, 34, 118);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace;
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: t, depthTest: false, transparent: true }));
  s.scale.set(0.7, 0.35, 1); return s;
}

/** Fusionne toutes les mailles d'un groupe par matériau (quelques appels de dessin au lieu de centaines). */
function mergeStatic(src: THREE.Group): THREE.Group {
  src.updateMatrixWorld(true);
  const byMat = new Map<THREE.Material, THREE.BufferGeometry[]>();
  src.traverse((o) => {
    if (!(o instanceof THREE.Mesh)) return;
    const g = (o.geometry as THREE.BufferGeometry).clone().applyMatrix4(o.matrixWorld);
    const geo = g.index ? g.toNonIndexed() : g;
    for (const k of Object.keys(geo.attributes)) if (!["position", "normal"].includes(k)) geo.deleteAttribute(k);
    const m = o.material as THREE.Material;
    (byMat.get(m) ?? byMat.set(m, []).get(m)!).push(geo);
  });
  const out = new THREE.Group();
  for (const [m, list] of byMat) {
    const merged = mergeGeometries(list, false);
    if (!merged) continue;
    const mesh = new THREE.Mesh(merged, m); mesh.castShadow = true; mesh.receiveShadow = true; out.add(mesh);
    list.forEach((g) => g.dispose());
  }
  return out;
}

export default function SimScene3D({ model, plan, frame, className = "" }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const api = useRef<{ update: (f: Frame | null) => void } | null>(null);

  useEffect(() => {
    const el = host.current; if (!el) return;
    const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
    renderer.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
    renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene(); scene.background = new THREE.Color("#eef1f4");
    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 600);
    const controls = new OrbitControls(camera, renderer.domElement); controls.enableDamping = true; controls.maxPolarAngle = Math.PI * 0.48;
    scene.add(new THREE.HemisphereLight("#ffffff", "#8a8f94", 1.1));
    const sun = new THREE.DirectionalLight("#ffffff", 1.4); sun.castShadow = true; sun.shadow.mapSize.set(2048, 2048);
    scene.add(sun);

    // emprise
    const xs = model.stations.flatMap((s) => [s.x, s.mx, s.qx]), ys = model.stations.flatMap((s) => [s.y, s.my, s.qy]);
    const x0 = plan ? 0 : Math.min(...xs) - 2, x1 = plan ? plan.width_m : Math.max(...xs) + 2;
    const z0 = plan ? 0 : Math.min(...ys) - 2, z1 = plan ? plan.length_m : Math.max(...ys) + 2;
    const cx = (x0 + x1) / 2, cz = (z0 + z1) / 2, span = Math.max(x1 - x0, z1 - z0, 6);
    camera.position.set(cx + span * 0.15, span * 0.75, z1 + span * 0.55); controls.target.set(cx, 0, cz); controls.update();
    sun.position.set(cx - span * 0.3, span, cz - span * 0.2); sun.target.position.set(cx, 0, cz); scene.add(sun.target);
    const sc = sun.shadow.camera as THREE.OrthographicCamera; sc.left = -span; sc.right = span; sc.top = span; sc.bottom = -span; sc.far = span * 3; sc.updateProjectionMatrix();

    const floor = new THREE.Mesh(new THREE.PlaneGeometry(x1 - x0 + 2, z1 - z0 + 2), new THREE.MeshStandardMaterial({ color: "#d9dcd6", roughness: 0.95 }));
    floor.rotation.x = -Math.PI / 2; floor.position.set(cx, 0, cz); floor.receiveShadow = true; scene.add(floor);

    // ---- décor statique
    const stat = new THREE.Group();
    const wallMat = new THREE.MeshStandardMaterial({ color: "#d2c8b7", roughness: 0.86 });
    const used = new Set(model.stations.flatMap((s) => s.machine_ids));
    if (plan) {
      for (const e of plan.elements) {
        if (e.kind === "wall") {
          const L = Math.hypot(e.x2 - e.x1, e.y2 - e.y1); if (L < 0.05) continue;
          const m = new THREE.Mesh(new THREE.BoxGeometry(L, 2.2, Math.max(0.08, e.thickness || 0.2)), wallMat);
          m.position.set((e.x1 + e.x2) / 2, 1.1, (e.y1 + e.y2) / 2); m.rotation.y = -Math.atan2(e.y2 - e.y1, e.x2 - e.x1); stat.add(m);
        } else if (e.kind === "pillar") {
          const m = new THREE.Mesh(new THREE.BoxGeometry(e.w, 2.8, e.d), new THREE.MeshStandardMaterial({ color: "#8b8f94" }));
          m.position.set(e.x, 1.4, e.y); stat.add(m);
        } else if (e.kind === "aisle") {
          const m = new THREE.Mesh(new THREE.BoxGeometry(e.w, 0.004, e.h), new THREE.MeshStandardMaterial({ color: e.main ? "#bfe0c9" : "#d3e9d9" }));
          m.position.set(e.x + e.w / 2, 0.003, e.y + e.h / 2); stat.add(m);
        } else if (e.kind === "machine") {
          const m = e as Machine;
          const root = new THREE.Group(); root.position.set(m.x, 0, m.y); root.rotation.y = (-m.rot * Math.PI) / 180;
          addMachineBody(root, m.type, m.w, m.d, used.has(m.id) ? "service" : m.status === "panne" ? "panne" : "reserve");
          stat.add(root);
        }
      }
    }
    for (const s of model.stations) {
      if (!plan || !s.machine_ids.length) {
        const root = new THREE.Group(); root.position.set(s.mx, 0, s.my); root.rotation.y = (-(s.rot ?? 0) * Math.PI) / 180;
        addMachineBody(root, s.machine || (s.machine_type in { manuel: 1 } ? "table_travail" : "piqueuse_plate"), 1.2, 0.6);
        stat.add(root);
      }
      const cart = new THREE.Group(); cart.position.set(s.qx, 0, s.qy); cart.rotation.y = (-(s.rot ?? 0) * Math.PI) / 180;
      addMachineBody(cart, "chariot", 0.55, 0.42); stat.add(cart);
      const lb = label(s.id); lb.position.set(s.mx, 1.75, s.my); scene.add(lb);
    }
    for (const [x, z, col] of [[model.source.x, model.source.y, "#1f4e79"], [model.sink.x, model.sink.y, "#2e9e5b"]] as [number, number, string][]) {
      const m = new THREE.Mesh(new THREE.CylinderGeometry(0.35, 0.35, 0.05, 20), new THREE.MeshStandardMaterial({ color: col })); m.position.set(x, 0.03, z); stat.add(m);
    }
    const merged = mergeStatic(stat);
    scene.add(merged);

    // ---- dynamiques (InstancedMesh)
    const n = model.stations.length;
    const lamps = new THREE.InstancedMesh(new THREE.BoxGeometry(1.35, 0.02, 0.95), new THREE.MeshStandardMaterial({ color: "#ffffff", roughness: 0.6 }), n);
    const beacons = new THREE.InstancedMesh(new THREE.CylinderGeometry(0.07, 0.07, 0.16, 12), new THREE.MeshStandardMaterial({ color: "#ffffff", emissive: "#222222" }), n);
    const tmp = new THREE.Object3D(), col = new THREE.Color();
    model.stations.forEach((s, i) => {
      tmp.position.set(s.mx, 0.012, s.my); tmp.rotation.set(0, (-(s.rot ?? 0) * Math.PI) / 180, 0); tmp.scale.set(1, 1, 1); tmp.updateMatrix(); lamps.setMatrixAt(i, tmp.matrix);
      tmp.position.set(s.mx, 1.45, s.my); tmp.updateMatrix(); beacons.setMatrixAt(i, tmp.matrix);
      lamps.setColorAt(i, col.set(STATE_COLOR.starved)); beacons.setColorAt(i, col);
    });
    scene.add(lamps, beacons);
    const bundles = new THREE.InstancedMesh(new THREE.BoxGeometry(0.36, 0.11, 0.26), new THREE.MeshStandardMaterial({ color: "#ffffff", roughness: 0.8 }), MAX_BUNDLES);
    bundles.castShadow = true; bundles.count = 0; scene.add(bundles);
    const bodies = new THREE.InstancedMesh(new THREE.CapsuleGeometry(0.17, 0.5, 3, 8), new THREE.MeshStandardMaterial({ color: "#ffffff", roughness: 0.85 }), MAX_ACTORS);
    const heads = new THREE.InstancedMesh(new THREE.SphereGeometry(0.12, 12, 10), new THREE.MeshStandardMaterial({ color: "#d9aa87", roughness: 0.9 }), MAX_ACTORS);
    const carts = new THREE.InstancedMesh(new THREE.BoxGeometry(0.9, 0.5, 0.6), new THREE.MeshStandardMaterial({ color: "#ffffff", roughness: 0.6 }), 16);
    bodies.castShadow = true; carts.castShadow = true; bodies.count = 0; heads.count = 0; carts.count = 0;
    scene.add(bodies, heads, carts);
    const white = new THREE.Color("#ffffff");
    for (let i = 0; i < MAX_BUNDLES; i++) bundles.setColorAt(i, white);
    for (let i = 0; i < MAX_ACTORS; i++) bodies.setColorAt(i, white);
    for (let i = 0; i < 16; i++) carts.setColorAt(i, white);

    let clock = 0;
    const update = (f: Frame | null) => {
      if (!f) return;
      clock = f.t;
      f.stations.forEach((st, i) => { col.set(STATE_COLOR[STATION_STATES[st] ?? "starved"]); lamps.setColorAt(i, col); beacons.setColorAt(i, col); });
      if (lamps.instanceColor) lamps.instanceColor.needsUpdate = true;
      if (beacons.instanceColor) beacons.instanceColor.needsUpdate = true;
      let k = 0;
      for (const b of f.bundles) {
        if (k >= MAX_BUNDLES) break;
        const carried = b.kind === 3 || b.kind === 4;
        const y = carried ? (b.kind === 4 ? 0.55 : 0.95) + (b.z - 1) * 0.12 : b.kind === 1 ? 0.86 : 0.82 + Math.min(b.z, 14) * 0.12;
        const sz = 0.55 + Math.min(1.2, b.qty / 20) * 0.5;
        tmp.position.set(b.x, y, b.y); tmp.rotation.set(0, 0, 0); tmp.scale.set(sz, 1, sz); tmp.updateMatrix();
        bundles.setMatrixAt(k, tmp.matrix); bundles.setColorAt(k, col.set(b.rework ? "#d64541" : lotColor(b.lot))); k++;
      }
      bundles.count = k; bundles.instanceMatrix.needsUpdate = true; if (bundles.instanceColor) bundles.instanceColor.needsUpdate = true;
      let o = 0, t = 0;
      for (const a of f.actors) {
        if (a.kind === "operator" && o < MAX_ACTORS) {
          const walking = a.state === 1 || a.state === 4;
          const bob = walking ? Math.abs(Math.sin(clock * 90 + o)) * 0.05 : 0;
          tmp.position.set(a.x, 0.42 + 0.25 + bob, a.y); tmp.rotation.set(0, 0, 0); tmp.scale.set(1, 1, 1); tmp.updateMatrix();
          bodies.setMatrixAt(o, tmp.matrix);
          bodies.setColorAt(o, col.set(walking ? "#e8a33d" : a.state === 2 || a.state === 3 ? "#1f6685" : a.state === 5 ? "#95a5a6" : "#76858b"));
          tmp.position.set(a.x, 1.18 + bob, a.y); tmp.updateMatrix(); heads.setMatrixAt(o, tmp.matrix);
          o++;
        } else if (a.kind === "transporter" && t < 16) {
          tmp.position.set(a.x, 0.3, a.y); tmp.rotation.set(0, -a.heading, 0); tmp.scale.set(1, 1, 1); tmp.updateMatrix();
          carts.setMatrixAt(t, tmp.matrix); carts.setColorAt(t, col.set(a.load ? "#16a085" : "#7f8c8d")); t++;
        }
      }
      bodies.count = o; heads.count = o; carts.count = t;
      bodies.instanceMatrix.needsUpdate = true; heads.instanceMatrix.needsUpdate = true; carts.instanceMatrix.needsUpdate = true;
      if (bodies.instanceColor) bodies.instanceColor.needsUpdate = true;
      if (carts.instanceColor) carts.instanceColor.needsUpdate = true;
    };
    api.current = { update };

    const resize = () => { const w = el.clientWidth, h = Math.max(200, el.clientHeight); renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); };
    const ro = new ResizeObserver(resize); ro.observe(el); resize();
    let raf = 0;
    const loop = () => { controls.update(); renderer.render(scene, camera); raf = requestAnimationFrame(loop); };
    loop();
    return () => {
      cancelAnimationFrame(raf); ro.disconnect(); controls.dispose();
      scene.traverse((o) => {
        if (o.userData.shared) return;
        if (o instanceof THREE.Mesh || o instanceof THREE.InstancedMesh) { o.geometry.dispose(); }
        if (o instanceof THREE.Sprite) { o.material.map?.dispose(); o.material.dispose(); }
      });
      renderer.dispose(); el.removeChild(renderer.domElement); api.current = null;
    };
  }, [model, plan]);

  useEffect(() => { api.current?.update(frame); }, [frame]);

  return <div ref={host} className={`sim3d ${className}`} role="img" aria-label="Simulation 3D de l'atelier" />;
}
