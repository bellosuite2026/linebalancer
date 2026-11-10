import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { addMachineBody } from "../lib/machines3d";
import { MACHINE_CATALOG, ZONES, operatorPoint, type Machine, type WorkshopPlan } from "../lib/workshop";

export interface SceneStation {
  station: number;
  x: number;
  z: number;
  machineIds: string[];
  virtual?: boolean;
}

export interface SceneStationState {
  utilization: number;
  queue: number;
  working: boolean;
}

export interface SceneBundle {
  id: number;
  x: number;
  z: number;
  size: number;
  kind: "queue" | "work" | "move";
}

export interface SceneWorker {
  id: string;
  label: string;
  x: number;
  z: number;
  kind: "idle" | "walk" | "work";
}

interface Props {
  plan?: WorkshopPlan | null;
  stations?: SceneStation[];
  states?: Record<string, SceneStationState>;
  bundles?: SceneBundle[];
  workers?: SceneWorker[];
  title?: string;
  className?: string;
}

const EMPTY_STATIONS: SceneStation[] = [];
const EMPTY_BUNDLES: SceneBundle[] = [];
const EMPTY_WORKERS: SceneWorker[] = [];
const ROOM_HEIGHT = 2.8;
const TABLE_HEIGHT = 0.76;

function colorForLoad(value: number) {
  return value >= 92 ? "#d84d35" : value >= 75 ? "#d49a26" : value >= 40 ? "#328b63" : "#6e91b1";
}

function disposeGroup(group: THREE.Group) {
  group.traverse((object) => {
    if (object.userData.shared) return;     // géométries / matériaux partagés de la bibliothèque 3D
    if (object instanceof THREE.Mesh || object instanceof THREE.Line) object.geometry.dispose();
    if (!(object instanceof THREE.Mesh || object instanceof THREE.Line || object instanceof THREE.Sprite)) return;
    const raw = object.material;
    const materials = Array.isArray(raw) ? raw : [raw];
    for (const material of materials) {
      if (material instanceof THREE.Material && "map" in material && material.map instanceof THREE.Texture) material.map.dispose();
      material.dispose();
    }
  });
  group.clear();
}

function makeBox(
  group: THREE.Group,
  size: [number, number, number],
  position: [number, number, number],
  material: THREE.Material,
) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(...size), material);
  mesh.position.set(...position);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  group.add(mesh);
  return mesh;
}

function makeLabel(text: string, color = "#263746") {
  const canvas = document.createElement("canvas");
  canvas.width = 320;
  canvas.height = 96;
  const context = canvas.getContext("2d")!;
  context.fillStyle = "rgba(255,255,255,.94)";
  context.fillRect(4, 4, 312, 88);
  context.strokeStyle = "#c7c5bc";
  context.lineWidth = 5;
  context.strokeRect(4, 4, 312, 88);
  context.fillStyle = color;
  context.font = "700 42px sans-serif";
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillText(text, 160, 48, 290);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true, depthTest: false }));
  sprite.scale.set(1.45, 0.44, 1);
  return sprite;
}

function wallSegment(group: THREE.Group, x1: number, z1: number, x2: number, z2: number, thickness: number, shiftX: number, shiftZ: number) {
  const dx = x2 - x1;
  const dz = z2 - z1;
  const length = Math.hypot(dx, dz);
  if (length < 0.04) return;
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(length, ROOM_HEIGHT, Math.max(0.08, thickness)),
    new THREE.MeshStandardMaterial({ color: "#d2c8b7", roughness: 0.86 }));
  mesh.position.set((x1 + x2) / 2 + shiftX, ROOM_HEIGHT / 2, (z1 + z2) / 2 + shiftZ);
  mesh.rotation.y = -Math.atan2(dz, dx);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  group.add(mesh);
}

