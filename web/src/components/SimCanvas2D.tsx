// Vue 2D (canvas) de la simulation : plan d'atelier, postes colorés par état, chariots d'encours avec
// leurs paquets empilés, opérateurs et transporteurs qui se déplacent le long des allées.
import { useEffect, useMemo, useRef, useState } from "react";
import NavControls, { type NavApi } from "./NavControls";
import { MACHINE_CATALOG, rectCorners, type Machine, type WorkshopPlan } from "../lib/workshop";
import { bubbleCanvas, drawPerson2D, operatorRoles, type Bubble } from "../lib/simIcons";
import { OP_COLOR, OP_STATES, STATE_COLOR, STATION_STATES, lotColor, railPoint, type DesModel, type Frame } from "../lib/des";

interface Props { model: DesModel; plan: WorkshopPlan | null; frame: Frame | null; selected?: string | null; onSelect?: (sid: string | null) => void; className?: string; detail?: boolean }

export default function SimCanvas2D({ model, plan, frame, selected, onSelect, className = "", detail = false }: Props) {
  const roles = useMemo(() => operatorRoles(model), [model]);
  const ref = useRef<HTMLCanvasElement>(null);
  const [, force] = useState(0);
  const view = useRef<{ s: number; ox: number; oy: number } | null>(null);
  const drag = useRef<{ x: number; y: number; ox: number; oy: number; moved: boolean } | null>(null);
  const bg = useRef<HTMLCanvasElement | null>(null);
  const bgKey = useRef("");

  // emprise : salle du plan ou postes
  const bounds = () => {
    if (plan) return { x0: -0.5, y0: -0.5, x1: plan.width_m + 0.5, y1: plan.length_m + 0.5 };
    const rp = model.conveyor?.enabled ? model.conveyor.pts ?? [] : [];
    const xs = model.stations.flatMap((s) => [s.x, s.qx, s.mx]).concat([model.source.x, model.sink.x], rp.map((p) => p[0]));
    const ys = model.stations.flatMap((s) => [s.y, s.qy, s.my]).concat([model.source.y, model.sink.y], rp.map((p) => p[1]));
    return { x0: Math.min(...xs) - 1.5, y0: Math.min(...ys) - 1.5, x1: Math.max(...xs) + 1.5, y1: Math.max(...ys) + 1.5 };
  };

  const fitS = useRef(1);
  const fit = () => {
    const c = ref.current; if (!c) return;
    const b = bounds(), W = c.clientWidth, H = c.clientHeight;
    const s = Math.min(W / (b.x1 - b.x0), H / (b.y1 - b.y0));
    fitS.current = s;
    view.current = { s, ox: (W - s * (b.x1 - b.x0)) / 2 - b.x0 * s, oy: (H - s * (b.y1 - b.y0)) / 2 - b.y0 * s };
    bgKey.current = "";
  };
  // ---- navigation (boutons, clavier)
  const nav = useRef<NavApi | null>(null);
  const zoomAround = (k: number, mx?: number, my?: number) => {
    const c = ref.current, v = view.current; if (!c || !v) return;
    const s = Math.max(fitS.current * 0.2, Math.min(fitS.current * 40, v.s * k)); k = s / v.s;
    const px = mx ?? c.clientWidth / 2, py = my ?? c.clientHeight / 2;
    view.current = { s, ox: px - (px - v.ox) * k, oy: py - (py - v.oy) * k }; bgKey.current = ""; force((n) => n + 1);
  };
  nav.current = {
    zoom: (f) => zoomAround(f),
    pan: (dx, dy) => { const c = ref.current, v = view.current; if (!c || !v) return; view.current = { ...v, ox: v.ox - dx * c.clientWidth, oy: v.oy - dy * c.clientHeight }; bgKey.current = ""; force((n) => n + 1); },
    fit: () => { fit(); force((n) => n + 1); },
    center: () => {
      const c = ref.current, v = view.current; if (!c || !v) return; const b = bounds();
      view.current = { s: v.s, ox: c.clientWidth / 2 - ((b.x0 + b.x1) / 2) * v.s, oy: c.clientHeight / 2 - ((b.y0 + b.y1) / 2) * v.s }; bgKey.current = ""; force((n) => n + 1);
    },
  };

  // fond statique (murs, allées, machines) mis en cache dans un canvas hors écran
  const drawBackground = (W: number, H: number, dpr: number) => {
    const v = view.current!;
    const key = `${W}x${H}x${dpr}:${v.s.toFixed(3)}:${v.ox.toFixed(1)}:${v.oy.toFixed(1)}:${selected}`;
    if (bg.current && bgKey.current === key) return bg.current;
    const off = bg.current ?? document.createElement("canvas");
    off.width = W * dpr; off.height = H * dpr;
    const g = off.getContext("2d")!;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.fillStyle = "#f6f5f1"; g.fillRect(0, 0, W, H);
    const X = (x: number) => v.ox + x * v.s, Y = (y: number) => v.oy + y * v.s;
    const poly = (pts: [number, number][], fill?: string, stroke?: string, lw = 1) => {
      g.beginPath(); pts.forEach(([x, y], i) => (i ? g.lineTo(X(x), Y(y)) : g.moveTo(X(x), Y(y)))); g.closePath();
      if (fill) { g.fillStyle = fill; g.fill(); } if (stroke) { g.strokeStyle = stroke; g.lineWidth = lw; g.stroke(); }
    };
    if (plan) {
      g.fillStyle = "#ffffff"; g.fillRect(X(0), Y(0), plan.width_m * v.s, plan.length_m * v.s);
      for (const e of plan.elements) {
        if (e.kind === "zone") { g.fillStyle = "rgba(120,140,170,.07)"; g.fillRect(X(e.x), Y(e.y), e.w * v.s, e.h * v.s); }
        if (e.kind === "aisle") { g.fillStyle = e.main ? "rgba(46,158,91,.10)" : "rgba(46,158,91,.06)"; g.fillRect(X(e.x), Y(e.y), e.w * v.s, e.h * v.s); }
      }
      for (const e of plan.elements) {
        if (e.kind === "wall") { g.strokeStyle = "#5a5f66"; g.lineWidth = Math.max(2, (e.thickness || 0.2) * v.s); g.lineCap = "square"; g.beginPath(); g.moveTo(X(e.x1), Y(e.y1)); g.lineTo(X(e.x2), Y(e.y2)); g.stroke(); }
        if (e.kind === "pillar") { g.fillStyle = "#3a3f47"; g.fillRect(X(e.x - e.w / 2), Y(e.y - e.d / 2), e.w * v.s, e.d * v.s); }
        if (e.kind === "door") { g.fillStyle = e.exit ? "#1f8a5b" : "#c8ccd2"; const p = rectCorners(e.x, e.y, e.width, 0.25, e.rot); poly(p, g.fillStyle as string); }
      }
      const used = new Set(model.stations.flatMap((s) => s.machine_ids));
      for (const e of plan.elements) {
        if (e.kind !== "machine") continue;
        const m = e as Machine;
        poly(rectCorners(m.x, m.y, m.w, m.d, m.rot), used.has(m.id) ? "#fbfbf9" : "#eef0f2", used.has(m.id) ? "#5b6878" : "#b5bcc5", 1);
        if (!used.has(m.id)) {
          g.fillStyle = "#9aa3ad"; g.font = `${Math.max(8, Math.min(12, v.s * 0.22))}px sans-serif`; g.textAlign = "center"; g.textBaseline = "middle";
          g.fillText(MACHINE_CATALOG[m.type]?.short ?? "", X(m.x), Y(m.y));
        }
      }
    } else {
      // implantation sans plan : tables dessinées autour des postes
      for (const s of model.stations) {
        const w = 1.2, d = 0.6;
        poly(rectCorners(s.mx, s.my, w, d, s.rot ?? 0), "#fbfbf9", "#5b6878", 1);
      }
    }
    // chemins entre postes consécutifs (flux des paquets)
    g.setLineDash([4, 4]); g.strokeStyle = "rgba(59,125,216,.35)"; g.lineWidth = 1.2;
    for (let i = 0; i + 1 < model.route.length; i++) {
      const a = model.route[i], b = model.route[i + 1];
      const key = a <= b ? `${a}|${b}` : `${b}|${a}`;
      const p = model.paths?.[key]?.pts;
      const A = model.stations.find((s) => s.id === a)!, B = model.stations.find((s) => s.id === b)!;
      const pts = p && p.length > 1 ? p : [[A.x, A.y], [B.x, B.y]];
      g.beginPath(); pts.forEach(([x, y], k) => (k ? g.lineTo(X(x), Y(y)) : g.moveTo(X(x), Y(y)))); g.stroke();
    }
    g.setLineDash([]);
    // convoyeur suspendu : boucle principale, sens de marche, dérivations + aiguillages, chargement / déchargement
    const cv = model.conveyor?.enabled && model.conveyor.pts?.length ? model.conveyor : null;
    if (cv) {
      const pts = cv.pts!;
      g.strokeStyle = "rgba(123,79,160,.85)"; g.lineWidth = Math.max(2.5, v.s * 0.09); g.lineJoin = "round";
      g.beginPath(); pts.forEach(([x, y], i) => (i ? g.lineTo(X(x), Y(y)) : g.moveTo(X(x), Y(y)))); g.closePath(); g.stroke();
      g.strokeStyle = "rgba(123,79,160,.55)"; g.lineWidth = Math.max(1.2, v.s * 0.04);
      for (const sp of Object.values(cv.spurs ?? {})) {
        g.beginPath(); g.moveTo(X(sp.pt[0]), Y(sp.pt[1])); g.lineTo(X(sp.to[0]), Y(sp.to[1])); g.stroke();
        g.fillStyle = "#7b4fa0"; const r = Math.max(2.5, v.s * 0.07);
        g.beginPath(); g.moveTo(X(sp.pt[0]), Y(sp.pt[1]) - r); g.lineTo(X(sp.pt[0]) + r, Y(sp.pt[1])); g.lineTo(X(sp.pt[0]), Y(sp.pt[1]) + r); g.lineTo(X(sp.pt[0]) - r, Y(sp.pt[1])); g.fill();
      }
      const L = cv.length_m ?? 0;
      g.fillStyle = "rgba(255,255,255,.95)";
      for (let s0 = 1.5; s0 < L; s0 += 3) {     // flèches : sens de marche du rail
        const [ax, ay] = railPoint(cv, s0), [bx, by] = railPoint(cv, s0 + 0.25);
        const ang = Math.atan2(Y(by) - Y(ay), X(bx) - X(ax)), r = Math.max(3, v.s * 0.07);
        g.save(); g.translate(X(ax), Y(ay)); g.rotate(ang); g.beginPath(); g.moveTo(r, 0); g.lineTo(-r * 0.7, -r * 0.7); g.lineTo(-r * 0.7, r * 0.7); g.fill(); g.restore();
      }
      const tagR = (p: [number, number] | undefined, txt: string) => {
        if (!p) return; g.fillStyle = "#7b4fa0"; g.fillRect(X(p[0]) - 13, Y(p[1]) - 8, 26, 16);
        g.fillStyle = "#fff"; g.font = "700 9px sans-serif"; g.textAlign = "center"; g.textBaseline = "middle"; g.fillText(txt, X(p[0]), Y(p[1]));
      };
      tagR(cv.load_pt, "CHG"); tagR(cv.unload_pt, "DÉCH");
    }
    // source / sortie
    const tag = (x: number, y: number, txt: string, col: string) => {
      g.fillStyle = col; g.beginPath(); g.arc(X(x), Y(y), Math.max(7, v.s * 0.28), 0, Math.PI * 2); g.fill();
      g.fillStyle = "#fff"; g.font = `700 ${Math.max(8, v.s * 0.22)}px sans-serif`; g.textAlign = "center"; g.textBaseline = "middle"; g.fillText(txt, X(x), Y(y));
    };
    tag(model.source.x, model.source.y, "IN", "#1f4e79");
    tag(model.sink.x, model.sink.y, "OUT", "#2e9e5b");
    bg.current = off; bgKey.current = key;
    return off;
  };

  useEffect(() => {
    const c = ref.current; if (!c) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    const W = c.clientWidth, H = c.clientHeight;
    if (c.width !== W * dpr || c.height !== H * dpr) { c.width = W * dpr; c.height = H * dpr; bgKey.current = ""; }
    if (!view.current) fit();
    const v = view.current!;
    const g = c.getContext("2d")!;
    g.setTransform(1, 0, 0, 1, 0, 0);
    g.drawImage(drawBackground(W, H, dpr), 0, 0);
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    const X = (x: number) => v.ox + x * v.s, Y = (y: number) => v.oy + y * v.s;
    const s = v.s;
    // postes : plateau coloré selon l'état + étiquette
    model.stations.forEach((st, i) => {
      const state = STATION_STATES[frame?.stations[i] ?? 1] ?? "starved";
      const col = STATE_COLOR[state];
      const pts = rectCorners(st.mx, st.my, 1.0, 0.45, st.rot ?? 0);
      g.beginPath(); pts.forEach(([x, y], k) => (k ? g.lineTo(X(x), Y(y)) : g.moveTo(X(x), Y(y)))); g.closePath();
      g.globalAlpha = 0.75; g.fillStyle = col; g.fill(); g.globalAlpha = 1;
      g.lineWidth = selected === st.id ? 3 : 1; g.strokeStyle = selected === st.id ? "#1f4e79" : "rgba(0,0,0,.35)"; g.stroke();
      g.fillStyle = "#1d2b38"; g.font = `700 ${Math.max(9, Math.min(13, s * 0.26))}px sans-serif`; g.textAlign = "center"; g.textBaseline = "middle";
      g.fillText(st.id, X(st.mx), Y(st.my));
      // chariot d'encours
      g.strokeStyle = "#8a7a5a"; g.lineWidth = 1; g.strokeRect(X(st.qx) - s * 0.25, Y(st.qy) - s * 0.2, s * 0.5, s * 0.4);
    });
    if (!frame) return;
    // paquets : carrés colorés par lot, empilés dans les files, quantité affichée
    const bs = Math.max(5, s * 0.22);
    // cintres du convoyeur : crochet violet (plein = chargé)
    const cr = Math.max(2, s * 0.08);
    for (const c of frame.carriers) {
      g.beginPath(); g.arc(X(c.x), Y(c.y), cr, 0, Math.PI * 2);
      g.fillStyle = c.loaded ? "#4b2a6b" : "#d9cce6"; g.fill(); g.lineWidth = 0.8; g.strokeStyle = "#fff"; g.stroke();
    }
    for (const b of frame.bundles) {
      if (b.kind === 7) {    // pièces suspendues à un cintre
        const w = Math.max(4, s * 0.16);
        g.fillStyle = lotColor(b.lot); g.fillRect(X(b.x) - w / 2, Y(b.y) + cr * 0.6, w, w * 1.1);
        if (b.rework) { g.lineWidth = 1.5; g.strokeStyle = "#d64541"; g.strokeRect(X(b.x) - w / 2, Y(b.y) + cr * 0.6, w, w * 1.1); }
        continue;
      }
      const off = b.kind === 3 || b.kind === 4 ? (b.z - 1) * bs * 0.5 : Math.min(b.z, 12) * bs * 0.38;
      const x = X(b.x) + (b.kind === 3 || b.kind === 4 ? bs * 0.6 : 0), y = Y(b.y) - off;
      g.fillStyle = lotColor(b.lot); g.fillRect(x - bs / 2, y - bs / 2, bs, bs * 0.7);
      g.lineWidth = b.rework ? 2 : 0.8; g.strokeStyle = b.rework ? "#d64541" : "rgba(255,255,255,.9)"; g.strokeRect(x - bs / 2, y - bs / 2, bs, bs * 0.7);
      if (bs >= 12 && (b.z === 0 || b.kind === 3 || b.kind === 4)) {
        g.fillStyle = "#fff"; g.font = `700 ${Math.round(bs * 0.45)}px sans-serif`; g.textAlign = "center"; g.textBaseline = "middle"; g.fillText(String(b.qty), x, y - bs * 0.15);
      }
    }
    // files trop hautes : compteur
    // acteurs : opérateurs (disque + tête) et transporteurs (chariot + charge)
    if (detail) {
      const r = Math.max(5, s * 0.2), bsz = Math.max(16, Math.min(34, s * 0.55));
      const bubble = (k: Bubble, x: number, y: number) => g.drawImage(bubbleCanvas(k), x - bsz / 2, y - r * 1.4 - bsz, bsz, bsz);
      const near = (x: number, y: number) => { let b = model.stations[0], bd = Infinity; for (const st of model.stations) { const d = (st.x - x) ** 2 + (st.y - y) ** 2; if (d < bd) { bd = d; b = st; } } return b; };
      frame.stations.forEach((code, i) => {      // panne : mécanicien de l'autre côté de la machine
        if (STATION_STATES[code] !== "down") return;
        const st = model.stations[i]; let vx = st.mx - st.x, vy = st.my - st.y; const L = Math.hypot(vx, vy) || 1; vx /= L; vy /= L;
        const mx = X(st.mx + vx * 0.7), my = Y(st.my + vy * 0.7);
        drawPerson2D(g, mx, my, r, Math.atan2(-vy, -vx), "mecanicien", STATE_COLOR.down);
        bubble("down", mx + r * 1.6, my + r * 1.2);
      });
      for (const a of frame.actors) {
        const x = X(a.x), y = Y(a.y);
        if (a.kind === "operator") {
          const moving = a.state === 1 || a.state === 4;
          const st = moving ? null : near(a.x, a.y);
          const h = st ? Math.atan2(st.my - a.y, st.mx - a.x) : a.heading;
          drawPerson2D(g, x, y, r, h, roles.get(a.id)?.role ?? "operatrice", OP_COLOR[OP_STATES[a.state] ?? "idle"] ?? "#76858b", a.state === 4);
          if (a.state === 3) bubble("setup", x, y); else if (a.state === 5) bubble("break", x, y); else if (a.state === 6) bubble("wait", x, y);
        } else {
          const w = Math.max(10, s * 0.6), hh = Math.max(7, s * 0.4);
          g.save(); g.translate(x, y); g.rotate(a.heading);
          g.fillStyle = a.load ? "#16a085" : "#7f8c8d"; g.fillRect(-w / 2, -hh / 2, w, hh);
          g.strokeStyle = "#2c3e50"; g.lineWidth = 1; g.strokeRect(-w / 2, -hh / 2, w, hh);
          g.restore();
          drawPerson2D(g, x - Math.cos(a.heading) * (w / 2 + r * 0.9), y - Math.sin(a.heading) * (w / 2 + r * 0.9), r, a.heading, "liaison", a.state === 1 || a.state === 2 ? OP_COLOR.walk : OP_COLOR.idle);
          if (a.state === 4) bubble("wait", x, y); else if (a.state === 5) bubble("break", x, y);
        }
      }
      return;
    }
    for (const a of frame.actors) {
      const x = X(a.x), y = Y(a.y);
      if (a.kind === "operator") {
        const r = Math.max(4, s * 0.17);
        const col = a.state === 1 || a.state === 4 ? "#e8a33d" : a.state === 2 || a.state === 3 ? "#1f6685" : "#76858b";
        g.fillStyle = col; g.beginPath(); g.arc(x, y, r, 0, Math.PI * 2); g.fill();
        g.fillStyle = "#d9aa87"; g.beginPath(); g.arc(x, y, r * 0.5, 0, Math.PI * 2); g.fill();
      } else {
        const w = Math.max(10, s * 0.6), h = Math.max(7, s * 0.4);
        g.save(); g.translate(x, y); g.rotate(a.heading);
        g.fillStyle = a.load ? "#16a085" : "#7f8c8d"; g.fillRect(-w / 2, -h / 2, w, h);
        g.restore();
        g.fillStyle = "#fff"; g.font = `700 ${Math.max(8, s * 0.22)}px sans-serif`; g.textAlign = "center"; g.textBaseline = "middle"; g.fillText(a.load ? String(a.load) : "T", x, y);
      }
    }
  });

  useEffect(() => {
    const c = ref.current; if (!c) return;
    const wheel = (ev: WheelEvent) => {
      ev.preventDefault(); const v = view.current; if (!v) return;
      const r = c.getBoundingClientRect(), mx = ev.clientX - r.left, my = ev.clientY - r.top;
      zoomAround(ev.deltaY > 0 ? 1 / 1.15 : 1.15, mx, my);
    };
    const ro = new ResizeObserver(() => { fit(); force((n) => n + 1); });
    ro.observe(c);
    c.addEventListener("wheel", wheel, { passive: false });
    return () => { c.removeEventListener("wheel", wheel); ro.disconnect(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [plan, model]);

  const toM = (ev: React.PointerEvent) => {
    const r = ref.current!.getBoundingClientRect(), v = view.current!;
    return [(ev.clientX - r.left - v.ox) / v.s, (ev.clientY - r.top - v.oy) / v.s];
  };
  const zoomPct = view.current ? (view.current.s / fitS.current) * 100 : 100;
  // pincement à deux doigts (tablette)
  const pts = useRef(new Map<number, { x: number; y: number }>());
  const pinch = useRef<{ d: number } | null>(null);
  return (
    <NavControls api={nav} mode="2d" zoomPct={zoomPct} className={`sim2d-wrap ${className}`}>
    <canvas ref={ref} className={`sim2d ${className}`} role="img" aria-label="Simulation 2D de l'atelier"
      onPointerDown={(ev) => {
        (ev.target as HTMLElement).setPointerCapture(ev.pointerId); pts.current.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
        if (pts.current.size === 2) { const [a, b] = [...pts.current.values()]; pinch.current = { d: Math.hypot(a.x - b.x, a.y - b.y) }; drag.current = null; return; }
        const v = view.current!; drag.current = { x: ev.clientX, y: ev.clientY, ox: v.ox, oy: v.oy, moved: false };
      }}
      onPointerCancel={(ev) => { pts.current.delete(ev.pointerId); pinch.current = null; drag.current = null; }}
      onPointerMove={(ev) => {
        if (pts.current.has(ev.pointerId)) pts.current.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
        if (pinch.current && pts.current.size === 2) {
          const [a, b] = [...pts.current.values()]; const d = Math.hypot(a.x - b.x, a.y - b.y); const r = ref.current!.getBoundingClientRect();
          if (pinch.current.d > 0) zoomAround(d / pinch.current.d, (a.x + b.x) / 2 - r.left, (a.y + b.y) / 2 - r.top);
          pinch.current.d = d; return;
        }
        const d = drag.current; if (!d || !view.current) return;
        if (Math.abs(ev.clientX - d.x) + Math.abs(ev.clientY - d.y) > 4) d.moved = true;
        if (d.moved) { view.current = { ...view.current, ox: d.ox + ev.clientX - d.x, oy: d.oy + ev.clientY - d.y }; bgKey.current = ""; force((n) => n + 1); }
      }}
      onPointerUp={(ev) => {
        pts.current.delete(ev.pointerId); if (pinch.current) { if (pts.current.size < 2) pinch.current = null; drag.current = null; return; }
        const d = drag.current; drag.current = null;
        if (d && !d.moved && onSelect) {
          const [x, y] = toM(ev);
          const hit = model.stations.find((s) => Math.hypot(s.mx - x, s.my - y) < 0.8 || Math.hypot(s.x - x, s.y - y) < 0.5);
          onSelect(hit ? hit.id : null);
        }
      }}
      onDoubleClick={() => { fit(); force((n) => n + 1); }} />
    </NavControls>
  );
}
