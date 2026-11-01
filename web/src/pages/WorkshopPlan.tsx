import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, fmt, post } from "../lib/api";
import { canManage, canWrite, useSession } from "../lib/session";
import type { Problem, ProblemRow } from "../lib/types";
import {
  MACHINE_CATALOG, STATUS_LABEL, ZONES, backgroundUrl, checkPlan, dxfToWalls, elCenter, emptyPlan, fileToImage, hitTest,
  inventory, machineType, moveEl, resizeRoom, nearestWallAngle, newMachine, nextLabel, operatorPoint, pngToPdf, r2, saveBlob, settingsOf,
  svgToPng, uid, uploadBackground,
  type Aisle, type Door, type El, type Machine, type MachineStatus, type OperatorSide, type P, type PlanSettings, type PlanSummary,
  type Wall, type WorkshopPlan, type Zone,
} from "../lib/workshop";

const PlanScene3D = lazy(() => import("../components/PlanScene3D"));

type Tool = "select" | "wall" | "pillar" | "door" | "aisle" | "zone" | "machine" | "calibrate" | "background";
const TOOLS: { id: Tool; label: string; hint: string }[] = [
  { id: "select", label: "Sélection", hint: "Touchez un élément pour le choisir, faites-le glisser pour le déplacer ; glissez le fond pour vous déplacer." },
  { id: "wall", label: "Mur", hint: "Glissez d'un point à l'autre pour tracer un mur (aimanté aux extrémités voisines)." },
  { id: "pillar", label: "Poteau", hint: "Touchez pour poser un poteau." },
  { id: "door", label: "Porte / issue", hint: "Touchez près d'un mur : la porte se met dans l'axe du mur." },
  { id: "aisle", label: "Allée", hint: "Glissez pour tracer une allée de circulation (rectangle)." },
  { id: "zone", label: "Zone", hint: "Glissez pour tracer une zone (coupe, montage…)." },
  { id: "machine", label: "Machine", hint: "Choisissez une machine dans la bibliothèque puis touchez le plan pour la poser (ou glissez-la depuis la liste)." },
  { id: "calibrate", label: "Calibrer", hint: "Touchez deux points du fond de plan dont vous connaissez la distance réelle." },
  { id: "background", label: "Déplacer le fond", hint: "Glissez pour caler le fond de plan sur la salle." },
];
const draftKey = (org: string, id?: string) => `tlb.plan.brouillon.${org}.${id || "nouveau"}`;
const gammeDraftKey = (org: string) => `tlb.gamme.brouillon.${org}`;
const MIN_W = 2, MAX_W = 420;