function addWall(group: THREE.Group, wall: Extract<WorkshopPlan["elements"][number], { kind: "wall" }>, doors: WorkshopPlan["elements"], shiftX: number, shiftZ: number) {
  const dx = wall.x2 - wall.x1;
  const dz = wall.y2 - wall.y1;
  const length = Math.hypot(dx, dz);
  if (length < 0.04) return;
  const angle = Math.atan2(dz, dx);
  const openings = doors.flatMap((element) => {
    if (element.kind !== "door") return [];
    const delta = Math.abs((((element.rot * Math.PI) / 180 - angle + Math.PI / 2) % Math.PI) - Math.PI / 2);
    if (delta > 0.2) return [];
    const t = ((element.x - wall.x1) * dx + (element.y - wall.y1) * dz) / (length * length);
    const px = wall.x1 + t * dx;
    const pz = wall.y1 + t * dz;
    if (t <= 0 || t >= 1 || Math.hypot(element.x - px, element.y - pz) > 0.35) return [];
    return [{ start: Math.max(0, t * length - element.width / 2), end: Math.min(length, t * length + element.width / 2), door: element }];
  }).sort((a, b) => a.start - b.start);

  let cursor = 0;
  for (const opening of openings) {
    const end = Math.max(cursor, opening.start);
    wallSegment(group, wall.x1 + (dx / length) * cursor, wall.y1 + (dz / length) * cursor,
      wall.x1 + (dx / length) * end, wall.y1 + (dz / length) * end, wall.thickness, shiftX, shiftZ);
    const door = opening.door;
    const frame = new THREE.MeshStandardMaterial({ color: door.exit ? "#27845a" : "#7d8992", roughness: 0.68 });
    for (const side of [-1, 1]) {
      const post = new THREE.Mesh(new THREE.BoxGeometry(0.08, 2.1, 0.08), frame);
      const offset = (door.width / 2) * side;
      post.position.set(door.x + Math.cos(angle) * offset + shiftX, 1.05, door.y + Math.sin(angle) * offset + shiftZ);
      group.add(post);
    }
    cursor = Math.max(cursor, opening.end);
  }
  wallSegment(group, wall.x1 + (dx / length) * cursor, wall.y1 + (dz / length) * cursor,
    wall.x2, wall.y2, wall.thickness, shiftX, shiftZ);
}

function addOperator(group: THREE.Group, x: number, z: number, active = false, stationId?: number) {
  const clothing = new THREE.MeshStandardMaterial({ color: active ? "#1f6685" : "#76858b", roughness: 0.82 });
  const skin = new THREE.MeshStandardMaterial({ color: "#d9aa87", roughness: 0.9 });
  const seat = new THREE.MeshStandardMaterial({ color: "#4e5960", roughness: 0.9 });
  const chair = new THREE.Mesh(new THREE.CylinderGeometry(0.2, 0.22, 0.08, 12), seat);
  chair.position.set(x, 0.43, z);
  group.add(chair);
  const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.16, 0.38, 3, 8), clothing);
  body.position.set(x, 0.91, z - 0.1);
  body.rotation.x = -0.2;
  body.userData.stationId = stationId;
  body.userData.part = "operator";
  group.add(body);
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.12, 12, 10), skin);
  head.position.set(x, 1.28, z - 0.12);
  group.add(head);
}

function makeWorker(group: THREE.Group, worker: SceneWorker) {
  const actor = new THREE.Group();
  actor.userData.workerId = worker.id;
  const clothing = new THREE.MeshStandardMaterial({ color: "#76858b", roughness: 0.82 });
  const skin = new THREE.MeshStandardMaterial({ color: "#d9aa87", roughness: 0.9 });
  const body = new THREE.Mesh(new THREE.CapsuleGeometry(0.17, 0.42, 3, 8), clothing);
  body.position.y = 0.8;
  body.userData.workerPart = true;
  actor.add(body);
  const head = new THREE.Mesh(new THREE.SphereGeometry(0.13, 12, 10), skin);
  head.position.set(0, 1.16, -0.02);
  actor.add(head);
  for (const x of [-0.09, 0.09]) {
    const leg = makeBox(actor, [0.07, 0.34, 0.08], [x, 0.25, 0.02], new THREE.MeshStandardMaterial({ color: "#454c52", roughness: 0.9 }));
    leg.userData.walkLeg = true;
  }
  const name = makeLabel(worker.label, "#263746");
  name.position.set(0, 1.62, 0);
  name.scale.set(1.05, 0.32, 1);
  actor.add(name);
  group.add(actor);
  return actor;
}

