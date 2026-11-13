// Navigation au clavier / aux boutons d'une caméra three.js pilotée par OrbitControls.
import * as THREE from "three";
import type { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { NavApi } from "../components/NavControls";

export type Preset = "top" | "front" | "side" | "persp";

/** Construit l'API de navigation d'une scène : centre (cx, cz), étendue span (m), position d'accueil. */
export function orbitNav(camera: THREE.PerspectiveCamera, controls: OrbitControls,
  scene: { cx: number; cz: number; cy?: number; span: number; home: THREE.Vector3; homeTarget?: THREE.Vector3 }): NavApi {
  const center = () => new THREE.Vector3(scene.cx, scene.cy ?? 0, scene.cz);
  const offset = () => camera.position.clone().sub(controls.target);
  const clampDist = (d: number) => Math.min(controls.maxDistance || Infinity, Math.max(controls.minDistance || 0.5, d));
  const sph = () => new THREE.Spherical().setFromVector3(offset());
  const apply = (s: THREE.Spherical) => {
    s.phi = Math.max(0.02, Math.min(controls.maxPolarAngle - 0.001, s.phi));
    s.radius = clampDist(s.radius);
    camera.position.copy(controls.target).add(new THREE.Vector3().setFromSpherical(s));
    controls.update();
  };
  const fitDist = () => (scene.span / 2) / Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2) * 1.15;
  return {
    zoom: (f) => { const s = sph(); s.radius /= f; apply(s); },
    pan: (dx, dy) => {
      const dist = offset().length();
      const right = new THREE.Vector3().setFromMatrixColumn(camera.matrix, 0).setY(0).normalize();
      const fwd = new THREE.Vector3().crossVectors(new THREE.Vector3(0, 1, 0), right).normalize();  // vers le haut de l'écran, au sol
      const step = dist * 1.2;
      const move = right.multiplyScalar(dx * step).add(fwd.multiplyScalar(-dy * step));
      controls.target.add(move); camera.position.add(move); controls.update();
    },
    fit: () => { const s = sph(); controls.target.copy(center()); s.radius = fitDist(); apply(s); },
    center: () => { const o = offset(); controls.target.copy(center()); camera.position.copy(center()).add(o); controls.update(); },
    rotate: (r) => { const s = sph(); s.theta += r; apply(s); },
    tilt: (r) => { const s = sph(); s.phi += r; apply(s); },
    preset: (p) => {
      controls.target.copy(center());
      const d = fitDist();
      if (p === "persp") { camera.position.copy(scene.home); if (scene.homeTarget) controls.target.copy(scene.homeTarget); controls.update(); return; }
      const s = new THREE.Spherical(d, p === "top" ? 0.02 : 1.2, p === "side" ? Math.PI / 2 : 0);
      apply(s);
    },
    reset: () => { camera.position.copy(scene.home); controls.target.copy(scene.homeTarget ?? center()); controls.update(); },
  };
}

