import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, fmt, post } from "../lib/api";
import { canManage, canWrite, useSession } from "../lib/session";
import type { Problem, ProblemRow } from "../lib/types";
import {
  CATEGORY_COLOR, MACHINE_CATALOG, MACHINE_CATEGORIES, MACHINE_SOURCES, STATUS_LABEL, ZONES, backgroundUrl, checkPlan, dimLabelAt, dimSegments, dimText, dxfToWalls, elCenter, elPoly, emptyPlan,
  fileToImage, hitTest, inventory, machineType, moveEl, resizeRoom, nearestWallAngle, newMachine, nextLabel, operatorPoint, pngToPdf, polyLen,
  r2, saveBlob, settingsOf, snapMeasure, svgToPng, uid, uploadBackground, walkRoute,
  type Aisle, type Dim, type DimMode, type Door, type El, type Machine, type MachineStatus, type OperatorSide, type P, type PlanSettings,
  type PlanSummary, type Wall, type WorkshopPlan, type Zone,
} from "../lib/workshop";

import MachineSymbol from "../components/MachineSymbol";
const PlanScene3D = lazy(() => import("../components/PlanScene3D"));

type Tool = "select" | "pan" | "erase" | "measure" | "wall" | "pillar" | "door" | "aisle" | "zone" | "machine" | "calibrate" | "background";
const TOOLS: { id: Tool; label: string; key?: string; hint: string; icon: string; dash?: boolean }[] = [
  { id: "select", label: "Sélection", key: "V", icon: "M5 3l13 8-5.5 1.5L10 18z", hint: "Touchez un élément pour le choisir · Maj+clic ou « multiple » pour en ajouter · glissez dans le vide pour encadrer · glissez la sélection pour la déplacer · poignées : taille ● et rotation ◯." },
  { id: "pan", label: "Main", key: "H", icon: "M12 3v18M3 12h18M12 3l-3 3M12 3l3 3M12 21l-3-3M12 21l3-3M3 12l3-3M3 12l3 3M21 12l-3-3M21 12l-3 3", hint: "Glissez pour vous déplacer dans le plan (ou deux doigts, molette pour zoomer)." },
  { id: "erase", label: "Gomme", key: "E", icon: "M15 4l5 5-10 10H5l-2-2zM9 10l5 5M10 19h10", hint: "Touchez un élément pour le supprimer, ou glissez sur plusieurs. Ctrl+Z pour annuler." },
  { id: "measure", label: "Mesure", key: "M", icon: "M3 16L16 3l5 5L8 21zM7 12l2 2M10 9l2 2M13 6l2 2", hint: "Touchez deux points (aimantés sur les coins et centres des machines, les murs…)." },
  { id: "wall", label: "Mur", icon: "M4 20L20 4", hint: "Glissez d'un point à l'autre pour tracer un mur (aimanté aux extrémités voisines)." },
  { id: "pillar", label: "Poteau", icon: "M8 8h8v8H8z", hint: "Touchez pour poser un poteau." },
  { id: "door", label: "Porte / issue", icon: "M4 20h16M7 20V6a13 13 0 0 1 13 14", hint: "Touchez près d'un mur : la porte se met dans l'axe du mur." },
  { id: "aisle", label: "Allée", icon: "M3 7h18M3 17h18M5 12h3M10.5 12h3M16 12h3", hint: "Glissez pour tracer une allée de circulation (rectangle)." },
  { id: "zone", label: "Zone", icon: "M4 4h16v16H4z", dash: true, hint: "Glissez pour tracer une zone (coupe, montage…)." },
  { id: "machine", label: "Machine", icon: "M3 13h18v3H3zM13 6h6v7h-6zM6 8h7v2", hint: "Choisissez une machine dans la bibliothèque puis touchez le plan pour la poser (ou glissez-la depuis la liste)." },
  { id: "calibrate", label: "Calibrer", icon: "M3 12h18M3 8v8M21 8v8M8 10v4M13 10v4", hint: "Touchez deux points du fond de plan dont vous connaissez la distance réelle." },
  { id: "background", label: "Déplacer le fond", icon: "M3 5h18v14H3zM3 16l5-5 4 4 3-3 6 6", hint: "Glissez pour caler le fond de plan sur la salle." },
];
const MEASURE_MODES: { id: DimMode; label: string; hint: string }[] = [
  { id: "dist", label: "Distance", hint: "Touchez deux points." },
  { id: "chain", label: "Chaîne", hint: "Touchez les points un par un ; double-clic, Entrée ou « Terminer » pour finir." },
  { id: "area", label: "Surface", hint: "Touchez deux coins opposés du rectangle (ou glissez)." },
  { id: "walk", label: "Chemin à pied", hint: "Touchez une machine puis une autre : chemin le plus court à pied, en contournant murs, poteaux et machines." },
];
const draftKey = (org: string, id?: string) => `tlb.plan.brouillon.${org}.${id || "nouveau"}`;
const gammeDraftKey = (org: string) => `tlb.gamme.brouillon.${org}`;
const MIN_W = 2, MAX_W = 420;
const rotV = (x: number, y: number, deg: number): P => { const a = (deg * Math.PI) / 180; return [x * Math.cos(a) - y * Math.sin(a), x * Math.sin(a) + y * Math.cos(a)]; };
const Icon = ({ d, dash }: { d: string; dash?: boolean }) => (
  <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" strokeDasharray={dash ? "3 2.5" : undefined} aria-hidden="true"><path d={d} /></svg>
);

type DragMode = "pan" | "move" | "wallEnd" | "draw" | "bg" | "pinch" | "marquee" | "resize" | "rotate" | "erase" | "dimPt" | "measure";
interface Drag {
  areaHit?: string;
  mode: DragMode;
  sx: number; sy: number; cx: number; cy: number; id?: string; end?: 1 | 2; idx?: number; orig?: El; origs?: El[]; view?: View;
  bg?: { x: number; y: number }; dist?: number; moved?: boolean; before?: WorkshopPlan; changed?: boolean;
}
interface View { x: number; y: number; w: number }
interface Handle { kind: "resize" | "rotate" | "end1" | "end2" | "pt"; p: P; idx?: number }