function addMachine(group: THREE.Group, machine: Machine, shiftX: number, shiftZ: number, stationId?: number, showOperator = true) {
  const root = new THREE.Group();
  root.position.set(machine.x + shiftX, 0, machine.y + shiftZ);
  root.rotation.y = (-machine.rot * Math.PI) / 180;
  group.add(root);
  const tableTop = addMachineBody(root, machine.type, machine.w, machine.d, machine.status);
  if (stationId != null) {
    // plateau propre (non partagé) : sa couleur suit l'état du poste
    tableTop.material = (tableTop.material as THREE.MeshStandardMaterial).clone();
    tableTop.userData.shared = false;
    tableTop.userData.stationId = stationId;
    tableTop.userData.part = "tabletop";
    tableTop.userData.baseColor = machine.status === "panne" ? "#b94b3d" : machine.status === "reserve" ? "#aeb4b6" : "#e2e4df";
  }
  if (showOperator && machine.status === "service" && MACHINE_CATALOG[machine.type]?.machine_type !== "") {
    const [ox, oz] = operatorPoint(machine);
    addOperator(group, ox + shiftX, oz + shiftZ, false, stationId);
  }
  const label = makeLabel(`${machine.label} · ${MACHINE_CATALOG[machine.type]?.short ?? "POSTE"}`, machine.status === "panne" ? "#a83a2f" : "#263746");
  label.position.set(machine.x + shiftX, 1.8, machine.y + shiftZ);
  group.add(label);
}

