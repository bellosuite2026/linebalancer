// Barre flottante de navigation commune aux vues 2D et 3D : zoom +/−, tout voir, recentrer, flèches de
// déplacement ; en 3D : rotation, inclinaison, vues prédéfinies et réinitialisation de la caméra.
// Maintien appuyé = mouvement continu. Raccourcis clavier (+, −, flèches, 0 ; en 3D Maj+flèches = tourner /
// incliner) actifs sur la dernière vue touchée ou survolée, jamais pendant une saisie.
import { useEffect, useRef, type ReactNode } from "react";
import type { Preset } from "../lib/nav3d";

export interface NavApi {
  zoom: (factor: number) => void;          // > 1 = rapprocher
  pan: (dx: number, dy: number) => void;   // pas en fraction de la vue (−1..1)
  fit: () => void;                         // tout voir
  center: () => void;                      // recentrer sans changer le zoom
  rotate?: (rad: number) => void;
  tilt?: (rad: number) => void;
  preset?: (p: Preset) => void;
  reset?: () => void;
}

let activeId = 0, nextId = 1;
const ZOOM_STEP = 1.12, PAN_STEP = 0.06, ROT_STEP = 0.06;

function isTyping(t: EventTarget | null) {
  const el = t as HTMLElement | null;
  if (!el) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable;
}

/** Bouton à maintien : une action au clic, puis répétée tant qu'on appuie. */
function HoldButton({ onStep, title, children, className = "" }: { onStep: () => void; title: string; children: ReactNode; className?: string }) {
  const timers = useRef<{ t?: number; i?: number }>({});
  const stop = () => { window.clearTimeout(timers.current.t); window.clearInterval(timers.current.i); timers.current = {}; };
  useEffect(() => stop, []);
  return (
    <button type="button" className={`nav-btn ${className}`} title={title} aria-label={title}
      onPointerDown={(e) => {
        e.preventDefault(); e.stopPropagation(); stop(); onStep();
        timers.current.t = window.setTimeout(() => { timers.current.i = window.setInterval(onStep, 50); }, 280);
      }}
      onPointerUp={stop} onPointerLeave={stop} onPointerCancel={stop}
      onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onStep(); } }}
      onContextMenu={(e) => e.preventDefault()}>
      {children}
    </button>
  );
}

function Click({ onClick, title, children, className = "" }: { onClick: () => void; title: string; children: ReactNode; className?: string }) {
  return <button type="button" className={`nav-btn ${className}`} title={title} aria-label={title}
    onPointerDown={(e) => e.stopPropagation()} onClick={(e) => { e.stopPropagation(); onClick(); }}>{children}</button>;
}

/** Enveloppe une vue (canvas, svg, scène 3D) et y superpose la barre de navigation. */
export default function NavControls({ api, mode, zoomPct, children, className = "" }: {
  api: React.MutableRefObject<NavApi | null>; mode: "2d" | "3d"; zoomPct?: number | null; children: ReactNode; className?: string;
}) {
  const id = useRef(0);
  if (!id.current) id.current = nextId++;
  const wrap = useRef<HTMLDivElement>(null);
  const a = () => api.current;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (activeId !== id.current || isTyping(e.target) || e.ctrlKey || e.metaKey || e.altKey) return;
      const n = a(); if (!n) return;
      const k = e.key;
      let done = true;
      if (k === "+" || k === "=" ) n.zoom(ZOOM_STEP);
      else if (k === "-" || k === "_") n.zoom(1 / ZOOM_STEP);
      else if (k === "0") n.fit();
      else if (k.startsWith("Arrow")) {
        const dx = k === "ArrowLeft" ? -1 : k === "ArrowRight" ? 1 : 0, dy = k === "ArrowUp" ? -1 : k === "ArrowDown" ? 1 : 0;
        if (mode === "3d" && e.shiftKey && dx && n.rotate) n.rotate(dx * ROT_STEP);
        else if (mode === "3d" && e.shiftKey && dy && n.tilt) n.tilt(dy * ROT_STEP);
        else n.pan(dx * PAN_STEP, dy * PAN_STEP);
      } else done = false;
      if (done) e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("keydown", onKey); if (activeId === id.current) activeId = 0; };
  }, [mode]);

  const activate = () => { activeId = id.current; };
  return (
    <div ref={wrap} className={`nav-wrap ${className}`} onPointerEnter={activate} onPointerDown={activate} onFocus={activate}>
      {children}
      <div className={`nav-bar nav-${mode}`} role="toolbar" aria-label={mode === "3d" ? "Navigation 3D" : "Navigation 2D"}>
        <div className="nav-group">
          <HoldButton title="Zoom avant (+)" onStep={() => a()?.zoom(ZOOM_STEP)}>＋</HoldButton>
          {mode === "2d" && zoomPct != null && <span className="nav-zoom" title="Niveau de zoom (100 % = tout le plan visible)">{Math.round(zoomPct)} %</span>}
          <HoldButton title="Zoom arrière (−)" onStep={() => a()?.zoom(1 / ZOOM_STEP)}>−</HoldButton>
          <Click title="Ajuster à la vue : tout voir (0)" onClick={() => a()?.fit()}>⤢</Click>
          <Click title="Recentrer" onClick={() => a()?.center()}>◎</Click>
        </div>
        <div className="nav-group nav-pad">
          <span />
          <HoldButton title="Déplacer vers le haut (↑)" onStep={() => a()?.pan(0, -PAN_STEP)}>▲</HoldButton>
          <span />
          <HoldButton title="Déplacer vers la gauche (←)" onStep={() => a()?.pan(-PAN_STEP, 0)}>◀</HoldButton>
          <span className="nav-pad-mid" />
          <HoldButton title="Déplacer vers la droite (→)" onStep={() => a()?.pan(PAN_STEP, 0)}>▶</HoldButton>
          <span />
          <HoldButton title="Déplacer vers le bas (↓)" onStep={() => a()?.pan(0, PAN_STEP)}>▼</HoldButton>
          <span />
        </div>
        {mode === "3d" && <>
          <div className="nav-group">
            <HoldButton title="Tourner à gauche (Maj + ←)" onStep={() => a()?.rotate?.(-ROT_STEP)}>⟲</HoldButton>
            <HoldButton title="Tourner à droite (Maj + →)" onStep={() => a()?.rotate?.(ROT_STEP)}>⟳</HoldButton>
            <HoldButton title="Incliner vers le haut : vue plus plongeante (Maj + ↑)" onStep={() => a()?.tilt?.(-ROT_STEP)}>⤒</HoldButton>
            <HoldButton title="Incliner vers le bas : vue plus rasante (Maj + ↓)" onStep={() => a()?.tilt?.(ROT_STEP)}>⤓</HoldButton>
          </div>
          <div className="nav-group nav-presets">
            <Click title="Vue de dessus" onClick={() => a()?.preset?.("top")}>Dessus</Click>
            <Click title="Vue de face" onClick={() => a()?.preset?.("front")}>Face</Click>
            <Click title="Vue de côté" onClick={() => a()?.preset?.("side")}>Côté</Click>
            <Click title="Vue en perspective" onClick={() => a()?.preset?.("persp")}>Persp.</Click>
            <Click title="Réinitialiser la caméra" onClick={() => a()?.reset?.()}>↺</Click>
          </div>
        </>}
      </div>
    </div>
  );
}