export default function WorkshopPlanPage() {
  const { currentOrg } = useSession();
  const org = currentOrg!;
  const writable = canWrite(org);
  const nav = useNavigate();
  const [params, setParams] = useSearchParams();
  const planId = params.get("id") || "";
  const [plans, setPlans] = useState<PlanSummary[] | null>(null);
  const [plan, setPlanState] = useState<WorkshopPlan>(() => emptyPlan());
  const [serverAt, setServerAt] = useState<string | null>(null);
  const [restore, setRestore] = useState<WorkshopPlan | null>(null);
  const [tool, setToolState] = useState<Tool>("select");
  const [armed, setArmed] = useState("piqueuse_plate");
  const [zoneKind, setZoneKind] = useState("montage");
  const [sel, setSel] = useState<string[]>([]);
  const [multi, setMulti] = useState(false);
  const [hover, setHover] = useState<string | null>(null);
  const [marquee, setMarquee] = useState<[P, P] | null>(null);
  const [view, setView] = useState<View>({ x: -1, y: -1, w: 32 });
  const [aspect, setAspect] = useState(0.62);
  const [bgUrl, setBgUrl] = useState<string | null>(null);
  const [calib, setCalib] = useState<P[]>([]);
  const [calibDist, setCalibDist] = useState("");
  const [preview, setPreview] = useState<El | null>(null);
  const [msg, setMsg] = useState<{ kind: "ok" | "err" | "warn"; text: string } | null>(null);
  const [busy, setBusy] = useState("");
  const [dirty, setDirty] = useState(false);
  const [showChecks, setShowChecks] = useState(true);
  const [view3d, setView3d] = useState(false);
  // outil Mesure
  const [mMode, setMMode] = useState<DimMode>("dist");
  const [mPts, setMPts] = useState<P[]>([]);
  const [mCursor, setMCursor] = useState<{ p: P; snapped: boolean } | null>(null);
  const [mDone, setMDone] = useState<Dim | null>(null);
  const [walkA, setWalkA] = useState<string | null>(null);
  const [keepDim, setKeepDim] = useState(() => localStorage.getItem("tlb.plan.keepDim") === "1");
  const [, setTick] = useState(0);
  const undo = useRef<WorkshopPlan[]>([]);
  const redo = useRef<WorkshopPlan[]>([]);
  const svgRef = useRef<SVGSVGElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const drag = useRef<Drag | null>(null);
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const base = `/v1/orgs/${org.id}`;
  const st = settingsOf(plan);
  const S = useMemo(() => new Set(sel), [sel]);

  const resetMeasure = () => { setMPts([]); setMDone(null); setWalkA(null); setMCursor(null); };
  const setTool = (t: Tool) => { setToolState(t); setCalib([]); resetMeasure(); setHover(null); setPreview(null); };

  // ---------------------------------------------------------------- chargement
  const fit = useCallback((p: WorkshopPlan) => {
    const a = (wrapRef.current?.clientHeight || 500) / (wrapRef.current?.clientWidth || 800);
    const w = Math.max(p.width_m + 2, (p.length_m + 2) / a);
    setView({ x: -1 - (w - p.width_m - 2) / 2, y: -1, w });
  }, []);

  useEffect(() => {
    api<PlanSummary[]>(`${base}/workshop-plans`).then(setPlans).catch((e) => setMsg({ kind: "err", text: (e as Error).message }));
  }, [base]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      undo.current = []; redo.current = []; setSel([]); setDirty(false); setRestore(null); resetMeasure();
      let p: WorkshopPlan;
      if (planId) {
        try { p = await api<WorkshopPlan>(`${base}/workshop-plans/${planId}`); }
        catch (e) { setMsg({ kind: "err", text: (e as Error).message }); return; }
        setServerAt(p.updated_at ?? null);
      } else {
        p = emptyPlan(); setServerAt(null);
      }
      if (cancelled) return;
      p = { ...p, width_m: Number(p.width_m), length_m: Number(p.length_m), settings: { ...settingsOf(p) } };
      setPlanState(p); fit(p);
      try {
        const raw = localStorage.getItem(draftKey(org.id, planId));
        if (raw) {
          const d = JSON.parse(raw) as { plan: WorkshopPlan; savedAt: string };
          if (!p.updated_at || new Date(d.savedAt) > new Date(p.updated_at)) setRestore(d.plan);
        }
      } catch { /* brouillon illisible */ }
    })();
    return () => { cancelled = true; };
  }, [planId, base, org.id, fit]);

  useEffect(() => {
    let url: string | null = null, cancelled = false;
    setBgUrl(null);
    if (plan.background?.path) backgroundUrl(plan.background.path).then((u) => { if (cancelled) URL.revokeObjectURL(u); else { url = u; setBgUrl(u); } })
      .catch((e) => setMsg({ kind: "warn", text: (e as Error).message }));
    return () => { cancelled = true; if (url) URL.revokeObjectURL(url); };
  }, [plan.background?.path]);

  useEffect(() => {
    const el = wrapRef.current; if (!el) return;
    const ro = new ResizeObserver(() => setAspect(el.clientHeight / Math.max(1, el.clientWidth)));
    ro.observe(el); return () => ro.disconnect();
  }, []);

  // brouillon local (enregistré à chaque modification)
  useEffect(() => {
    if (!dirty) return;
    const t = setTimeout(() => localStorage.setItem(draftKey(org.id, planId), JSON.stringify({ plan, savedAt: new Date().toISOString() })), 400);
    return () => clearTimeout(t);
  }, [plan, dirty, org.id, planId]);
  useEffect(() => { localStorage.setItem("tlb.plan.keepDim", keepDim ? "1" : "0"); }, [keepDim]);

  // ---------------------------------------------------------------- historique (annuler / rétablir pour toutes les actions)
  const commit = useCallback((next: WorkshopPlan | ((p: WorkshopPlan) => WorkshopPlan)) => {
    setPlanState((cur) => {
      const n = typeof next === "function" ? next(cur) : next;
      if (n === cur) return cur;
      undo.current.push(cur); if (undo.current.length > 100) undo.current.shift();
      redo.current = [];
      return n;
    });
    setDirty(true);
  }, []);
  const pushUndo = (before: WorkshopPlan) => { undo.current.push(before); if (undo.current.length > 100) undo.current.shift(); redo.current = []; setDirty(true); setTick((t) => t + 1); };
  const setEls = (fn: (els: El[]) => El[]) => commit((p) => ({ ...p, elements: fn(p.elements) }));
  const updEl = (id: string, patch: Partial<El>) => setEls((els) => els.map((e) => (e.id === id ? ({ ...e, ...patch } as El) : e)));
  const doUndo = () => { const prev = undo.current.pop(); if (prev) { setPlanState((cur) => { redo.current.push(cur); return prev; }); setDirty(true); setSel((s) => s.filter((id) => prev.elements.some((e) => e.id === id))); } };
  const doRedo = () => { const nx = redo.current.pop(); if (nx) { setPlanState((cur) => { undo.current.push(cur); return nx; }); setDirty(true); setSel((s) => s.filter((id) => nx.elements.some((e) => e.id === id))); } };

  const selected = sel.length === 1 ? plan.elements.find((e) => e.id === sel[0]) ?? null : null;
  const selEls = plan.elements.filter((e) => S.has(e.id));
  const issues = useMemo(() => checkPlan(plan), [plan]);
  const issueIds = useMemo(() => new Set(issues.filter((i) => i.level !== "info").flatMap((i) => i.ids)), [issues]);
  const machines = plan.elements.filter((e): e is Machine => e.kind === "machine");

  // ---------------------------------------------------------------- géométrie écran
  const vh = view.w * aspect;
  const toM = (cx: number, cy: number): P => {
    const svg = svgRef.current!; const pt = svg.createSVGPoint(); pt.x = cx; pt.y = cy;
    const m = pt.matrixTransform(svg.getScreenCTM()!.inverse()); return [m.x, m.y];
  };
  const snapV = (v: number) => (st.snap ? Math.round(v / st.grid) * st.grid : Math.round(v * 100) / 100);
  const snapP = (p: P): P => [r2(snapV(p[0])), r2(snapV(p[1]))];
  const snapToWallEnds = (p: P, except?: string): P => {
    let best: P | null = null, bd = 0.3;
    for (const e of plan.elements) if (e.kind === "wall" && e.id !== except)
      for (const q of [[e.x1, e.y1], [e.x2, e.y2]] as P[]) { const d = Math.hypot(q[0] - p[0], q[1] - p[1]); if (d < bd) { bd = d; best = q; } }
    return best ?? snapP(p);
  };
  const zoomAt = (factor: number, cx?: number, cy?: number) => {
    setView((v) => {
      const w = Math.min(MAX_W, Math.max(MIN_W, v.w * factor));
      const [mx, my] = cx != null && cy != null ? toM(cx, cy) : [v.x + v.w / 2, v.y + (v.w * aspect) / 2];
      const k = w / v.w;
      return { w, x: mx - (mx - v.x) * k, y: my - (my - v.y) * k };
    });
  };
  const hr = Math.max(0.06, view.w / 110);           // rayon des poignées (m)
  const tol = Math.max(0.12, view.w / 120);          // tolérance de touche (m)
  const measureSnap = (p: P, free = false): { p: P; snapped: boolean } => {
    if (!free) { const s = snapMeasure(plan.elements, p, Math.max(0.2, view.w / 45)); if (s) return { p: s.p, snapped: true }; }
    return { p: st.snap && !free ? snapP(p) : [r2(p[0]), r2(p[1])], snapped: false };
  };

  // poignées de l'élément sélectionné (seul)
  const handles: Handle[] = (() => {
    if (!selected || !writable || tool !== "select" || view3d) return [];
    const e = selected;
    if (e.kind === "machine") {
      const [rx, ry] = rotV(e.w / 2, e.d / 2, e.rot), [ux, uy] = rotV(0, -e.d / 2 - Math.max(0.35, hr * 4), e.rot);
      return [{ kind: "resize", p: [e.x + rx, e.y + ry] }, { kind: "rotate", p: [e.x + ux, e.y + uy] }];
    }
    if (e.kind === "door") {
      const [rx, ry] = rotV(e.width / 2, 0, e.rot), [ux, uy] = rotV(0, Math.max(0.5, hr * 5), e.rot);
      return [{ kind: "resize", p: [e.x + rx, e.y + ry] }, { kind: "rotate", p: [e.x + ux, e.y + uy] }];
    }
    if (e.kind === "pillar") return [{ kind: "resize", p: [e.x + e.w / 2, e.y + e.d / 2] }];
    if (e.kind === "aisle" || e.kind === "zone") return [{ kind: "resize", p: [e.x + e.w, e.y + e.h] }];
    if (e.kind === "wall") return [{ kind: "end1", p: [e.x1, e.y1] }, { kind: "end2", p: [e.x2, e.y2] }];
    if (e.kind === "dim") return e.pts.map((p, i) => ({ kind: "pt" as const, p, idx: i }));
    return [];
  })();

  // ---------------------------------------------------------------- mesure
  const finishMeasure = (d: Omit<Dim, "id" | "kind">) => {
    const dim: Dim = { id: uid(), kind: "dim", ...d };
    if (keepDim && writable) { setEls((els) => [...els, dim]); setMDone(null); setMsg({ kind: "ok", text: `Cote ajoutée au plan : ${dimText(dim)}.` }); }
    else setMDone(dim);
    setMPts([]); setWalkA(null);
  };
  const keepCurrent = () => { if (!mDone || !writable) return; const d = { ...mDone, id: uid() }; setEls((els) => [...els, d]); setMDone(null); setMsg({ kind: "ok", text: `Cote ajoutée au plan : ${dimText(d)}.` }); };
  const measureTap = (raw: P, free: boolean) => {
    if (mMode === "walk") {
      const hit = hitTest(plan.elements, raw[0], raw[1], tol);
      if (!hit || hit.kind !== "machine") { setMsg({ kind: "warn", text: "Chemin à pied : touchez une machine." }); return; }
      if (!walkA || walkA === hit.id) { setWalkA(hit.id); setMDone(null); setMsg(null); return; }
      const r = walkRoute(plan, walkA, hit.id);
      if (!r) { setMsg({ kind: "err", text: "Aucun passage à pied entre ces deux machines (murs, poteaux ou machines bloquent le chemin)." }); setWalkA(null); return; }
      const a = plan.elements.find((e) => e.id === walkA) as Machine;
      finishMeasure({ mode: "walk", pts: r.pts, note: `${a.label} → ${hit.label}` });
      setMsg({ kind: "ok", text: `Chemin à pied ${a.label} → ${hit.label} : ${fmt.n(r.length, 1)} m (à vol d'oiseau ${fmt.n(Math.hypot(r.pts[0][0] - r.pts[r.pts.length - 1][0], r.pts[0][1] - r.pts[r.pts.length - 1][1]), 1)} m).` });
      return;
    }
    const p = measureSnap(raw, free).p;
    if (mDone) setMDone(null);
    if (mMode === "chain") { setMPts((pts) => [...pts, p]); return; }
    if (mPts.length === 0) { setMPts([p]); return; }
    finishMeasure({ mode: mMode, pts: [mPts[0], p] });
  };
  const finishChain = () => { if (mMode === "chain" && mPts.length >= 2) finishMeasure({ mode: "chain", pts: mPts }); };

  // ---------------------------------------------------------------- édition
  const removeIds = useCallback((ids: string[]) => {
    if (!writable || !ids.length) return;
    const set = new Set(ids);
    setEls((els) => els.filter((x) => !set.has(x.id))); setSel([]);
  }, [writable]); // eslint-disable-line react-hooks/exhaustive-deps
  const duplicateIds = useCallback((ids: string[]) => {
    if (!writable) return;
    const src = plan.elements.filter((x) => ids.includes(x.id)); if (!src.length) return;
    let labelEls = plan.elements;
    const out: El[] = src.map((e) => {
      let off: P = [0.5, 0.5];
      if (src.length === 1 && e.kind === "machine") { const o = Math.max(e.w, 0.6) + 0.2; off = Math.abs(Math.sin((e.rot * Math.PI) / 180)) > 0.7 ? [0, o] : [o, 0]; }
      let n = { ...moveEl(e, off[0], off[1]), id: uid() } as El;
      if (n.kind === "machine") { n = { ...n, label: nextLabel(labelEls), ws_id: undefined }; labelEls = [...labelEls, n]; }
      return n;
    });
    setEls((els) => [...els, ...out]); setSel(out.map((e) => e.id));
  }, [plan.elements, writable]); // eslint-disable-line react-hooks/exhaustive-deps
  const rotateIds = useCallback((ids: string[], deg: number) => {
    setEls((els) => els.map((e) => (ids.includes(e.id) && (e.kind === "machine" || e.kind === "door") ? { ...e, rot: ((Math.round(e.rot + deg) % 360) + 360) % 360 } : e)));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const alignIds = (ids: string[], axis: "x" | "y") => {
    const ms = plan.elements.filter((e): e is Machine => ids.includes(e.id) && e.kind === "machine"); if (ms.length < 2) return;
    const v = r2(ms.reduce((a, m) => a + m[axis], 0) / ms.length);
    setEls((els) => els.map((e) => (ids.includes(e.id) && e.kind === "machine" ? { ...e, [axis]: v } : e)));
  };
  const placeAt = (p: P, type = armed) => {
    if (!writable) return;
    const m = newMachine(type, ...snapP(p), nextLabel(plan.elements));
    setEls((els) => [...els, m]); setSel([m.id]);
  };

  // ---------------------------------------------------------------- interactions (souris, doigt, stylet)
  const onDown = (e: React.PointerEvent<SVGSVGElement>) => {
    (e.currentTarget as Element).setPointerCapture?.(e.pointerId);
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.current.size === 2) {
      // deuxième doigt : on annule le geste en cours et on passe en zoom / déplacement
      const d0 = drag.current;
      if (d0?.before && d0.changed) setPlanState(d0.before);
      setMarquee(null); setPreview(null);
      const [a, b] = [...pointers.current.values()];
      drag.current = { mode: "pinch", sx: (a.x + b.x) / 2, sy: (a.y + b.y) / 2, cx: 0, cy: 0, view, dist: Math.hypot(a.x - b.x, a.y - b.y) };
      return;
    }
    const [mx, my] = toM(e.clientX, e.clientY);
    const d: Drag = { mode: "pan", sx: e.clientX, sy: e.clientY, cx: mx, cy: my, view };
    const middle = e.button === 1 || e.button === 2;
    if (middle || tool === "pan" || !writable) {
      if (!writable && tool !== "pan" && !middle) { const hit = hitTest(plan.elements, mx, my, tol); setSel(hit ? [hit.id] : []); }
      drag.current = d; return;
    }
    if (tool === "select") {
      // 1) poignées
      for (const h of handles) if (Math.hypot(h.p[0] - mx, h.p[1] - my) <= hr * 1.8) {
        const el = selected!;
        if (h.kind === "end1" || h.kind === "end2") drag.current = { ...d, mode: "wallEnd", id: el.id, end: h.kind === "end1" ? 1 : 2, orig: el, before: plan };
        else if (h.kind === "pt") drag.current = { ...d, mode: "dimPt", id: el.id, idx: h.idx, orig: el, before: plan };
        else drag.current = { ...d, mode: h.kind, id: el.id, orig: el, before: plan };
        return;
      }
      const hit = hitTest(plan.elements, mx, my, tol);
      const additive = e.shiftKey || e.ctrlKey || e.metaKey || multi;
      // zone / allée non sélectionnée : glisser dessus encadre les machines posées dessus (un simple toucher la sélectionne)
      if (hit && (hit.kind === "zone" || hit.kind === "aisle") && !S.has(hit.id) && !additive) {
        setSel([]);
        drag.current = { ...d, mode: "marquee", areaHit: hit.id }; setMarquee([[mx, my], [mx, my]]);
        return;
      }
      if (hit) {
        if (additive) { setSel((s) => (s.includes(hit.id) ? s.filter((x) => x !== hit.id) : [...s, hit.id])); drag.current = null; return; }
        const ids = S.has(hit.id) ? sel : [hit.id];
        if (!S.has(hit.id)) setSel([hit.id]);
        drag.current = { ...d, mode: "move", id: hit.id, origs: plan.elements.filter((x) => ids.includes(x.id)), before: plan };
        return;
      }
      if (!additive) setSel([]);
      drag.current = { ...d, mode: "marquee" }; setMarquee([[mx, my], [mx, my]]);
      return;
    }
    if (tool === "erase") {
      const hit = hitTest(plan.elements, mx, my, tol);
      drag.current = { ...d, mode: "erase", before: plan, changed: !!hit };
      if (hit) { setPlanState((p) => ({ ...p, elements: p.elements.filter((x) => x.id !== hit.id) })); setSel((s) => s.filter((x) => x !== hit.id)); setHover(null); }
      return;
    }
    if (tool === "measure") {
      drag.current = { ...d, mode: "measure" };
      if ((mMode === "dist" || mMode === "area") && mPts.length === 0) measureTap([mx, my], e.altKey);
      return;
    }
    if (tool === "wall" || tool === "aisle" || tool === "zone") {
      const p = tool === "wall" ? snapToWallEnds([mx, my]) : snapP([mx, my]);
      drag.current = { ...d, mode: "draw", cx: p[0], cy: p[1] }; return;
    }
    if (tool === "background") { if (plan.background) drag.current = { ...d, mode: "bg", bg: { x: plan.background.x, y: plan.background.y }, before: plan }; return; }
    drag.current = { ...d, mode: "pan", moved: false };
  };
  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    if (!pointers.current.has(e.pointerId)) {
      // survol (souris) : surbrillance gomme, curseur de mesure
      if (e.pointerType === "mouse" && svgRef.current) {
        const [mx, my] = toM(e.clientX, e.clientY);
        if (tool === "erase") { const h = hitTest(plan.elements, mx, my, tol); setHover(h?.id ?? null); }
        else if (tool === "measure") { if (mMode === "walk") { const h = hitTest(plan.elements, mx, my, tol); setHover(h?.kind === "machine" ? h.id : null); } else setMCursor(measureSnap([mx, my], e.altKey)); }
      }
      return;
    }
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    const d = drag.current; if (!d) return;
    if (d.mode === "pinch" && pointers.current.size >= 2 && d.view) {
      const [a, b] = [...pointers.current.values()];
      const dist = Math.hypot(a.x - b.x, a.y - b.y), mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
      const r = svgRef.current!.getBoundingClientRect();
      const k = Math.min(MAX_W / d.view.w, Math.max(MIN_W / d.view.w, (d.dist || 1) / Math.max(1, dist)));
      const w = d.view.w * k, ppm = r.width / d.view.w;
      const ax = d.view.x + (d.sx - r.left) / ppm, ay = d.view.y + (d.sy - r.top) / ppm;
      setView({ w, x: ax - (mid.x - r.left) * (w / r.width), y: ay - (mid.y - r.top) * (w / r.width) });
      return;
    }
    const [mx, my] = toM(e.clientX, e.clientY);
    if (Math.hypot(e.clientX - d.sx, e.clientY - d.sy) > 4) d.moved = true;
    const setEl = (id: string, el: El) => { d.changed = true; setPlanState((p) => ({ ...p, elements: p.elements.map((x) => (x.id === id ? el : x)) })); };
    if (d.mode === "pan" && d.view) {
      const r = svgRef.current!.getBoundingClientRect(); const k = d.view.w / r.width;
      setView({ ...d.view, x: d.view.x - (e.clientX - d.sx) * k, y: d.view.y - (e.clientY - d.sy) * k });
    } else if (d.mode === "move" && d.origs && d.moved) {
      const ref = d.origs.find((x) => x.id === d.id) ?? d.origs[0];
      const [ox, oy] = elCenter(ref);
      const [nx, ny] = snapP([ox + mx - d.cx, oy + my - d.cy]);
      const dx = nx - ox, dy = ny - oy;
      const moved = new Map(d.origs.map((o) => [o.id, moveEl(o, dx, dy)]));
      d.changed = true;
      setPlanState((p) => ({ ...p, elements: p.elements.map((x) => moved.get(x.id) ?? x) }));
    } else if (d.mode === "wallEnd" && d.orig?.kind === "wall") {
      const [px, py] = snapToWallEnds([mx, my], d.id);
      setEl(d.id!, { ...d.orig, ...(d.end === 1 ? { x1: px, y1: py } : { x2: px, y2: py }) });
    } else if (d.mode === "dimPt" && d.orig?.kind === "dim" && d.idx != null) {
      const p = measureSnap([mx, my], e.altKey).p;
      setEl(d.id!, { ...d.orig, pts: d.orig.pts.map((q, i) => (i === d.idx ? p : q)) });
    } else if (d.mode === "resize" && d.orig) {
      const o = d.orig;
      if (o.kind === "machine") {
        const [fx, fy] = ((): P => { const [a, b] = rotV(-o.w / 2, -o.d / 2, o.rot); return [o.x + a, o.y + b]; })();
        const [lx, ly] = rotV(mx - fx, my - fy, -o.rot);
        const w = Math.max(0.2, r2(snapV(lx))), dd = Math.max(0.2, r2(snapV(ly)));
        const [cx, cy] = rotV(w / 2, dd / 2, o.rot);
        setEl(o.id, { ...o, w, d: dd, x: r2(fx + cx), y: r2(fy + cy) });
      } else if (o.kind === "pillar") {
        const fx = o.x - o.w / 2, fy = o.y - o.d / 2, w = Math.max(0.1, r2(snapV(mx - fx))), dd = Math.max(0.1, r2(snapV(my - fy)));
        setEl(o.id, { ...o, w, d: dd, x: r2(fx + w / 2), y: r2(fy + dd / 2) });
      } else if (o.kind === "door") {
        const [lx] = rotV(mx - o.x, my - o.y, -o.rot);
        setEl(o.id, { ...o, width: Math.max(0.6, r2(snapV(Math.abs(lx) * 2))) });
      } else if (o.kind === "aisle" || o.kind === "zone") {
        setEl(o.id, { ...o, w: Math.max(0.2, r2(snapV(mx - o.x))), h: Math.max(0.2, r2(snapV(my - o.y))) });
      }
    } else if (d.mode === "rotate" && d.orig && (d.orig.kind === "machine" || d.orig.kind === "door")) {
      const o = d.orig;
      const ang = (Math.atan2(my - o.y, mx - o.x) * 180) / Math.PI + (o.kind === "machine" ? 90 : -90);
      const rot = e.altKey ? Math.round(ang) : Math.round(ang / 15) * 15;
      setEl(o.id, { ...o, rot: ((rot % 360) + 360) % 360 });
    } else if (d.mode === "marquee") {
      setMarquee([[d.cx, d.cy], [mx, my]]);
    } else if (d.mode === "erase") {
      const hit = hitTest(plan.elements, mx, my, tol);
      if (hit) { d.changed = true; setPlanState((p) => ({ ...p, elements: p.elements.filter((x) => x.id !== hit.id) })); setSel((s) => s.filter((x) => x !== hit.id)); }
    } else if (d.mode === "measure") {
      if (mMode !== "walk") setMCursor(measureSnap([mx, my], e.altKey));
    } else if (d.mode === "draw") {
      setPreview(drawEl(d.cx, d.cy, mx, my));
    } else if (d.mode === "bg" && d.bg && plan.background) {
      d.changed = true;
      setPlanState((p) => ({ ...p, background: p.background && { ...p.background, x: r2(d.bg!.x + mx - d.cx), y: r2(d.bg!.y + my - d.cy) } }));
    }
  };
  const drawEl = (x0: number, y0: number, mx: number, my: number): El | null => {
    if (tool === "wall") {
      let [x1, y1] = snapToWallEnds([mx, my]);
      if (Math.abs(x1 - x0) < 0.25 * Math.abs(y1 - y0)) x1 = x0; else if (Math.abs(y1 - y0) < 0.25 * Math.abs(x1 - x0)) y1 = y0; // orthogonal
      return { id: "preview", kind: "wall", x1: x0, y1: y0, x2: x1, y2: y1, thickness: 0.2 };
    }
    const [x1, y1] = snapP([mx, my]);
    const box = { x: Math.min(x0, x1), y: Math.min(y0, y1), w: r2(Math.abs(x1 - x0)), h: r2(Math.abs(y1 - y0)) };
    if (tool === "aisle") return { id: "preview", kind: "aisle", ...box, main: true };
    return { id: "preview", kind: "zone", ...box, zone: zoneKind, name: ZONES[zoneKind]?.label ?? "" };
  };
  const onUp = (e: React.PointerEvent<SVGSVGElement>) => {
    pointers.current.delete(e.pointerId);
    const d = drag.current;
    if (d?.mode === "pinch") { if (pointers.current.size === 0) drag.current = null; return; }
    drag.current = null;
    if (!d) return;
    const [mx, my] = toM(e.clientX, e.clientY);
    if (d.before && d.changed) { pushUndo(d.before); return; }   // déplacement, poignée, gomme, fond : une seule étape d'historique
    if (d.mode === "marquee") {
      setMarquee(null);
      if (!d.moved) { if (d.areaHit) setSel([d.areaHit]); return; }
      const x0 = Math.min(d.cx, mx), x1 = Math.max(d.cx, mx), y0 = Math.min(d.cy, my), y1 = Math.max(d.cy, my);
      const inside = plan.elements.filter((el) => elPoly(el).every(([x, y]) => x >= x0 && x <= x1 && y >= y0 && y <= y1)).map((el) => el.id);
      setSel((s) => (e.shiftKey || e.ctrlKey || e.metaKey || multi ? [...new Set([...s, ...inside])] : inside));
      return;
    }
    if (d.mode === "measure") {
      if (mMode === "walk") { if (!d.moved) measureTap([mx, my], e.altKey); return; }
      if (mMode === "chain") { if (!d.moved) measureTap([mx, my], e.altKey); return; }
      // distance / surface : 2e point au relâché si on a glissé, sinon au toucher suivant
      if (d.moved && mPts.length === 1) measureTap([mx, my], e.altKey);
      else if (!d.moved && mPts.length === 1 && Math.hypot(mx - mPts[0][0], my - mPts[0][1]) > tol) measureTap([mx, my], e.altKey);
      return;
    }
    if (d.mode === "draw") {
      const el = drawEl(d.cx, d.cy, mx, my); setPreview(null);
      if (!el) return;
      const ok = el.kind === "wall" ? Math.hypot(el.x2 - el.x1, el.y2 - el.y1) >= 0.1 : (el as Aisle).w >= 0.2 && (el as Aisle).h >= 0.2;
      if (ok) { const n = { ...el, id: uid() } as El; setEls((els) => (n.kind === "zone" ? [n, ...els] : [...els, n])); setSel([n.id]); }
      return;
    }
    if (d.mode === "pan" && !d.moved && writable) {
      if (tool === "pillar") { const [x, y] = snapP([mx, my]); const n: El = { id: uid(), kind: "pillar", x, y, w: 0.4, d: 0.4 }; setEls((els) => [...els, n]); setSel([n.id]); }
      else if (tool === "door") {
        const w = nearestWallAngle(plan.elements, mx, my);
        const [x, y] = w ? [w.x, w.y] : snapP([mx, my]);
        const n: El = { id: uid(), kind: "door", x, y, width: 1.2, rot: w ? r2(w.angle) : 0, exit: true };
        setEls((els) => [...els, n]); setSel([n.id]);
      } else if (tool === "machine") placeAt([mx, my]);
      else if (tool === "calibrate") {
        const next = calib.length >= 2 ? [[mx, my] as P] : [...calib, [mx, my] as P];
        setCalib(next);
      }
    }
  };
  const onWheel = (e: React.WheelEvent) => { zoomAt(e.deltaY > 0 ? 1.15 : 1 / 1.15, e.clientX, e.clientY); };

  useEffect(() => {
    const el = svgRef.current; if (!el) return;
    const stop = (ev: WheelEvent) => ev.preventDefault();
    const ctx = (ev: MouseEvent) => ev.preventDefault();
    el.addEventListener("wheel", stop, { passive: false }); el.addEventListener("contextmenu", ctx);
    return () => { el.removeEventListener("wheel", stop); el.removeEventListener("contextmenu", ctx); };
  }, [view3d]);

  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      const t = ev.target as HTMLElement;
      if (t && (t.tagName === "INPUT" || t.tagName === "SELECT" || t.tagName === "TEXTAREA")) return;
      const k = ev.key.toLowerCase(), mod = ev.ctrlKey || ev.metaKey;
      if (mod && k === "z") { ev.preventDefault(); if (ev.shiftKey) doRedo(); else doUndo(); return; }
      if (mod && k === "y") { ev.preventDefault(); doRedo(); return; }
      if (mod && k === "a" && !view3d) { ev.preventDefault(); setTool("select"); setSel(plan.elements.map((x) => x.id)); return; }
      if (ev.key === "Enter" && tool === "measure") { finishChain(); return; }
      if (ev.key === "Escape") {
        if (tool === "measure" && (mPts.length || mDone || walkA)) { resetMeasure(); return; }
        if (sel.length) { setSel([]); return; }
        setTool("select"); return;
      }
      if (sel.length && writable && (ev.key === "Delete" || ev.key === "Backspace")) { ev.preventDefault(); removeIds(sel); return; }
      if (!mod && !ev.altKey && !view3d) {
        if (k === "v") { setTool("select"); return; }
        if (k === "h") { setTool("pan"); return; }
        if (k === "e" && writable) { setTool("erase"); return; }
        if (k === "m") { setTool("measure"); return; }
      }
      if (!sel.length || !writable) return;
      if (mod && k === "d") { ev.preventDefault(); duplicateIds(sel); }
      else if (k === "r" && !mod) rotateIds(sel, ev.shiftKey ? -15 : 90);
      else if (ev.key.startsWith("Arrow")) {
        ev.preventDefault();
        const s = ev.shiftKey ? 0.5 : st.grid;
        const [dx, dy] = { ArrowLeft: [-s, 0], ArrowRight: [s, 0], ArrowUp: [0, -s], ArrowDown: [0, s] }[ev.key] as P;
        setEls((els) => els.map((x) => (S.has(x.id) ? moveEl(x, dx, dy) : x)));
      }
    };
    window.addEventListener("keydown", onKey); return () => window.removeEventListener("keydown", onKey);
  }); // eslint-disable-line react-hooks/exhaustive-deps

  // ---------------------------------------------------------------- fond de plan
  const onBackground = async (file: File) => {
    if (!writable) return;
    setBusy("bg"); setMsg(null);
    try {
      if (/\.dxf$/i.test(file.name)) {
        const unit = (window.prompt("Unité du DXF (mm, cm, m) — laisser vide pour la lire dans le fichier :", "") || "auto").trim().toLowerCase();
        const r = await dxfToWalls(await file.text(), (["mm", "cm", "m"].includes(unit) ? unit : "auto") as "auto");
        commit((p) => ({ ...resizeRoom(p, Math.max(p.width_m, r.width), Math.max(p.length_m, r.length)),
          elements: [...p.elements.filter((e) => !(e.kind === "wall" && plan.elements.length <= 4)), ...r.walls] }));
        setMsg({ kind: "ok", text: `${r.walls.length} murs importés du DXF (unité : ${r.unit}). Vérifiez les cotes avec l'outil Calibrer si besoin.` });
        return;
      }
      const img = await fileToImage(file);
      const path = await uploadBackground(org.id, img.blob, img.ext);
      const width_m = plan.width_m, height_m = r2((plan.width_m * img.h) / img.w);
      commit((p) => ({ ...p, background: { path, x: 0, y: 0, width_m, height_m, opacity: 0.55, source: img.source } }));
      setTool("calibrate");
      setMsg({ kind: "ok", text: "Fond importé. Calibrez l'échelle : touchez deux points dont vous connaissez la distance réelle (ex. une cote ou un mur)." });
    } catch (e) { setMsg({ kind: "err", text: (e as Error).message }); } finally { setBusy(""); }
  };
  const applyCalibration = () => {
    const D = Number(calibDist.replace(",", "."));
    if (calib.length !== 2 || !(D > 0) || !plan.background) return;
    const d = Math.hypot(calib[1][0] - calib[0][0], calib[1][1] - calib[0][1]);
    if (d < 0.01) return;
    const k = D / d, [px, py] = calib[0], bg = plan.background;
    commit((p) => ({ ...p, background: { ...bg, x: r2(px + (bg.x - px) * k), y: r2(py + (bg.y - py) * k), width_m: r2(bg.width_m * k), height_m: r2(bg.height_m * k) } }));
    setCalibDist(""); setTool("select");
    setMsg({ kind: "ok", text: `Échelle calibrée (×${k.toFixed(3)}). Le fond mesure maintenant ${r2(bg.width_m * k)} × ${r2(bg.height_m * k)} m.` });
  };
  const fitRoomToBackground = () => {
    const bg = plan.background; if (!bg) return;
    commit((p) => resizeRoom(p, r2(Math.max(2, bg.x + bg.width_m)), r2(Math.max(2, bg.y + bg.height_m))));
  };

  // ---------------------------------------------------------------- enregistrement
  const payload = () => ({ name: plan.name, version: plan.version, width_m: plan.width_m, length_m: plan.length_m,
    background: plan.background, elements: plan.elements, settings: plan.settings });
  const save = async () => {
    setBusy("save"); setMsg(null);
    try {
      const row = planId ? await api<WorkshopPlan>(`${base}/workshop-plans/${planId}`, { method: "PUT", body: JSON.stringify({ ...payload(), clear_background: !plan.background }) })
        : await post<WorkshopPlan>(`${base}/workshop-plans`, payload());
      localStorage.removeItem(draftKey(org.id, planId));
      setDirty(false); setServerAt(row.updated_at ?? null);
      setPlans(await api<PlanSummary[]>(`${base}/workshop-plans`));
      setMsg({ kind: "ok", text: "Plan enregistré ✓" });
      if (!planId && row.id) setParams({ id: row.id });
    } catch (e) { setMsg({ kind: "err", text: (e as Error).message }); } finally { setBusy(""); }
  };
  const duplicatePlan = async (version: "projet" | "actuel") => {
    setBusy("dup");
    try {
      const row = await post<WorkshopPlan>(`${base}/workshop-plans`, { ...payload(), version, name: `${plan.name} (${version === "projet" ? "projet" : "copie"})`.slice(0, 120) });
      setPlans(await api<PlanSummary[]>(`${base}/workshop-plans`));
      setParams({ id: row.id! }); setMsg({ kind: "ok", text: "Copie créée : vous travaillez maintenant sur la nouvelle version." });
    } catch (e) { setMsg({ kind: "err", text: (e as Error).message }); } finally { setBusy(""); }
  };
  const deletePlan = async () => {
    if (!planId || !window.confirm(`Supprimer le plan « ${plan.name} » ?`)) return;
    try { await api(`${base}/workshop-plans/${planId}`, { method: "DELETE" }); localStorage.removeItem(draftKey(org.id, planId)); setParams({}); setPlans(await api<PlanSummary[]>(`${base}/workshop-plans`)); }
    catch (e) { setMsg({ kind: "err", text: (e as Error).message }); }
  };
  const exportAs = async (kind: "png" | "pdf") => {
    if (view3d) { setView3d(false); setMsg({ kind: "warn", text: "Export du plan 2D : relancez l'export (en 3D, utilisez « Capture PNG »)." }); return; }
    if (!svgRef.current) return;
    setBusy(kind);
    try {
      const clone = svgRef.current.cloneNode(true) as SVGSVGElement;
      const vb = [-0.6, -0.6, plan.width_m + 1.2, plan.length_m + 1.2];
      clone.setAttribute("viewBox", vb.join(" "));
      const ratio = vb[2] / vb[3]; const W = 2400, H = Math.round(W / ratio);
      const png = await svgToPng(clone, W, H, bgUrl);
      const nm = plan.name.replace(/[^\p{L}\d_-]+/gu, "_").slice(0, 40) || "plan";
      const nDims = plan.elements.filter((x) => x.kind === "dim").length;
      if (kind === "png") saveBlob(png, `${nm}.png`);
      else saveBlob(await pngToPdf(png, `${org.name} — ${plan.name}`, `${plan.width_m} × ${plan.length_m} m · ${machines.length} machines${nDims ? ` · ${nDims} cote${nDims > 1 ? "s" : ""}` : ""} · version ${plan.version} · ${new Date().toLocaleDateString("fr-FR")}`, ratio), `${nm}.pdf`);
    } catch (e) { setMsg({ kind: "err", text: (e as Error).message }); } finally { setBusy(""); }
  };

  // ---------------------------------------------------------------- rendu
  const gridStep = view.w > 60 ? 5 : view.w > 25 ? 1 : st.grid >= 0.5 ? st.grid : view.w > 10 ? 0.5 : st.grid;
  const gx0 = Math.max(0, Math.floor(view.x / gridStep) * gridStep), gx1 = Math.min(plan.width_m, view.x + view.w);
  const gy0 = Math.max(0, Math.floor(view.y / gridStep) * gridStep), gy1 = Math.min(plan.length_m, view.y + vh);
  const gridLines: JSX.Element[] = [];
  if ((gx1 - gx0) / gridStep < 400 && (gy1 - gy0) / gridStep < 400) {
    for (let x = gx0; x <= gx1 + 1e-6; x += gridStep) gridLines.push(<line key={`x${x}`} x1={x} x2={x} y1={0} y2={plan.length_m} className={Math.abs(x - Math.round(x)) < 1e-6 ? "wp-grid major" : "wp-grid"} />);
    for (let y = gy0; y <= gy1 + 1e-6; y += gridStep) gridLines.push(<line key={`y${y}`} y1={y} y2={y} x1={0} x2={plan.width_m} className={Math.abs(y - Math.round(y)) < 1e-6 ? "wp-grid major" : "wp-grid"} />);
  }
  const fs = Math.max(0.16, Math.min(0.45, view.w / 90));
  const toolHint = tool === "measure" ? MEASURE_MODES.find((m) => m.id === mMode)?.hint : TOOLS.find((t) => t.id === tool)?.hint;
  const sw = Math.max(0.02, view.w / 700);   // trait fin, indépendant du zoom
  // mesure en cours (aperçu)
  const live: Dim | null = (() => {
    if (tool !== "measure" || mMode === "walk") return null;
    const cur = mCursor?.p;
    if (mMode === "chain" && mPts.length) return { id: "live", kind: "dim", mode: "chain", pts: cur ? [...mPts, cur] : mPts };
    if (mPts.length === 1 && cur) return { id: "live", kind: "dim", mode: mMode, pts: [mPts[0], cur] };
    return null;
  })();
  const cursorStyle = tool === "pan" ? "grab" : tool === "select" ? "default" : tool === "erase" ? "pointer" : "crosshair";

  const renderDim = (dm: Dim, opts: { temp?: boolean; selected?: boolean } = {}) => {
    const col = opts.temp ? "#c0392b" : dm.mode === "walk" ? "#1f8a5b" : "#1f4e79";
    const segs = dimSegments(dm); const [lx, ly] = dimLabelAt(dm);
    const txt = dimText(dm) + (dm.mode === "chain" && dm.pts.length > 2 ? ` (${dm.pts.length - 1} segments)` : "");
    const tk = Math.max(0.08, fs * 0.45);
    return (
      <g key={dm.id} data-noexport={opts.temp ? "" : undefined}>
        {dm.mode === "area" && <rect x={Math.min(dm.pts[0][0], dm.pts[1][0])} y={Math.min(dm.pts[0][1], dm.pts[1][1])} width={Math.abs(dm.pts[1][0] - dm.pts[0][0])} height={Math.abs(dm.pts[1][1] - dm.pts[0][1])} fill={col} fillOpacity={0.08} />}
        {segs.map(([a, b], i) => {
          const dx = b[0] - a[0], dy = b[1] - a[1], L = Math.hypot(dx, dy) || 1, nx = (-dy / L) * tk, ny = (dx / L) * tk;
          return <g key={i}>
            <line x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke={col} strokeWidth={opts.selected ? sw * 3 : sw * 1.8} strokeDasharray={dm.mode === "walk" ? `${tk * 1.2} ${tk * 0.8}` : undefined} />
            {dm.mode !== "walk" && dm.mode !== "area" && <><line x1={a[0] - nx} y1={a[1] - ny} x2={a[0] + nx} y2={a[1] + ny} stroke={col} strokeWidth={sw * 1.8} />
              <line x1={b[0] - nx} y1={b[1] - ny} x2={b[0] + nx} y2={b[1] + ny} stroke={col} strokeWidth={sw * 1.8} /></>}
            {dm.mode === "chain" && segs.length > 1 && <text x={(a[0] + b[0]) / 2} y={(a[1] + b[1]) / 2 - fs * 0.35} fontSize={fs * 0.7} textAnchor="middle" fill={col}>{fmt.n(Math.hypot(dx, dy), 2)}</text>}
          </g>;
        })}
        {dm.mode === "walk" && dm.pts.length > 0 && <><circle cx={dm.pts[0][0]} cy={dm.pts[0][1]} r={tk} fill={col} /><circle cx={dm.pts[dm.pts.length - 1][0]} cy={dm.pts[dm.pts.length - 1][1]} r={tk} fill={col} /></>}
        <g transform={`translate(${lx},${ly})`}>
          <rect x={-(txt.length * fs * 0.3) - fs * 0.25} y={-fs * 0.72} width={txt.length * fs * 0.6 + fs * 0.5} height={fs * 1.3} rx={fs * 0.25} fill="#fff" fillOpacity={0.92} stroke={col} strokeWidth={sw} />
          <text x={0} y={fs * 0.12} fontSize={fs * 0.95} textAnchor="middle" dominantBaseline="middle" fill={col} fontWeight={700}>{txt}</text>
        </g>
      </g>
    );
  };

  return (
    <div className="page wide">
      <div className="page-head">
        <div>
          <h1>Plan de l'atelier</h1>
          <p className="muted">Dessinez ou importez la salle, posez vos machines, puis simulez la ligne dessus depuis le <Link to="/jumeau">jumeau numérique</Link>.</p>
        </div>
        <div className="row">
          <select value={planId} onChange={(e) => { if (dirty && !window.confirm("Modifications non enregistrées (gardées en brouillon local). Changer de plan ?")) return; setParams(e.target.value ? { id: e.target.value } : {}); }}>
            <option value="">+ Nouveau plan</option>
            {(plans ?? []).map((p) => <option key={p.id} value={p.id}>{p.name} · {p.version}</option>)}
          </select>
          {writable && <button className="btn primary" disabled={busy === "save"} onClick={save}>{busy === "save" ? "Enregistrement…" : dirty || !planId ? "Enregistrer" : "Enregistré ✓"}</button>}
        </div>
      </div>
      {restore && <div className="notice warn row">Un brouillon local plus récent que la version enregistrée existe.
        <button className="btn small" onClick={() => { setPlanState(restore); setRestore(null); setDirty(true); }}>Restaurer le brouillon</button>
        <button className="link" onClick={() => { localStorage.removeItem(draftKey(org.id, planId)); setRestore(null); }}>Ignorer</button></div>}
      {msg && <p className={`notice ${msg.kind}`}>{msg.text}</p>}

      <div className="card wp-meta">
        <div className="form-grid tight4">
          <label>Nom<input value={plan.name} maxLength={120} onChange={(e) => commit((p) => ({ ...p, name: e.target.value }))} disabled={!writable} /></label>
          <label>Version<select value={plan.version} onChange={(e) => commit((p) => ({ ...p, version: e.target.value as WorkshopPlan["version"] }))} disabled={!writable}>
            <option value="actuel">Actuel</option><option value="projet">Projet</option><option value="archive">Archivé</option></select></label>
          <label>Largeur (m)<input type="number" min={2} max={400} step={0.5} value={plan.width_m} onChange={(e) => commit((p) => resizeRoom(p, +e.target.value || 2, p.length_m))} disabled={!writable} /></label>
          <label>Longueur (m)<input type="number" min={2} max={400} step={0.5} value={plan.length_m} onChange={(e) => commit((p) => resizeRoom(p, p.width_m, +e.target.value || 2))} disabled={!writable} /></label>
        </div>
        <div className="row small">
          {writable && planId && <button className="btn small" disabled={!!busy} onClick={() => duplicatePlan("projet")}>Dupliquer en version projet</button>}
          <button className="btn small" disabled={!!busy} onClick={() => exportAs("png")}>{busy === "png" ? "Export…" : "Export PNG"}</button>
          <button className="btn small" disabled={!!busy} onClick={() => exportAs("pdf")}>{busy === "pdf" ? "Export…" : "Export PDF"}</button>
          {planId && canManage(org) && <button className="link" onClick={deletePlan}>Supprimer ce plan</button>}
          {serverAt && <span className="muted">Enregistré le {fmt.date(serverAt)}</span>}
        </div>
      </div>

      <div className="wp-layout">
        {/* ------------------------------------------------ options + bibliothèque */}
        <aside className="card wp-side">
          <h3>Options de dessin</h3>
          {tool === "zone" && <label>Type de zone<select value={zoneKind} onChange={(e) => setZoneKind(e.target.value)}>
            {Object.entries(ZONES).map(([k, z]) => <option key={k} value={k}>{z.label}</option>)}</select></label>}
          <div className="row tight small">
            <label className="check"><input type="checkbox" checked={st.snap} disabled={!writable} onChange={(e) => commit((p) => ({ ...p, settings: { ...st, snap: e.target.checked } }))} /> Aimantation</label>
            <select value={st.grid} disabled={!writable} onChange={(e) => commit((p) => ({ ...p, settings: { ...st, grid: +e.target.value } }))}>
              {[0.05, 0.1, 0.25, 0.5, 1].map((g) => <option key={g} value={g}>grille {g * 100} cm</option>)}</select>
          </div>
          <p className="muted small">Raccourcis : V sélection · H main · E gomme · M mesure · Suppr effacer · Ctrl+Z / Ctrl+Y · Ctrl+D dupliquer · R pivoter · Ctrl+A tout · Échap.</p>
          {writable && <>
            <h3>Fond de plan</h3>
            <label className="btn small file-btn">{busy === "bg" ? "Import…" : plan.background ? "Remplacer le fond" : "Importer un plan (PNG, JPG, PDF, DXF)"}
              <input type="file" accept="image/png,image/jpeg,image/webp,application/pdf,.pdf,.dxf" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) onBackground(f); e.target.value = ""; }} /></label>
            {plan.background && <>
              <label>Opacité<input type="range" min={0.05} max={1} step={0.05} value={plan.background.opacity} onChange={(e) => commit((p) => ({ ...p, background: p.background && { ...p.background, opacity: +e.target.value } }))} /></label>
              <p className="muted small">{plan.background.source} · {plan.background.width_m} × {plan.background.height_m} m</p>
              <div className="row tight small">
                <button className="link" onClick={fitRoomToBackground}>Salle = taille du fond</button>
                <button className="link" onClick={() => commit((p) => ({ ...p, background: null }))}>Retirer le fond</button>
              </div>
            </>}
          </>}
          {writable && <>
            <h3>Bibliothèque de machines</h3>
            <p className="muted small">Encombrements indicatifs (table comprise), modifiables machine par machine.</p>
            <div className="wp-lib">
              {Object.entries(MACHINE_CATEGORIES).map(([cat, catLabel]) => (
                <details key={cat} className="wp-libcat" open={cat === "piqure" || cat === "surjet"}>
                  <summary>{catLabel} <small>({Object.values(MACHINE_CATALOG).filter((c) => c.category === cat).length})</small></summary>
                  {Object.entries(MACHINE_CATALOG).filter(([, c]) => c.category === cat).map(([k, c]) => (
                    <button key={k} draggable className={`wp-libitem ${tool === "machine" && armed === k ? "on" : ""}`}
                      onDragStart={(e) => e.dataTransfer.setData("text/x-machine", k)}
                      onClick={() => { setArmed(k); setTool("machine"); setView3d(false); }}
                      title={`${c.label} — ${c.w} × ${c.d} × ${c.h} m · ${MACHINE_SOURCES[c.source] ?? ""}`}>
                      <span className="wp-ico" style={{ background: CATEGORY_COLOR[c.category] }}>{c.short}</span>
                      <span>{c.label}<small>{c.w} × {c.d} m · h {c.h} m</small></span>
                    </button>
                  ))}
                </details>
              ))}
            </div>
          </>}
        </aside>

        {/* ------------------------------------------------ plan */}
        <section className="card wp-canvas-card">
          <div className="wp-drawbar" role="toolbar" aria-label="Outils de dessin">
            <div className="seg wp-dim-toggle" role="group" aria-label="Vue">
              <button className={!view3d ? "on" : ""} onClick={() => setView3d(false)} title="Plan 2D (édition)">2D</button>
              <button className={view3d ? "on" : ""} onClick={() => { setView3d(true); setMarquee(null); setPreview(null); }} title="Vue 3D (consultation)">3D</button>
            </div>
            {!view3d && <>
              <span className="wp-sep" />
              {TOOLS.filter((t) => writable || t.id === "select" || t.id === "pan" || t.id === "measure").map((t, i) => (
                <span key={t.id} className="wp-toolwrap">
                  {i === 4 && <span className="wp-sep" />}
                  <button className={`wp-toolbtn ${tool === t.id ? "on" : ""} ${t.id === "erase" ? "danger" : ""}`} aria-pressed={tool === t.id}
                    disabled={(t.id === "calibrate" || t.id === "background") && !plan.background}
                    title={`${t.label}${t.key ? ` (${t.key}${t.id === "erase" ? " ; Suppr efface la sélection" : ""})` : ""} — ${t.hint}`} aria-label={t.label}
                    onClick={() => setTool(t.id)}>
                    <Icon d={t.icon} dash={t.dash} /><span className="wp-toollbl">{t.label}{t.key && <kbd>{t.key}</kbd>}</span>
                  </button>
                </span>
              ))}
              <span className="wp-sep" />
              <button className="wp-toolbtn" onClick={() => zoomAt(1 / 1.3)} title="Zoom avant (molette, pincer)" aria-label="Zoom avant"><Icon d="M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM21 21l-5-5M8 11h6M11 8v6" /></button>
              <button className="wp-toolbtn" onClick={() => zoomAt(1.3)} title="Zoom arrière" aria-label="Zoom arrière"><Icon d="M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM21 21l-5-5M8 11h6" /></button>
              <button className="wp-toolbtn" onClick={() => fit(plan)} title="Ajuster à la salle" aria-label="Ajuster"><Icon d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5" /></button>
            </>}
            {writable && <>
              <span className="wp-sep" />
              <button className="wp-toolbtn" disabled={!undo.current.length} onClick={doUndo} title="Annuler (Ctrl+Z)" aria-label="Annuler"><Icon d="M9 14L4 9l5-5M4 9h10a6 6 0 0 1 0 12h-3" /><span className="wp-toollbl">Annuler</span></button>
              <button className="wp-toolbtn" disabled={!redo.current.length} onClick={doRedo} title="Rétablir (Ctrl+Y)" aria-label="Rétablir"><Icon d="M15 14l5-5-5-5M20 9H10a6 6 0 0 0 0 12h3" /><span className="wp-toollbl">Rétablir</span></button>
            </>}
          </div>
          {!view3d && <p className="muted small wp-hint">{toolHint}</p>}
          {!view3d && tool === "select" && writable && <div className="row tight small wp-subbar">
            <label className="check" title="Sur tablette : chaque toucher ajoute ou retire un élément de la sélection"><input type="checkbox" checked={multi} onChange={(e) => setMulti(e.target.checked)} /> Sélection multiple</label>
            {sel.length > 0 && <span className="muted">{sel.length} sélectionné{sel.length > 1 ? "s" : ""}</span>}
            {sel.length > 0 && <button className="link" onClick={() => setSel([])}>désélectionner (Échap)</button>}
          </div>}
          {!view3d && tool === "measure" && <div className="notice row tight small wp-measurebar">
            <div className="seg">{MEASURE_MODES.map((m) => <button key={m.id} className={mMode === m.id ? "on" : ""} onClick={() => { setMMode(m.id); resetMeasure(); }}>{m.label}</button>)}</div>
            {writable && <label className="check" title="Chaque mesure terminée devient une cote affichée sur le plan (exportée en PNG/PDF)"><input type="checkbox" checked={keepDim} onChange={(e) => setKeepDim(e.target.checked)} /> Garder la cote sur le plan</label>}
            {mMode === "chain" && mPts.length >= 2 && <><b>{fmt.n(polyLen(mPts), 2)} m</b><button className="btn small primary" onClick={finishChain}>Terminer</button></>}
            {mMode === "walk" && walkA && <span>Départ : <b>{(plan.elements.find((x) => x.id === walkA) as Machine | undefined)?.label}</b> — touchez la machine d'arrivée.</span>}
            {live && <span className="muted">{dimText(live)}{mCursor?.snapped ? " · aimanté" : ""}</span>}
            {mDone && <><b>{dimText(mDone)}</b>{writable && <button className="btn small" onClick={keepCurrent}>Garder cette cote</button>}</>}
            {(mPts.length > 0 || mDone || walkA) && <button className="link" onClick={resetMeasure}>Effacer (Échap)</button>}
            <span className="muted">Alt : sans aimantation</span>
          </div>}
          {!view3d && tool === "calibrate" && <div className="notice warn row">
            {calib.length < 2 ? `Calibrage : touchez le point ${calib.length + 1} sur 2.` : <>Distance réelle entre les 2 points :
              <input type="number" min={0.1} step={0.01} value={calibDist} onChange={(e) => setCalibDist(e.target.value)} style={{ width: 110 }} autoFocus /> m
              <button className="btn small primary" onClick={applyCalibration} disabled={!(Number(calibDist.replace(",", ".")) > 0)}>Appliquer</button></>}
            <button className="link" onClick={() => setTool("select")}>Annuler</button>
          </div>}
          {view3d ? <div className="wp-canvas wp-canvas3d">
            <Suspense fallback={<p className="muted p3d-loading">Chargement de la vue 3D…</p>}>
              <PlanScene3D plan={plan} className="wp-canvas3d" title={`Atelier · ${plan.name}`} />
            </Suspense>
          </div> : <div ref={wrapRef} className="wp-canvas" onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => { const k = e.dataTransfer.getData("text/x-machine"); if (k) { e.preventDefault(); placeAt(toM(e.clientX, e.clientY), k); } }}>
            <svg ref={svgRef} viewBox={`${view.x} ${view.y} ${view.w} ${vh}`} onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp}
              onPointerLeave={() => { setHover(null); if (tool === "measure" && !drag.current) setMCursor(null); }}
              onDoubleClick={() => { if (tool === "measure") finishChain(); }}
              onWheel={onWheel} style={{ touchAction: "none", cursor: cursorStyle }} xmlns="http://www.w3.org/2000/svg">
              <defs>
                <pattern id="hatch" width="0.3" height="0.3" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="0.3" stroke="#c9c2b0" strokeWidth="0.06" /></pattern>
                <pattern id="hatchred" width="0.2" height="0.2" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="0.2" stroke="#c0392b" strokeWidth="0.05" /></pattern>
              </defs>
              <rect x={0} y={0} width={plan.width_m} height={plan.length_m} fill="#fbfaf7" stroke="#d5d0c4" strokeWidth={0.03} />
              {plan.background && bgUrl && <image data-bg href={bgUrl} x={plan.background.x} y={plan.background.y} width={plan.background.width_m} height={plan.background.height_m}
                opacity={plan.background.opacity} preserveAspectRatio="none" />}
              <g data-noexport>{gridLines}</g>
              {plan.elements.filter((e): e is Zone => e.kind === "zone").map((z) => (
                <g key={z.id}><rect x={z.x} y={z.y} width={z.w} height={z.h} fill={ZONES[z.zone]?.color ?? "#eee"} fillOpacity={0.45} stroke={S.has(z.id) ? "#1f4e79" : "#b9b2a0"} strokeWidth={S.has(z.id) ? 0.06 : 0.03} strokeDasharray="0.2 0.12" />
                  <text x={z.x + 0.15} y={z.y + fs + 0.1} fontSize={fs * 1.1} className="wp-zone-t">{z.name || ZONES[z.zone]?.label}</text></g>
              ))}
              {plan.elements.filter((e): e is Aisle => e.kind === "aisle").map((a) => (
                <g key={a.id}><rect x={a.x} y={a.y} width={a.w} height={a.h} fill="url(#hatch)" stroke={issueIds.has(a.id) ? "#c0392b" : S.has(a.id) ? "#1f4e79" : "#a39d8c"} strokeWidth={S.has(a.id) || issueIds.has(a.id) ? 0.06 : 0.03} strokeDasharray="0.25 0.15" />
                  <text x={a.x + a.w / 2} y={a.y + a.h / 2} fontSize={fs * 0.9} textAnchor="middle" dominantBaseline="middle" className="wp-aisle-t">{a.main ? "allée" : "passage"} {fmt.n(Math.min(a.w, a.h), 2)} m</text></g>
              ))}
              {plan.elements.filter((e): e is Wall => e.kind === "wall").map((w) => (
                <line key={w.id} x1={w.x1} y1={w.y1} x2={w.x2} y2={w.y2} stroke={S.has(w.id) ? "#1f4e79" : "#3a3f47"} strokeWidth={Math.max(0.05, w.thickness)} strokeLinecap="square" />
              ))}
              {plan.elements.filter((e) => e.kind === "pillar").map((p) => p.kind === "pillar" && (
                <rect key={p.id} x={p.x - p.w / 2} y={p.y - p.d / 2} width={p.w} height={p.d} fill="#3a3f47" stroke={S.has(p.id) ? "#2f6ea5" : "none"} strokeWidth={0.06} />
              ))}
              {plan.elements.filter((e): e is Door => e.kind === "door").map((d) => (
                <g key={d.id} transform={`translate(${d.x},${d.y}) rotate(${d.rot})`}>
                  <rect x={-d.width / 2} y={-0.14} width={d.width} height={0.28} fill="#fbfaf7" />
                  <path d={`M${-d.width / 2},0 L${-d.width / 2},${-d.width} A${d.width},${d.width} 0 0 1 ${d.width / 2},0`} fill="none" stroke={d.exit ? "#1f8a5b" : "#8a8f98"} strokeWidth={0.04} />
                  {d.exit && <text x={0} y={0.45} fontSize={fs * 0.8} textAnchor="middle" fill="#1f8a5b" fontWeight={700}>ISSUE</text>}
                  {S.has(d.id) && <circle r={d.width / 2 + 0.1} fill="none" stroke="#1f4e79" strokeWidth={0.05} strokeDasharray="0.1 0.08" />}
                </g>
              ))}
              {machines.map((m) => {
                const c = MACHINE_CATALOG[m.type]; const op = operatorPoint(m); const bad = issueIds.has(m.id); const on = S.has(m.id) || walkA === m.id;
                return (
                  <g key={m.id}>
                    <g transform={`translate(${m.x},${m.y}) rotate(${m.rot})`}>
                      <rect x={-m.w / 2} y={-m.d / 2} width={m.w} height={m.d} rx={0.05}
                        fill={m.status === "panne" ? "url(#hatchred)" : MACHINE_CATALOG[m.type]?.category === "logistique" ? "#efe9dc" : "#ffffff"}
                        stroke={bad ? "#c0392b" : on ? "#1f4e79" : m.status === "reserve" ? "#9aa1ab" : "#5b6878"}
                        strokeWidth={on || bad ? 0.06 : 0.03} strokeDasharray={m.status === "reserve" ? "0.12 0.08" : undefined} />
                      <MachineSymbol type={m.type} w={m.w} d={m.d} />
                    </g>
                    <text x={m.x} y={m.y} fontSize={fs} textAnchor="middle" dominantBaseline="middle" className="wp-m-t">{m.label}</text>
                    <text x={m.x} y={m.y + fs * 1.05} fontSize={fs * 0.62} textAnchor="middle" dominantBaseline="middle" className="wp-m-s">{c?.short}{m.ws_id ? ` · ${m.ws_id}` : ""}</text>
                    {m.type !== "chariot" && <circle cx={op[0]} cy={op[1]} r={0.17} fill={m.status === "service" ? "#1f4e79" : "#b8bec7"} fillOpacity={0.85} />}
                  </g>
                );
              })}
              {plan.elements.filter((e): e is Dim => e.kind === "dim").map((dm) => renderDim(dm, { selected: S.has(dm.id) }))}
              {/* ----- surcouches non exportées : sélection, survol gomme, poignées, mesure */}
              <g data-noexport>
                {selEls.length > 1 && selEls.map((el) => { const b = elPoly(el); return <polygon key={`s${el.id}`} points={b.map((p) => p.join(",")).join(" ")} fill="#2f6ea5" fillOpacity={0.08} stroke="#2f6ea5" strokeWidth={sw * 1.5} strokeDasharray={`${sw * 6} ${sw * 4}`} />; })}
                {hover && (() => { const el = plan.elements.find((x) => x.id === hover); if (!el) return null; const b = elPoly(el); const er = tool === "erase";
                  return <polygon points={b.map((p) => p.join(",")).join(" ")} fill={er ? "#c0392b" : "#1f8a5b"} fillOpacity={0.15} stroke={er ? "#c0392b" : "#1f8a5b"} strokeWidth={sw * 2.5} />; })()}
                {handles.map((h, i) => h.kind === "rotate"
                  ? <g key={i}><line x1={selected && "x" in selected ? selected.x : 0} y1={selected && "y" in selected ? selected.y : 0} x2={h.p[0]} y2={h.p[1]} stroke="#2f6ea5" strokeWidth={sw} strokeDasharray={`${sw * 4} ${sw * 3}`} />
                    <circle cx={h.p[0]} cy={h.p[1]} r={hr} fill="#fff" stroke="#2f6ea5" strokeWidth={sw * 2} /><title>Rotation (pas de 15°, Alt : libre)</title></g>
                  : <rect key={i} x={h.p[0] - hr * 0.8} y={h.p[1] - hr * 0.8} width={hr * 1.6} height={hr * 1.6} fill="#2f6ea5" stroke="#fff" strokeWidth={sw}><title>{h.kind === "resize" ? "Redimensionner" : "Déplacer ce point"}</title></rect>)}
                {marquee && <rect x={Math.min(marquee[0][0], marquee[1][0])} y={Math.min(marquee[0][1], marquee[1][1])} width={Math.abs(marquee[1][0] - marquee[0][0])} height={Math.abs(marquee[1][1] - marquee[0][1])}
                  fill="#2f6ea5" fillOpacity={0.08} stroke="#2f6ea5" strokeWidth={sw * 1.5} strokeDasharray={`${sw * 5} ${sw * 3}`} />}
                {live && renderDim(live, { temp: true })}
                {mDone && renderDim(mDone, { temp: true })}
                {tool === "measure" && mPts.map((p, i) => <circle key={`mp${i}`} cx={p[0]} cy={p[1]} r={hr * 0.7} fill="#c0392b" />)}
                {tool === "measure" && mCursor && mMode !== "walk" && <circle cx={mCursor.p[0]} cy={mCursor.p[1]} r={mCursor.snapped ? hr : hr * 0.6} fill={mCursor.snapped ? "#fff" : "#c0392b"} stroke="#c0392b" strokeWidth={sw * 2} />}
              </g>
              {preview && <g data-noexport opacity={0.6}>
                {preview.kind === "wall" ? <line x1={preview.x1} y1={preview.y1} x2={preview.x2} y2={preview.y2} stroke="#2f6ea5" strokeWidth={0.2} />
                  : <rect x={(preview as Aisle).x} y={(preview as Aisle).y} width={(preview as Aisle).w} height={(preview as Aisle).h} fill="#2f6ea5" fillOpacity={0.2} stroke="#2f6ea5" strokeWidth={0.04} />}
                {preview.kind === "wall" ? <text x={(preview.x1 + preview.x2) / 2} y={(preview.y1 + preview.y2) / 2 - 0.3} fontSize={fs} textAnchor="middle" fill="#1f4e79">{fmt.n(Math.hypot(preview.x2 - preview.x1, preview.y2 - preview.y1), 2)} m</text>
                  : <text x={(preview as Aisle).x + (preview as Aisle).w / 2} y={(preview as Aisle).y - 0.15} fontSize={fs} textAnchor="middle" fill="#1f4e79">{fmt.n((preview as Aisle).w, 2)} × {fmt.n((preview as Aisle).h, 2)} m</text>}
              </g>}
              {calib.length > 0 && <g data-noexport>
                {calib.map((p, i) => <circle key={i} cx={p[0]} cy={p[1]} r={Math.max(0.08, view.w / 200)} fill="#c0392b" />)}
                {calib.length === 2 && <line x1={calib[0][0]} y1={calib[0][1]} x2={calib[1][0]} y2={calib[1][1]} stroke="#c0392b" strokeWidth={Math.max(0.03, view.w / 500)} strokeDasharray="0.2 0.1" />}
              </g>}
            </svg>
          </div>}
          {!view3d && <div className="legend small"><span>● opératrice (côté de travail)</span><span>contour rouge = à vérifier</span><span>hachures rouges = en panne</span><span>pointillés = réserve</span><span>cotes en bleu, chemin à pied en vert</span><span>Pincez / molette pour zoomer, deux doigts ou clic droit pour vous déplacer</span></div>}
        </section>

        {/* ------------------------------------------------ propriétés + contrôles */}
        <aside className="card wp-side">
          {selected ? <Props el={selected} plan={plan} writable={writable} upd={(patch) => updEl(selected.id, patch)} onDup={() => duplicateIds([selected.id])}
            onDel={() => removeIds([selected.id])} onRot={(d) => rotateIds([selected.id], d)} orgId={org.id} />
            : sel.length > 1 ? <MultiProps els={selEls} writable={writable} onDel={() => removeIds(sel)} onDup={() => duplicateIds(sel)} onRot={(d) => rotateIds(sel, d)}
              onAlign={(a) => alignIds(sel, a)} onClear={() => setSel([])} />
            : <p className="muted small">Outil Sélection (V) : touchez un élément du plan pour modifier ses propriétés, ou encadrez-en plusieurs. Raccourcis : Suppr, Ctrl+D (dupliquer), R (pivoter), flèches, Échap.</p>}
          <div className="card-head"><h3>Contrôles</h3><button className="link small" onClick={() => setShowChecks(!showChecks)}>{showChecks ? "masquer" : "afficher"}</button></div>
          {showChecks && <>
            <p className="muted small">Repères indicatifs pour l'implantation, pas une norme : faites valider les issues et circulations selon la réglementation applicable.</p>
            {issues.length === 0 ? <p className="small">Rien à signaler.</p> : <ul className="issues">
              {issues.map((i, k) => <li key={k} className={i.level === "err" ? "error" : i.level === "warn" ? "warning" : "info"} onClick={() => { if (i.ids.length) { setSel(i.ids); setTool("select"); } }} style={{ cursor: i.ids[0] ? "pointer" : "default" }}>{i.msg}</li>)}
            </ul>}
            {writable && <div className="form-grid tight3 small">
              <label>Allée princ. (m)<input type="number" min={0.5} max={5} step={0.1} value={st.main_aisle_min} onChange={(e) => commit((p) => ({ ...p, settings: { ...st, main_aisle_min: +e.target.value } as PlanSettings }))} /></label>
              <label>Passage (m)<input type="number" min={0.4} max={5} step={0.1} value={st.secondary_aisle_min} onChange={(e) => commit((p) => ({ ...p, settings: { ...st, secondary_aisle_min: +e.target.value } as PlanSettings }))} /></label>
              <label>Issue max (m)<input type="number" min={5} max={200} step={5} value={st.exit_max_m} onChange={(e) => commit((p) => ({ ...p, settings: { ...st, exit_max_m: +e.target.value } as PlanSettings }))} /></label>
            </div>}
          </>}
          <GammeLink plan={plan} orgId={org.id} base={base} writable={writable}
            onLinks={(links) => setEls((els) => els.map((e) => (e.kind === "machine" && links[e.id] ? { ...e, ws_id: links[e.id] } : e)))}
            goGamme={() => nav("/gamme?onglet=postes")} />
          <Summary plan={plan} />
        </aside>
      </div>
    </div>
  );
}