export default function PlanScene3D({ plan, stations = EMPTY_STATIONS, states = {}, bundles = EMPTY_BUNDLES, workers = EMPTY_WORKERS, title = "Vue 3D", className = "" }: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<THREE.Scene | null>(null);
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null);
  const cameraRef = useRef<THREE.PerspectiveCamera | null>(null);
  const controlsRef = useRef<OrbitControls | null>(null);
  const modelRef = useRef<THREE.Group | null>(null);
  const activityRef = useRef<THREE.Group | null>(null);
  const bundleRef = useRef<THREE.Group | null>(null);
  const workerGroupRef = useRef<THREE.Group | null>(null);
  const resetRef = useRef<(() => void) | null>(null);
  const bundlePool = useRef<THREE.Mesh[]>([]);
  const stationIndicators = useRef(new Map<number, THREE.Mesh>());
  const workerActors = useRef(new Map<string, THREE.Group>());
  const offsets = useRef({ x: 0, z: 0 });
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "low-power" });
    } catch {
      setError("La navigation ne peut pas créer de contexte WebGL sur cet appareil.");
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.domElement.className = "p3d-canvas";
    host.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color("#e9e7df");
    scene.add(new THREE.HemisphereLight("#fffdf5", "#728080", 2.1));
    const sunlight = new THREE.DirectionalLight("#fff8e9", 2.2);
    sunlight.position.set(-16, 26, -12);
    sunlight.castShadow = true;
    sunlight.shadow.mapSize.set(1024, 1024);
    scene.add(sunlight);
    const model = new THREE.Group();
    const activity = new THREE.Group();
    const bundleGroup = new THREE.Group();
    const workerGroup = new THREE.Group();
    scene.add(model, activity, bundleGroup, workerGroup);
    const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 1500);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.075;
    controls.maxPolarAngle = Math.PI * 0.48;
    controls.minDistance = 2;

    sceneRef.current = scene;
    rendererRef.current = renderer;
    cameraRef.current = camera;
    controlsRef.current = controls;
    modelRef.current = model;
    activityRef.current = activity;
    bundleRef.current = bundleGroup;
    workerGroupRef.current = workerGroup;

    const resize = () => {
      const width = Math.max(1, host.clientWidth);
      const height = Math.max(1, host.clientHeight);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height, false);
    };
    const observer = new ResizeObserver(resize);
    observer.observe(host);
    resize();
    let frame = 0;
    const render = () => {
      controls.update();
      renderer.render(scene, camera);
      frame = requestAnimationFrame(render);
    };
    render();
    resetRef.current = () => {
      controls.reset();
    };
    setReady(true);

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      controls.dispose();
      disposeGroup(model);
      disposeGroup(activity);
      disposeGroup(bundleGroup);
      disposeGroup(workerGroup);
      renderer.dispose();
      renderer.domElement.remove();
      sceneRef.current = null;
      rendererRef.current = null;
      cameraRef.current = null;
      controlsRef.current = null;
      modelRef.current = null;
      activityRef.current = null;
      bundleRef.current = null;
      workerGroupRef.current = null;
      resetRef.current = null;
      bundlePool.current = [];
      stationIndicators.current.clear();
      workerActors.current.clear();
      setReady(false);
    };
  }, []);

  useEffect(() => {
    const group = workerGroupRef.current;
    if (!ready || !group) return;
    const activeIds = new Set(workers.map((worker) => worker.id));
    for (const [id, actor] of workerActors.current) if (!activeIds.has(id)) {
      group.remove(actor);
      disposeGroup(actor);
      workerActors.current.delete(id);
    }
    const { x: shiftX, z: shiftZ } = offsets.current;
    for (const worker of workers) {
      let actor = workerActors.current.get(worker.id);
      if (!actor) {
        actor = makeWorker(group, worker);
        workerActors.current.set(worker.id, actor);
      }
      actor.position.set(worker.x + shiftX, 0, worker.z + shiftZ);
      actor.userData.kind = worker.kind;
      actor.traverse((object) => {
        if (!(object instanceof THREE.Mesh)) return;
        if (object.userData.workerPart) {
          const color = worker.kind === "work" ? "#1f6685" : worker.kind === "walk" ? "#c17b2c" : "#76858b";
          (object.material as THREE.MeshStandardMaterial).color.set(color);
        }
        if (object.userData.walkLeg) object.rotation.x = worker.kind === "walk" ? Math.sin(performance.now() / 75 + (object.position.x < 0 ? 0 : Math.PI)) * 0.55 : 0;
      });
    }
  }, [ready, workers]);

  useEffect(() => {
    const scene = sceneRef.current;
    const model = modelRef.current;
    const activity = activityRef.current;
    const camera = cameraRef.current;
    const controls = controlsRef.current;
    if (!ready || !scene || !model || !activity || !camera || !controls) return;
    disposeGroup(model);
    disposeGroup(activity);
    stationIndicators.current.clear();

    const stationXs = stations.map((station) => station.x);
    const stationZs = stations.map((station) => station.z);
    const minX = plan ? 0 : Math.min(0, ...stationXs) - 1.5;
    const minZ = plan ? 0 : Math.min(0, ...stationZs) - 1.5;
    const width = plan ? Number(plan.width_m) : Math.max(4, ...stationXs.map((x) => x - minX + 2.5));
    const length = plan ? Number(plan.length_m) : Math.max(4, ...stationZs.map((z) => z - minZ + 2.5));
    const shiftX = -minX + (plan ? 0 : 1.5);
    const shiftZ = -minZ + (plan ? 0 : 1.5);
    offsets.current = { x: shiftX, z: shiftZ };

    const floor = new THREE.Mesh(new THREE.PlaneGeometry(width, length), new THREE.MeshStandardMaterial({ color: "#f6f3eb", roughness: 0.95 }));
    floor.rotation.x = -Math.PI / 2;
    floor.position.set(width / 2, -0.035, length / 2);
    floor.receiveShadow = true;
    model.add(floor);
    const gridSize = Math.ceil(Math.max(width, length));
    const grid = new THREE.GridHelper(gridSize, gridSize, "#c7c4b9", "#dedbd2");
    grid.position.set(width / 2, 0.002, length / 2);
    model.add(grid);

    const elements = plan?.elements ?? [];
    const assigned = new Map<string, number>();
    for (const station of stations) for (const machineId of station.machineIds) assigned.set(machineId, station.station);
    const zoneMaterials: THREE.MeshStandardMaterial[] = [];
    for (const element of elements) {
      if (element.kind === "zone" || element.kind === "aisle") {
        const material = new THREE.MeshStandardMaterial({
          color: element.kind === "zone" ? ZONES[element.zone]?.color ?? "#dedbd1" : element.main ? "#d8e5e0" : "#e9e7df",
          transparent: true,
          opacity: element.kind === "zone" ? 0.58 : 0.74,
          roughness: 1,
          side: THREE.DoubleSide,
        });
        zoneMaterials.push(material);
        const x = element.x;
        const z = element.y;
        const mesh = new THREE.Mesh(new THREE.PlaneGeometry(element.w, element.h), material);
        mesh.rotation.x = -Math.PI / 2;
        mesh.position.set(x + element.w / 2 + shiftX, 0.009, z + element.h / 2 + shiftZ);
        model.add(mesh);
        const label = makeLabel(element.kind === "zone" ? element.name || ZONES[element.zone]?.label || "Zone" : element.main ? "ALLÉE" : "PASSAGE", "#625e53");
        label.position.set(x + element.w / 2 + shiftX, 0.12, z + element.h / 2 + shiftZ);
        label.scale.set(Math.min(2.2, Math.max(0.8, element.w * 0.6)), 0.3, 1);
        model.add(label);
      }
    }
    for (const element of elements) {
      if (element.kind === "wall") addWall(model, element, elements, shiftX, shiftZ);
      else if (element.kind === "pillar") {
        makeBox(model, [element.w, ROOM_HEIGHT, element.d], [element.x + shiftX, ROOM_HEIGHT / 2, element.y + shiftZ], new THREE.MeshStandardMaterial({ color: "#555d5e", roughness: 0.9 }));
      } else if (element.kind === "machine") {
        addMachine(model, element, shiftX, shiftZ, assigned.get(element.id), stations.length === 0);
      }
    }
    if (!elements.some((element) => element.kind === "wall")) {
      const edge = 0.14;
      wallSegment(model, 0, 0, width, 0, edge, shiftX, shiftZ);
      wallSegment(model, width, 0, width, length, edge, shiftX, shiftZ);
      wallSegment(model, width, length, 0, length, edge, shiftX, shiftZ);
      wallSegment(model, 0, length, 0, 0, edge, shiftX, shiftZ);
    }

    for (const station of stations) {
      const machineExists = station.machineIds.some((id) => elements.some((element) => element.kind === "machine" && element.id === id));
      if (machineExists) continue;
      const machine: Machine = {
        id: `virtual-${station.station}`, kind: "machine", type: "piqueuse_plate", x: station.x, y: station.z,
        w: 1.15, d: 0.72, rot: 0, label: `Poste ${station.station}`, operator: "front", status: "service",
      };
      addMachine(model, machine, shiftX, shiftZ, undefined, false);
    }

    for (const station of stations) {
      const indicator = new THREE.Mesh(
        new THREE.TorusGeometry(0.52, 0.035, 8, 32),
        new THREE.MeshStandardMaterial({ color: "#7b9a91", roughness: 0.74, metalness: 0.08 }),
      );
      indicator.rotation.x = Math.PI / 2;
      indicator.position.set(station.x + shiftX, 0.045, station.z + shiftZ);
      indicator.userData.stationId = station.station;
      activity.add(indicator);
      stationIndicators.current.set(station.station, indicator);
      const label = makeLabel(station.virtual ? `POSTE ${station.station} · VIRTUEL` : `POSTE ${station.station}`, station.virtual ? "#a83a2f" : "#263746");
      label.position.set(station.x + shiftX, 2.15, station.z + shiftZ);
      activity.add(label);
    }

    const target = new THREE.Vector3(width / 2, 0.7, length / 2);
    controls.target.copy(target);
    const span = Math.max(width, length, 4);
    camera.position.set(width / 2 + span * 0.8, span * 0.92, length / 2 + span * 1.05);
    camera.near = Math.max(0.1, span / 300);
    camera.far = span * 20;
    camera.updateProjectionMatrix();
    controls.minDistance = Math.max(2, span * 0.18);
    controls.maxDistance = span * 4;
    controls.update();
    resetRef.current = () => {
      camera.position.set(width / 2 + span * 0.8, span * 0.92, length / 2 + span * 1.05);
      controls.target.copy(target);
      controls.update();
    };
    return () => {
      for (const material of zoneMaterials) material.dispose();
    };
  }, [plan, ready, stations]);

  useEffect(() => {
    const activity = activityRef.current;
    const model = modelRef.current;
    if (!ready || !activity || !model) return;
    for (const [stationId, indicator] of stationIndicators.current) {
      const state = states[String(stationId)];
      const material = indicator.material as THREE.MeshStandardMaterial;
      material.color.set(state ? colorForLoad(state.utilization) : "#7b9a91");
      material.emissive.set(state?.working ? "#183d32" : "#000000");
      indicator.scale.setScalar(state?.queue ? 1 + Math.min(state.queue, 40) / 180 : 1);
    }
    const updateStationMesh = (object: THREE.Object3D) => {
      if (!(object instanceof THREE.Mesh) || object.userData.stationId == null) return;
      const state = states[String(object.userData.stationId)];
      const material = object.material as THREE.MeshStandardMaterial;
      if (object.userData.part === "tabletop") material.color.set(state ? colorForLoad(state.utilization) : object.userData.baseColor);
      if (object.userData.part === "operator") material.color.set(state?.working ? "#1f6685" : "#76858b");
      if (object.userData.part == null && state) material.color.set(colorForLoad(state.utilization));
    };
    model.traverse(updateStationMesh);
    activity.traverse(updateStationMesh);
  }, [ready, states]);

  useEffect(() => {
    const group = bundleRef.current;
    if (!ready || !group) return;
    const visibleBundles = bundles.slice(0, 260);
    while (bundlePool.current.length < visibleBundles.length) {
      const material = new THREE.MeshStandardMaterial({ color: "#d49a26", roughness: 0.46, metalness: 0.08, emissive: "#513600" });
      const mesh = new THREE.Mesh(new THREE.SphereGeometry(0.12, 12, 10), material);
      mesh.castShadow = true;
      group.add(mesh);
      bundlePool.current.push(mesh);
    }
    const { x: shiftX, z: shiftZ } = offsets.current;
    bundlePool.current.forEach((mesh, index) => {
      const bundle = visibleBundles[index];
      mesh.visible = !!bundle;
      if (!bundle) return;
      mesh.position.set(bundle.x + shiftX, bundle.kind === "work" ? 1.06 : 0.2, bundle.z + shiftZ);
      const color = bundle.kind === "work" ? "#2c7792" : bundle.kind === "move" ? "#d49a26" : "#c57442";
      (mesh.material as THREE.MeshStandardMaterial).color.set(color);
      const scale = Math.min(1.8, 0.75 + Math.log2(Math.max(1, bundle.size)) * 0.16);
      mesh.scale.setScalar(scale);
    });
  }, [bundles, ready]);

  return (
    <section className={`p3d ${className}`} aria-label={title}>
      <header className="p3d-bar">
        <h3 className="p3d-h">{title}</h3>
        <span className="p3d-help">Glisser : orbiter · molette/pincer : zoomer · Maj + glisser : déplacer</span>
        <button className="btn small" onClick={() => resetRef.current?.()} disabled={!ready} title="Réinitialiser la caméra">Réinitialiser la vue</button>
      </header>
      <div className="p3d-stage" ref={hostRef}>
        {!ready && !error && <div className="p3d-loading" role="status">Préparation de la scène 3D…</div>}
        {error && <p className="p3d-err" role="alert">{error}</p>}
      </div>
    </section>
  );
}