interface Drag {
  mode: "pan" | "move" | "wallEnd" | "draw" | "bg" | "pinch";
  sx: number; sy: number; cx: number; cy: number; id?: string; end?: 1 | 2; orig?: El; view?: View; bg?: { x: number; y: number };
  dist?: number; moved?: boolean;
}
interface View { x: number; y: number; w: number }

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
  const [tool, setTool] = useState<Tool>("select");
  const [canvasMode, setCanvasMode] = useState<"2d" | "3d">("2d");
  const [armed, setArmed] = useState("piqueuse_plate");
  const [zoneKind, setZoneKind] = useState("montage");
  const [sel, setSel] = useState<string | null>(null);
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
  const undo = useRef<WorkshopPlan[]>([]);
  const redo = useRef<WorkshopPlan[]>([]);
  const svgRef = useRef<SVGSVGElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const drag = useRef<Drag | null>(null);
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const base = `/v1/orgs/${org.id}`;
  const st = settingsOf(plan);

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
      undo.current = []; redo.current = []; setSel(null); setDirty(false); setRestore(null);
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

  const commit = useCallback((next: WorkshopPlan | ((p: WorkshopPlan) => WorkshopPlan)) => {
    setPlanState((cur) => {
      const n = typeof next === "function" ? next(cur) : next;
      if (n === cur) return cur;
      undo.current.push(cur); if (undo.current.length > 80) undo.current.shift();
      redo.current = [];
      return n;
    });
    setDirty(true);
  }, []);
  const setEls = (fn: (els: El[]) => El[]) => commit((p) => ({ ...p, elements: fn(p.elements) }));
  const updEl = (id: string, patch: Partial<El>) => setEls((els) => els.map((e) => (e.id === id ? ({ ...e, ...patch } as El) : e)));
  const doUndo = () => { const prev = undo.current.pop(); if (prev) { setPlanState((cur) => { redo.current.push(cur); return prev; }); setDirty(true); } };
  const doRedo = () => { const nx = redo.current.pop(); if (nx) { setPlanState((cur) => { undo.current.push(cur); return nx; }); setDirty(true); } };

  const selected = plan.elements.find((e) => e.id === sel) ?? null;
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

  // ---------------------------------------------------------------- interactions (souris, doigt, stylet)
  const placeAt = (p: P, type = armed) => {
    if (!writable) return;
    const m = newMachine(type, ...snapP(p), nextLabel(plan.elements));
    setEls((els) => [...els, m]); setSel(m.id);
  };
  const onDown = (e: React.PointerEvent<SVGSVGElement>) => {
    (e.currentTarget as Element).setPointerCapture?.(e.pointerId);
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.current.size === 2) {
      const [a, b] = [...pointers.current.values()];
      if (drag.current?.mode === "move" && drag.current.orig) setEls((els) => els.map((x) => (x.id === drag.current!.orig!.id ? drag.current!.orig! : x)));
      drag.current = { mode: "pinch", sx: (a.x + b.x) / 2, sy: (a.y + b.y) / 2, cx: 0, cy: 0, view, dist: Math.hypot(a.x - b.x, a.y - b.y) };
      setPreview(null); return;
    }
    const [mx, my] = toM(e.clientX, e.clientY);
    const d: Drag = { mode: "pan", sx: e.clientX, sy: e.clientY, cx: mx, cy: my, view };
    if (tool === "select" || !writable) {
      const hit = hitTest(plan.elements, mx, my);
      if (hit && writable) {
        setSel(hit.id);
        if (hit.kind === "wall") {
          const n1 = Math.hypot(mx - hit.x1, my - hit.y1), n2 = Math.hypot(mx - hit.x2, my - hit.y2);
          if (Math.min(n1, n2) < Math.max(0.3, view.w / 60)) { drag.current = { ...d, mode: "wallEnd", id: hit.id, end: n1 < n2 ? 1 : 2, orig: hit }; return; }
        }
        drag.current = { ...d, mode: "move", id: hit.id, orig: hit }; return;
      }
      if (hit) setSel(hit.id); else setSel(null);
      drag.current = d; return;
    }
    if (tool === "wall" || tool === "aisle" || tool === "zone") {
      const p = tool === "wall" ? snapToWallEnds([mx, my]) : snapP([mx, my]);
      drag.current = { ...d, mode: "draw", cx: p[0], cy: p[1] }; return;
    }
    if (tool === "background") { if (plan.background) drag.current = { ...d, mode: "bg", bg: { x: plan.background.x, y: plan.background.y } }; return; }
    drag.current = { ...d, mode: "pan", moved: false };
  };
  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    if (!pointers.current.has(e.pointerId)) return;
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
    if (d.mode === "pan" && d.view) {
      const r = svgRef.current!.getBoundingClientRect(); const k = d.view.w / r.width;
      setView({ ...d.view, x: d.view.x - (e.clientX - d.sx) * k, y: d.view.y - (e.clientY - d.sy) * k });
    } else if (d.mode === "move" && d.orig && d.moved) {
      const [ox, oy] = elCenter(d.orig);
      const [nx, ny] = snapP([ox + mx - d.cx, oy + my - d.cy]);
      const moved = moveEl(d.orig, nx - ox, ny - oy);
      setPlanState((p) => ({ ...p, elements: p.elements.map((x) => (x.id === d.id ? moved : x)) }));
    } else if (d.mode === "wallEnd" && d.orig) {
      const [px, py] = snapToWallEnds([mx, my], d.id);
      const patch = d.end === 1 ? { x1: px, y1: py } : { x2: px, y2: py };
      setPlanState((p) => ({ ...p, elements: p.elements.map((x) => (x.id === d.id ? ({ ...x, ...patch } as El) : x)) }));
    } else if (d.mode === "draw") {
      setPreview(drawEl(d.cx, d.cy, mx, my));
    } else if (d.mode === "bg" && d.bg && plan.background) {
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
    if ((d.mode === "move" || d.mode === "wallEnd" || d.mode === "bg") && d.moved && d.orig !== undefined) {
      // valider le déplacement dans l'historique
      const cur = plan;
      undo.current.push({ ...cur, elements: cur.elements.map((x) => (x.id === d.id && d.orig ? d.orig : x)) }); redo.current = []; setDirty(true);
      return;
    }
    if (d.mode === "bg" && d.moved) { setDirty(true); return; }
    if (d.mode === "draw") {
      const el = drawEl(d.cx, d.cy, mx, my); setPreview(null);
      if (!el) return;
      const ok = el.kind === "wall" ? Math.hypot(el.x2 - el.x1, el.y2 - el.y1) >= 0.1 : (el as Aisle).w >= 0.2 && (el as Aisle).h >= 0.2;
      if (ok) { const n = { ...el, id: uid() } as El; setEls((els) => (n.kind === "zone" ? [n, ...els] : [...els, n])); setSel(n.id); }
      return;
    }
    if (d.mode === "pan" && !d.moved && writable) {
      if (tool === "pillar") { const [x, y] = snapP([mx, my]); const n: El = { id: uid(), kind: "pillar", x, y, w: 0.4, d: 0.4 }; setEls((els) => [...els, n]); setSel(n.id); }
      else if (tool === "door") {
        const w = nearestWallAngle(plan.elements, mx, my);
        const [x, y] = w ? [w.x, w.y] : snapP([mx, my]);
        const n: El = { id: uid(), kind: "door", x, y, width: 1.2, rot: w ? r2(w.angle) : 0, exit: true };
        setEls((els) => [...els, n]); setSel(n.id);
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
    el.addEventListener("wheel", stop, { passive: false });
    return () => el.removeEventListener("wheel", stop);
  }, []);

  const duplicate = useCallback((id: string) => {
    const e = plan.elements.find((x) => x.id === id); if (!e || !writable) return;
    const off = e.kind === "machine" ? Math.max(e.w, 0.6) + 0.2 : 0.5;
    let n = { ...moveEl(e, e.kind === "machine" && Math.abs(Math.sin((e.rot * Math.PI) / 180)) > 0.7 ? 0 : off, e.kind === "machine" && Math.abs(Math.sin((e.rot * Math.PI) / 180)) > 0.7 ? off : 0), id: uid() } as El;
    if (n.kind === "machine") n = { ...n, label: nextLabel(plan.elements), ws_id: undefined };
    setEls((els) => [...els, n]); setSel(n.id);
  }, [plan.elements, writable]); // eslint-disable-line react-hooks/exhaustive-deps
  const remove = useCallback((id: string) => { if (!writable) return; setEls((els) => els.filter((x) => x.id !== id)); setSel(null); }, [writable]); // eslint-disable-line react-hooks/exhaustive-deps
  const rotate = useCallback((id: string, deg: number) => {
    const e = plan.elements.find((x) => x.id === id); if (!e) return;
    if (e.kind === "machine" || e.kind === "door") updEl(id, { rot: ((Math.round(e.rot + deg) % 360) + 360) % 360 } as Partial<El>);
  }, [plan.elements]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      const t = ev.target as HTMLElement;
      if (t && (t.tagName === "INPUT" || t.tagName === "SELECT" || t.tagName === "TEXTAREA")) return;
      if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "z") { ev.preventDefault(); if (ev.shiftKey) doRedo(); else doUndo(); return; }
      if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "y") { ev.preventDefault(); doRedo(); return; }
      if (!sel) { if (ev.key === "Escape") setTool("select"); return; }
      if (ev.key === "Delete" || ev.key === "Backspace") { ev.preventDefault(); remove(sel); }
      else if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "d") { ev.preventDefault(); duplicate(sel); }
      else if (ev.key.toLowerCase() === "r") rotate(sel, ev.shiftKey ? -15 : 90);
      else if (ev.key === "Escape") setSel(null);
      else if (ev.key.startsWith("Arrow")) {
        ev.preventDefault();
        const s = ev.shiftKey ? 0.5 : st.grid;
        const [dx, dy] = { ArrowLeft: [-s, 0], ArrowRight: [s, 0], ArrowUp: [0, -s], ArrowDown: [0, s] }[ev.key] as P;
        setEls((els) => els.map((x) => (x.id === sel ? moveEl(x, dx, dy) : x)));
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
      setTool("calibrate"); setCalib([]);
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
    setCalib([]); setCalibDist(""); setTool("select");
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
    if (!svgRef.current) return;
    setBusy(kind);
    try {
      const clone = svgRef.current.cloneNode(true) as SVGSVGElement;
      const vb = [-0.6, -0.6, plan.width_m + 1.2, plan.length_m + 1.2];
      clone.setAttribute("viewBox", vb.join(" "));
      const ratio = vb[2] / vb[3]; const W = 2400, H = Math.round(W / ratio);
      const png = await svgToPng(clone, W, H, bgUrl);
      const nm = plan.name.replace(/[^\p{L}\d_-]+/gu, "_").slice(0, 40) || "plan";
      if (kind === "png") saveBlob(png, `${nm}.png`);
      else saveBlob(await pngToPdf(png, `${org.name} — ${plan.name}`, `${plan.width_m} × ${plan.length_m} m · ${machines.length} machines · version ${plan.version} · ${new Date().toLocaleDateString("fr-FR")}`, ratio), `${nm}.pdf`);
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
  const toolHint = TOOLS.find((t) => t.id === tool)?.hint;

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
        {/* ------------------------------------------------ outils + bibliothèque */}
        <aside className="card wp-side">
          <h3>Outils</h3>
          <div className="wp-tools">
            {TOOLS.filter((t) => writable || t.id === "select").map((t) => (
              <button key={t.id} className={`chipbtn ${tool === t.id ? "on" : ""}`} disabled={(t.id === "calibrate" || t.id === "background") && !plan.background}
                onClick={() => { setTool(t.id); setCalib([]); }}>{t.label}</button>
            ))}
          </div>
          {tool === "zone" && <label>Type de zone<select value={zoneKind} onChange={(e) => setZoneKind(e.target.value)}>
            {Object.entries(ZONES).map(([k, z]) => <option key={k} value={k}>{z.label}</option>)}</select></label>}
          <div className="row tight small">
            <label className="check"><input type="checkbox" checked={st.snap} onChange={(e) => commit((p) => ({ ...p, settings: { ...st, snap: e.target.checked } }))} /> Aimantation</label>
            <select value={st.grid} onChange={(e) => commit((p) => ({ ...p, settings: { ...st, grid: +e.target.value } }))}>
              {[0.05, 0.1, 0.25, 0.5, 1].map((g) => <option key={g} value={g}>grille {g * 100} cm</option>)}</select>
          </div>
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
              {Object.entries(MACHINE_CATALOG).map(([k, c]) => (
                <button key={k} draggable className={`wp-libitem ${tool === "machine" && armed === k ? "on" : ""}`}
                  onDragStart={(e) => e.dataTransfer.setData("text/x-machine", k)}
                  onClick={() => { setArmed(k); setTool("machine"); }} title={`${c.label} — ${c.w} × ${c.d} m`}>
                  <span className="wp-ico">{c.short}</span><span>{c.label}<small>{c.w} × {c.d} m</small></span>
                </button>
              ))}
            </div>
          </>}
        </aside>

        {/* ------------------------------------------------ plan */}
        <section className="card wp-canvas-card">
          <div className="row small wp-toolbar">
            <div className="seg" aria-label="Vue du plan">
              <button className={canvasMode === "2d" ? "on" : ""} aria-pressed={canvasMode === "2d"} onClick={() => setCanvasMode("2d")}>2D</button>
              <button className={canvasMode === "3d" ? "on" : ""} aria-pressed={canvasMode === "3d"} onClick={() => setCanvasMode("3d")}>3D</button>
            </div>
            {canvasMode === "2d" && <>
              <button className="btn small" onClick={() => zoomAt(1 / 1.3)}>＋</button>
              <button className="btn small" onClick={() => zoomAt(1.3)}>－</button>
              <button className="btn small" onClick={() => fit(plan)}>Ajuster</button>
            </>}
            {writable && <><button className="btn small" disabled={!undo.current.length} onClick={doUndo} title="Ctrl+Z">↶ Annuler</button>
              <button className="btn small" disabled={!redo.current.length} onClick={doRedo} title="Ctrl+Y">↷ Rétablir</button></>}
            <span className="muted">{canvasMode === "2d" ? toolHint : "Vue 3D du plan enregistré dans l’éditeur · faites glisser pour orbiter."}</span>
          </div>
          {tool === "calibrate" && <div className="notice warn row">
            {calib.length < 2 ? `Calibrage : touchez le point ${calib.length + 1} sur 2.` : <>Distance réelle entre les 2 points :
              <input type="number" min={0.1} step={0.01} value={calibDist} onChange={(e) => setCalibDist(e.target.value)} style={{ width: 110 }} autoFocus /> m
              <button className="btn small primary" onClick={applyCalibration} disabled={!(Number(calibDist.replace(",", ".")) > 0)}>Appliquer</button></>}
            <button className="link" onClick={() => { setCalib([]); setTool("select"); }}>Annuler</button>
          </div>}
          <div ref={wrapRef} className="wp-canvas" onDragOver={(e) => { if (canvasMode === "2d") e.preventDefault(); }}
            onDrop={(e) => { if (canvasMode !== "2d") return; const k = e.dataTransfer.getData("text/x-machine"); if (k) { e.preventDefault(); placeAt(toM(e.clientX, e.clientY), k); } }}>
            {canvasMode === "3d" ? <Suspense fallback={<div className="p3d-fallback" role="status">Chargement du moteur 3D…</div>}>
              <PlanScene3D plan={plan} className="wp-canvas3d" title={`Atelier · ${plan.name}`} />
            </Suspense> :
            <svg ref={svgRef} viewBox={`${view.x} ${view.y} ${view.w} ${vh}`} onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerCancel={onUp}
              onWheel={onWheel} style={{ touchAction: "none", cursor: tool === "select" ? "default" : "crosshair" }} xmlns="http://www.w3.org/2000/svg">
              <defs>
                <pattern id="hatch" width="0.3" height="0.3" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="0.3" stroke="#c9c2b0" strokeWidth="0.06" /></pattern>
                <pattern id="hatchred" width="0.2" height="0.2" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="0.2" stroke="#c0392b" strokeWidth="0.05" /></pattern>
              </defs>
              <rect x={0} y={0} width={plan.width_m} height={plan.length_m} fill="#fbfaf7" stroke="#d5d0c4" strokeWidth={0.03} />
              {plan.background && bgUrl && <image data-bg href={bgUrl} x={plan.background.x} y={plan.background.y} width={plan.background.width_m} height={plan.background.height_m}
                opacity={plan.background.opacity} preserveAspectRatio="none" />}
              <g data-noexport>{gridLines}</g>
              {plan.elements.filter((e): e is Zone => e.kind === "zone").map((z) => (
                <g key={z.id}><rect x={z.x} y={z.y} width={z.w} height={z.h} fill={ZONES[z.zone]?.color ?? "#eee"} fillOpacity={0.45} stroke={sel === z.id ? "#1f4e79" : "#b9b2a0"} strokeWidth={sel === z.id ? 0.06 : 0.03} strokeDasharray="0.2 0.12" />
                  <text x={z.x + 0.15} y={z.y + fs + 0.1} fontSize={fs * 1.1} className="wp-zone-t">{z.name || ZONES[z.zone]?.label}</text></g>
              ))}
              {plan.elements.filter((e): e is Aisle => e.kind === "aisle").map((a) => (
                <g key={a.id}><rect x={a.x} y={a.y} width={a.w} height={a.h} fill="url(#hatch)" stroke={issueIds.has(a.id) ? "#c0392b" : sel === a.id ? "#1f4e79" : "#a39d8c"} strokeWidth={sel === a.id || issueIds.has(a.id) ? 0.06 : 0.03} strokeDasharray="0.25 0.15" />
                  <text x={a.x + a.w / 2} y={a.y + a.h / 2} fontSize={fs * 0.9} textAnchor="middle" dominantBaseline="middle" className="wp-aisle-t">{a.main ? "allée" : "passage"} {fmt.n(Math.min(a.w, a.h), 2)} m</text></g>
              ))}
              {plan.elements.filter((e): e is Wall => e.kind === "wall").map((w) => (
                <line key={w.id} x1={w.x1} y1={w.y1} x2={w.x2} y2={w.y2} stroke={sel === w.id ? "#1f4e79" : "#3a3f47"} strokeWidth={Math.max(0.05, w.thickness)} strokeLinecap="square" />
              ))}
              {plan.elements.filter((e) => e.kind === "pillar").map((p) => p.kind === "pillar" && (
                <rect key={p.id} x={p.x - p.w / 2} y={p.y - p.d / 2} width={p.w} height={p.d} fill="#3a3f47" stroke={sel === p.id ? "#2f6ea5" : "none"} strokeWidth={0.06} />
              ))}
              {plan.elements.filter((e): e is Door => e.kind === "door").map((d) => (
                <g key={d.id} transform={`translate(${d.x},${d.y}) rotate(${d.rot})`}>
                  <rect x={-d.width / 2} y={-0.14} width={d.width} height={0.28} fill="#fbfaf7" />
                  <path d={`M${-d.width / 2},0 L${-d.width / 2},${-d.width} A${d.width},${d.width} 0 0 1 ${d.width / 2},0`} fill="none" stroke={d.exit ? "#1f8a5b" : "#8a8f98"} strokeWidth={0.04} />
                  {d.exit && <text x={0} y={0.45} fontSize={fs * 0.8} textAnchor="middle" fill="#1f8a5b" fontWeight={700}>ISSUE</text>}
                  {sel === d.id && <circle r={d.width / 2 + 0.1} fill="none" stroke="#1f4e79" strokeWidth={0.05} strokeDasharray="0.1 0.08" />}
                </g>
              ))}
              {machines.map((m) => {
                const c = MACHINE_CATALOG[m.type]; const op = operatorPoint(m); const bad = issueIds.has(m.id);
                return (
                  <g key={m.id}>
                    <g transform={`translate(${m.x},${m.y}) rotate(${m.rot})`}>
                      <rect x={-m.w / 2} y={-m.d / 2} width={m.w} height={m.d} rx={0.05}
                        fill={m.status === "panne" ? "url(#hatchred)" : m.type === "chariot" ? "#efe9dc" : "#ffffff"}
                        stroke={bad ? "#c0392b" : sel === m.id ? "#1f4e79" : m.status === "reserve" ? "#9aa1ab" : "#5b6878"}
                        strokeWidth={sel === m.id || bad ? 0.06 : 0.03} strokeDasharray={m.status === "reserve" ? "0.12 0.08" : undefined} />
                      {m.type !== "chariot" && !m.type.startsWith("table") && m.type !== "presse_thermocollage" && <rect x={m.w / 2 - 0.42} y={-m.d / 2 + 0.08} width={0.3} height={m.d * 0.42} fill="#cfd8e3" stroke="#5b6878" strokeWidth={0.015} />}
                    </g>
                    <text x={m.x} y={m.y} fontSize={fs} textAnchor="middle" dominantBaseline="middle" className="wp-m-t">{m.label}</text>
                    <text x={m.x} y={m.y + fs * 1.05} fontSize={fs * 0.62} textAnchor="middle" dominantBaseline="middle" className="wp-m-s">{c?.short}{m.ws_id ? ` · ${m.ws_id}` : ""}</text>
                    {m.type !== "chariot" && <circle cx={op[0]} cy={op[1]} r={0.17} fill={m.status === "service" ? "#1f4e79" : "#b8bec7"} fillOpacity={0.85} />}
                  </g>
                );
              })}
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
            </svg>}
          </div>
          <div className="legend small"><span>● opératrice (côté de travail)</span><span>contour rouge = à vérifier</span><span>hachures rouges = en panne</span><span>pointillés = réserve</span><span>Pincez pour zoomer, glissez le fond pour vous déplacer</span></div>
        </section>

        {/* ------------------------------------------------ propriétés + contrôles */}
        <aside className="card wp-side">
          {selected ? <Props el={selected} plan={plan} writable={writable} upd={(patch) => updEl(selected.id, patch)} onDup={() => duplicate(selected.id)}
            onDel={() => remove(selected.id)} onRot={(d) => rotate(selected.id, d)} orgId={org.id} />
            : <p className="muted small">Touchez un élément du plan pour modifier ses propriétés. Raccourcis : Suppr, Ctrl+D (dupliquer), R (pivoter), flèches.</p>}
          <div className="card-head"><h3>Contrôles</h3><button className="link small" onClick={() => setShowChecks(!showChecks)}>{showChecks ? "masquer" : "afficher"}</button></div>
          {showChecks && <>
            <p className="muted small">Repères indicatifs pour l'implantation, pas une norme : faites valider les issues et circulations selon la réglementation applicable.</p>
            {issues.length === 0 ? <p className="small">Rien à signaler.</p> : <ul className="issues">
              {issues.map((i, k) => <li key={k} className={i.level === "err" ? "error" : i.level === "warn" ? "warning" : "info"} onClick={() => i.ids[0] && setSel(i.ids[0])} style={{ cursor: i.ids[0] ? "pointer" : "default" }}>{i.msg}</li>)}
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

// =================================================================== propriétés d'un élément
function Props({ el, plan, writable, upd, onDup, onDel, onRot, orgId }: {
  el: El; plan: WorkshopPlan; writable: boolean; upd: (p: Partial<El>) => void; onDup: () => void; onDel: () => void; onRot: (d: number) => void; orgId: string;
}) {
  const num = (v: string) => r2(Number(v.replace(",", ".")) || 0);
  const wsOptions = useMemo(() => {
    try { const d = JSON.parse(localStorage.getItem(gammeDraftKey(orgId)) || "null"); return (d?.ws ?? []).map((w: { id: string }) => w.id).filter(Boolean) as string[]; }
    catch { return [] as string[]; }
  }, [orgId]);
  const title = { machine: "Machine", wall: "Mur", pillar: "Poteau", door: "Porte / issue", aisle: "Allée", zone: "Zone" }[el.kind];
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