// =================================================================== sélection multiple
function MultiProps({ els, writable, onDel, onDup, onRot, onAlign, onClear }: {
  els: El[]; writable: boolean; onDel: () => void; onDup: () => void; onRot: (d: number) => void; onAlign: (a: "x" | "y") => void; onClear: () => void;
}) {
  const names: Record<El["kind"], string> = { machine: "machine", wall: "mur", pillar: "poteau", door: "porte", aisle: "allée", zone: "zone", dim: "cote" };
  const counts = new Map<string, number>();
  for (const e of els) counts.set(e.kind, (counts.get(e.kind) ?? 0) + 1);
  const nm = els.filter((e) => e.kind === "machine").length;
  return (
    <div className="wp-props">
      <div className="card-head"><h3>{els.length} éléments</h3><button className="link small" onClick={onClear}>désélectionner</button></div>
      <p className="small">{[...counts.entries()].map(([k, n]) => `${n} ${names[k as El["kind"]]}${n > 1 ? (k === "machine" ? "s" : k === "wall" ? "s" : "s") : ""}`).join(" · ")}</p>
      <p className="muted small">Glissez un des éléments pour déplacer tout le groupe, ou utilisez les flèches.</p>
      {writable && <div className="row tight">
        <button className="btn small" onClick={onDup}>Dupliquer</button>
        {nm > 0 && <><button className="btn small" onClick={() => onRot(90)}>⟳ 90°</button>
          {nm > 1 && <><button className="btn small" onClick={() => onAlign("y")} title="Même ordonnée (centres)">Aligner en ligne</button>
            <button className="btn small" onClick={() => onAlign("x")} title="Même abscisse (centres)">Aligner en colonne</button></>}</>}
        <button className="btn small danger" onClick={onDel}>Supprimer ({els.length})</button>
      </div>}
    </div>
  );
}


// =================================================================== propriétés d'un élément
function Props({ el, plan, writable, upd, onDup, onDel, onRot, orgId }: {
  el: El; plan: WorkshopPlan; writable: boolean; upd: (p: Partial<El>) => void; onDup: () => void; onDel: () => void; onRot: (d: number) => void; orgId: string;
}) {
  const num = (v: string) => r2(Number(v.replace(",", ".")) || 0);
  const wsOptions = useMemo(() => {
    try { const d = JSON.parse(localStorage.getItem(gammeDraftKey(orgId)) || "null"); return (d?.ws ?? []).map((w: { id: string }) => w.id).filter(Boolean) as string[]; }
    catch { return [] as string[]; }
  }, [orgId]);
  const title = { machine: "Machine", wall: "Mur", pillar: "Poteau", door: "Porte / issue", aisle: "Allée", zone: "Zone", dim: "Cote" }[el.kind];
  return (
    <div className="wp-props">
      <div className="card-head"><h3>{title}</h3>
        {writable && <div className="row tight">{el.kind !== "wall" && el.kind !== "zone" && el.kind !== "aisle" && <button className="btn small" onClick={onDup}>Dupliquer</button>}
          {el.kind === "zone" || el.kind === "aisle" ? <button className="btn small" onClick={onDup}>Dupliquer</button> : null}
          <button className="btn small danger" onClick={onDel}>Supprimer</button></div>}
      </div>
      <fieldset disabled={!writable} className="plain">
        {el.kind === "machine" && <>
          <div className="form-grid tight2">
            <label>N° / étiquette<input value={el.label} maxLength={20} onChange={(e) => upd({ label: e.target.value })} /></label>
            <label>Type<select value={el.type} onChange={(e) => { const c = MACHINE_CATALOG[e.target.value]; upd({ type: e.target.value, w: c.w, d: c.d } as Partial<Machine>); }}>
              {Object.entries(MACHINE_CATALOG).map(([k, c]) => <option key={k} value={k}>{c.label}</option>)}</select></label>
            <label>Largeur (m)<input type="number" step={0.05} min={0.2} value={el.w} onChange={(e) => upd({ w: Math.max(0.2, num(e.target.value)) } as Partial<Machine>)} /></label>
            <label>Profondeur (m)<input type="number" step={0.05} min={0.2} value={el.d} onChange={(e) => upd({ d: Math.max(0.2, num(e.target.value)) } as Partial<Machine>)} /></label>
            <label>État<select value={el.status} onChange={(e) => upd({ status: e.target.value as MachineStatus } as Partial<Machine>)}>
              {Object.entries(STATUS_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></label>
            <label>Opératrice<select value={el.operator} onChange={(e) => upd({ operator: e.target.value as OperatorSide } as Partial<Machine>)}>
              <option value="front">devant</option><option value="back">derrière</option><option value="left">à gauche</option><option value="right">à droite</option></select></label>
          </div>
          <label>Poste de gamme (WS)<input list="dl-plan-ws" value={el.ws_id ?? ""} maxLength={40} placeholder={machineType(el) ? "ex. WS01" : "chariot : pas de poste"} disabled={!machineType(el)}
            onChange={(e) => upd({ ws_id: e.target.value || undefined } as Partial<Machine>)} /></label>
          <datalist id="dl-plan-ws">{wsOptions.map((w) => <option key={w} value={w} />)}</datalist>
          <div className="row tight">Rotation {el.rot}° <button className="btn small" onClick={() => onRot(-90)}>⟲ 90°</button><button className="btn small" onClick={() => onRot(90)}>⟳ 90°</button>
            <button className="btn small" onClick={() => onRot(15)}>+15°</button></div>
          <p className="muted small">Position {fmt.n(el.x, 2)} ; {fmt.n(el.y, 2)} m · zone : {zoneLabel(plan, el.x, el.y) || "—"}</p>
        </>}
        {el.kind === "wall" && <div className="form-grid tight2">
          <label>Épaisseur (m)<input type="number" step={0.05} min={0.05} value={el.thickness} onChange={(e) => upd({ thickness: Math.max(0.05, num(e.target.value)) } as Partial<Wall>)} /></label>
          <label>Longueur (m)<input type="number" step={0.1} min={0.1} value={r2(Math.hypot(el.x2 - el.x1, el.y2 - el.y1))} onChange={(e) => {
            const L = Math.max(0.1, num(e.target.value)), cur = Math.hypot(el.x2 - el.x1, el.y2 - el.y1) || 1;
            upd({ x2: r2(el.x1 + ((el.x2 - el.x1) / cur) * L), y2: r2(el.y1 + ((el.y2 - el.y1) / cur) * L) } as Partial<Wall>);
          }} /></label>
        </div>}
        {el.kind === "pillar" && <div className="form-grid tight2">
          <label>Largeur (m)<input type="number" step={0.05} min={0.1} value={el.w} onChange={(e) => upd({ w: Math.max(0.1, num(e.target.value)) })} /></label>
          <label>Profondeur (m)<input type="number" step={0.05} min={0.1} value={el.d} onChange={(e) => upd({ d: Math.max(0.1, num(e.target.value)) })} /></label>
        </div>}
        {el.kind === "door" && <>
          <div className="form-grid tight2">
            <label>Largeur (m)<input type="number" step={0.1} min={0.6} value={el.width} onChange={(e) => upd({ width: Math.max(0.6, num(e.target.value)) } as Partial<Door>)} /></label>
            <label>Angle (°)<input type="number" step={15} value={el.rot} onChange={(e) => upd({ rot: num(e.target.value) } as Partial<Door>)} /></label>
          </div>
          <label className="check"><input type="checkbox" checked={el.exit} onChange={(e) => upd({ exit: e.target.checked } as Partial<Door>)} /> Issue de secours</label>
        </>}
        {(el.kind === "aisle" || el.kind === "zone") && <div className="form-grid tight2">
          <label>Largeur (m)<input type="number" step={0.1} min={0.2} value={el.w} onChange={(e) => upd({ w: Math.max(0.2, num(e.target.value)) })} /></label>
          <label>Longueur (m)<input type="number" step={0.1} min={0.2} value={el.h} onChange={(e) => upd({ h: Math.max(0.2, num(e.target.value)) })} /></label>
        </div>}
        {el.kind === "aisle" && <label className="check"><input type="checkbox" checked={el.main} onChange={(e) => upd({ main: e.target.checked } as Partial<Aisle>)} /> Allée principale (sinon passage secondaire)</label>}
        {el.kind === "dim" && <>
          <p className="small"><b>{dimText(el)}</b>{el.note ? ` · ${el.note}` : ""}</p>
          <p className="muted small">{({ dist: "Distance", chain: "Mesure en chaîne", area: "Surface", walk: "Chemin à pied" } as Record<string, string>)[el.mode]} · affichée sur le plan et dans les exports PNG/PDF. Faites glisser ses points (poignées) pour l'ajuster.</p>
          <label>Note<input value={el.note ?? ""} maxLength={60} onChange={(e) => upd({ note: e.target.value || undefined } as Partial<Dim>)} /></label>
        </>}
        {el.kind === "zone" && <div className="form-grid tight2">
          <label>Type<select value={el.zone} onChange={(e) => upd({ zone: e.target.value, name: ZONES[e.target.value]?.label ?? "" } as Partial<Zone>)}>
            {Object.entries(ZONES).map(([k, z]) => <option key={k} value={k}>{z.label}</option>)}</select></label>
          <label>Nom<input value={el.name} maxLength={40} onChange={(e) => upd({ name: e.target.value } as Partial<Zone>)} /></label>
        </div>}
      </fieldset>
    </div>
  );
}
const zoneLabel = (plan: WorkshopPlan, x: number, y: number) => {
  const z = plan.elements.find((e): e is Zone => e.kind === "zone" && x >= e.x && x <= e.x + e.w && y >= e.y && y <= e.y + e.h);
  return z ? z.name || ZONES[z.zone]?.label : "";
};

// =================================================================== lien avec les gammes
function GammeLink({ plan, orgId, base, writable, onLinks, goGamme }: {
  plan: WorkshopPlan; orgId: string; base: string; writable: boolean; onLinks: (l: Record<string, string>) => void; goGamme: () => void;
}) {
  const [src, setSrc] = useState("draft");
  const [problems, setProblems] = useState<ProblemRow[]>([]);
  const [problem, setProblem] = useState<Problem | null>(null);
  const [done, setDone] = useState("");
  useEffect(() => { api<ProblemRow[]>(`${base}/problems?limit=30`).then(setProblems).catch(() => setProblems([])); }, [base]);
  useEffect(() => {
    if (src === "draft") {
      try {
        const d = JSON.parse(localStorage.getItem(gammeDraftKey(orgId)) || "null");
        setProblem(d ? { name: d.name, target_cycle_time: 0, operations: (d.ops ?? []).map((o: { id: string; machine_type: string }) => ({ id: o.id, machine_type: o.machine_type })),
          workstations: (d.ws ?? []).map((w: { id: string; machine_type: string }) => ({ id: w.id, machine_type: w.machine_type })), workers: [] } as unknown as Problem : null);
      } catch { setProblem(null); }
    } else api<ProblemRow>(`${base}/problems/${src}`).then((r) => setProblem(r.payload ?? null)).catch(() => setProblem(null));
  }, [src, base, orgId, done]);

  const ms = plan.elements.filter((e): e is Machine => e.kind === "machine" && !!machineType(e));
  const wsIds = new Set((problem?.workstations ?? []).map((w) => w.id).filter(Boolean));
  const linked = new Set(ms.map((m) => m.ws_id).filter(Boolean) as string[]);
  const wsWithout = [...wsIds].filter((w) => !linked.has(w));
  const machinesUnused = ms.filter((m) => !m.ws_id || !wsIds.has(m.ws_id));
  const opTypes = new Set((problem?.operations ?? []).map((o) => o.machine_type).filter((t) => t && t !== "manuel"));
  const planTypes = new Set(ms.filter((m) => m.status === "service").map((m) => machineType(m)));
  const typesMissing = [...opTypes].filter((t) => !planTypes.has(t));
  const typesUnused = [...planTypes].filter((t) => !opTypes.has(t));

  const pushToGamme = (mode: "merge" | "replace") => {
    const { rows, links } = inventory(plan);
    let d: { ws?: { id: string }[] } & Record<string, unknown>;
    try { d = JSON.parse(localStorage.getItem(gammeDraftKey(orgId)) || "null") ?? {}; } catch { d = {}; }
    const draft = { name: "", cycle: "", lineId: "", ops: [], wk: [], ...d } as { ws: { id: string }[] } & Record<string, unknown>;
    const cur = (draft.ws ?? []) as { id: string }[];
    const byId = new Map(rows.map((r) => [r.id, r]));
    const ws = mode === "replace" ? rows : [...cur.map((w) => (byId.has(w.id) ? { ...w, ...byId.get(w.id) } : w)), ...rows.filter((r) => !cur.some((w) => w.id === r.id))];
    localStorage.setItem(gammeDraftKey(orgId), JSON.stringify({ ...draft, ws }));
    onLinks(links);
    setSrc("draft"); setDone(String(Date.now()));
    return rows.length;
  };

  return (
    <div className="wp-gamme">
      <h3>Lien avec les gammes</h3>
      <label>Comparer avec<select value={src} onChange={(e) => setSrc(e.target.value)}>
        <option value="draft">Gamme en cours d'édition (brouillon)</option>
        {problems.map((p) => <option key={p.id} value={p.id}>{p.name} · {fmt.date(p.created_at)}</option>)}</select></label>
      {problem ? <ul className="small plain-list">
        <li><b>{ms.length}</b> machines (hors chariots) · <b>{wsIds.size}</b> postes dans la gamme</li>
        {wsWithout.length > 0 && <li className="warn-text">Postes de gamme sans machine sur le plan : {wsWithout.slice(0, 20).join(", ")}{wsWithout.length > 20 ? "…" : ""}</li>}
        {machinesUnused.length > 0 && <li>Machines du plan non utilisées par la gamme : {machinesUnused.slice(0, 20).map((m) => m.label).join(", ")}{machinesUnused.length > 20 ? "…" : ""}</li>}
        {typesMissing.length > 0 && <li className="warn-text">Types demandés par les opérations, absents du plan (en service) : {typesMissing.join(", ")}</li>}
        {typesUnused.length > 0 && <li className="muted">Types présents sur le plan, non demandés : {typesUnused.join(", ")}</li>}
      </ul> : <p className="muted small">Aucune gamme en cours d'édition.</p>}
      {writable && <div className="row tight">
        <button className="btn small" onClick={() => { const n = pushToGamme("merge"); window.setTimeout(() => window.alert(`${n} postes envoyés dans l'onglet Postes de l'éditeur de gamme (fusion : les postes existants de même identifiant sont mis à jour). Enregistrez aussi le plan pour garder les liens machine ↔ poste.`), 0); }}>Mettre à jour les postes de la gamme</button>
        <button className="link small" onClick={() => { if (window.confirm("Remplacer tous les postes de la gamme en cours par l'inventaire du plan ?")) pushToGamme("replace"); }}>remplacer</button>
        <button className="link small" onClick={goGamme}>ouvrir l'onglet Postes</button>
      </div>}
    </div>
  );
}

function Summary({ plan }: { plan: WorkshopPlan }) {
  const counts = new Map<string, { n: number; panne: number; reserve: number }>();
  for (const e of plan.elements) if (e.kind === "machine") {
    const c = counts.get(e.type) ?? { n: 0, panne: 0, reserve: 0 };
    c.n++; if (e.status === "panne") c.panne++; if (e.status === "reserve") c.reserve++;
    counts.set(e.type, c);
  }
  if (!counts.size) return null;
  return (
    <div><h3>Inventaire</h3>
      <table className="small compact"><tbody>
        {[...counts.entries()].map(([t, c]) => <tr key={t}><td>{MACHINE_CATALOG[t]?.label ?? t}</td><td>{c.n}</td>
          <td className="muted">{c.panne ? `${c.panne} en panne ` : ""}{c.reserve ? `${c.reserve} en réserve` : ""}</td></tr>)}
      </tbody></table>
    </div>
  );
}
