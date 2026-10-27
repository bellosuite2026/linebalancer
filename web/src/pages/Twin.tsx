import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, download, fmt, post } from "../lib/api";
import { canWrite, useSession } from "../lib/session";
import {
  buildTracks, bundleAt, clock, defaultLayout, newScenario,
  type Layout, type LayoutKind, type Placement, type Scenario, type SimResult, type Simulation, type Sync, type Twin as TwinData,
} from "../lib/twin";
import type { ProblemRow, Run } from "../lib/types";
import { MACHINE_CATALOG, ZONES, machineType, operatorPoint, type Machine, type WorkshopPlan } from "../lib/workshop";

const SPEEDS = [1, 5, 10, 30, 60];
const PX = 70;                       // pixels par mètre
const SW = 1.15, SH = 0.75;          // poste : 1,15 m × 0,75 m
const SCEN_COLORS = ["#1f4e79", "#c0392b", "#b7791f"];

const loadColor = (u: number) => (u >= 92 ? "#e4572e" : u >= 75 ? "#f0b429" : u >= 40 ? "#3fa66b" : "#a9b4c2");
const initials = (n: string) => n.split(/[\s.-]+/).filter(Boolean).slice(0, 2).map((p) => p[0]?.toUpperCase()).join("") || "?";

export default function Twin() {
  const { runId = "" } = useParams();
  const { currentOrg } = useSession();
  const org = currentOrg!;
  const writable = canWrite(org);
  const [data, setData] = useState<TwinData | null>(null);
  const [layout, setLayout] = useState<Layout | null>(null);
  const [dirty, setDirty] = useState(false);
  const [sim, setSim] = useState<Simulation | null>(null);
  const [animIdx, setAnimIdx] = useState(0);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState("");
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [saved, setSaved] = useState(false);
  const [placement, setPlacement] = useState<Placement | null>(null);
  const [wplan, setWplan] = useState<WorkshopPlan | null>(null);
  const [params, setParams] = useSearchParams();
  const nav = useNavigate();
  const autoLaunched = useRef(false);

  const base = `/v1/orgs/${org.id}`;

  const pollSim = useCallback(async (id: string) => {
    for (let i = 0; i < 120; i++) {
      const s = await api<Simulation>(`${base}/simulations/${id}`);
      setSim(s);
      if (s.status === "done" || s.status === "failed") return s;
      await new Promise((r) => setTimeout(r, 1500));
    }
    return null;
  }, [base]);

  const launch = useCallback(async (list: Scenario[], name = "", lay?: Layout) => {
    setBusy("sim"); setErr("");
    try {
      const L = lay ?? layout;
      const body = { name, scenarios: list.map((s) => ({ ...s, run_id: s.run_id || null })),
        layout: L ? { kind: L.kind, positions: L.positions, plan_id: L.plan_id ?? null, assignment: L.assignment ?? {} } : undefined };
      const row = await post<Simulation>(`${base}/runs/${runId}/simulate`, body);
      setSim(row); setAnimIdx(0);
      const done = await pollSim(row.id);
      if (done?.status === "failed") setErr(`La simulation a échoué : ${done.error || "erreur inconnue"}`);
      setDirty(false);
    } catch (e) { setErr((e as Error).message); } finally { setBusy(""); }
  }, [base, runId, layout, pollSim]);

  useEffect(() => {
    (async () => {
      try {
        const d = await api<TwinData>(`${base}/runs/${runId}/twin`);
        setData(d); setLayout(d.layout); setPlacement(d.placement);
        const wantPlan = params.get("plan"), compare = params.get("compare");
        if (wantPlan && canWrite(org) && !autoLaunched.current) {
          // « Simuler sur un plan » : placement automatique, enregistrement, simulation
          autoLaunched.current = true;
          setParams({}, { replace: true });
          setBusy("sim");
          const pl = d.placement?.plan_id === wantPlan ? d.placement
            : await post<Placement>(`${base}/runs/${runId}/twin/plan`, { plan_id: wantPlan, assignment: {} });
          const r = await api<{ layout: Layout; placement: Placement }>(`${base}/runs/${runId}/layout`, { method: "PUT",
            body: JSON.stringify({ kind: "free", positions: {}, plan_id: pl.plan_id, assignment: pl.assignment }) });
          setPlacement(r.placement); setLayout(r.layout); setSaved(true);
          setData((x) => x && { ...x, layout_saved: true });
          const list = compare ? [newScenario("Équilibrage sur le plan"), newScenario("Calcul d'origine", { run_id: compare })]
            : [newScenario(`Sur le plan ${pl.plan_name}`.slice(0, 60))];
          const row = await post<Simulation>(`${base}/runs/${runId}/simulate`, { name: list.map((x) => x.name).join(" / ").slice(0, 120),
            scenarios: list, layout: { kind: "free", positions: {}, plan_id: pl.plan_id, assignment: r.placement.assignment } });
          setSim(row); await pollSim(row.id); setBusy("");
          return;
        }
        const bn = d.plan.bottleneck_station;
        const bnWorker = d.plan.stations.find((s) => s.station === bn)?.worker_ids?.[0];
        setScenarios([
          newScenario("Référence"),
          newScenario(bnWorker ? `Absence ${d.plan.workers[bnWorker]?.name ?? bnWorker}` : "Efficience 75 %",
            bnWorker ? { absent: [bnWorker] } : { efficiency_pct: 75 }),
          newScenario("Paquets de 5", { bundle_size: 5 }),
        ]);
        const last = d.simulations.find((s) => s.status === "done");
        if (last) setSim(await api<Simulation>(`${base}/simulations/${last.id}`));
        else if (d.simulations[0] && d.simulations[0].status !== "failed") pollSim(d.simulations[0].id);
        else if (canWrite(org) && !autoLaunched.current) {
          autoLaunched.current = true;
          setBusy("sim");
          const row = await post<Simulation>(`${base}/runs/${runId}/simulate`, { name: "Référence", scenarios: [newScenario("Référence")] });
          setSim(row);
          await pollSim(row.id);
          setBusy("");
        }
      } catch (e) { setErr((e as Error).message); setBusy(""); }
    })();
  }, [base, runId, org, pollSim]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!placement?.plan_id) { setWplan(null); return; }
    if (wplan?.id === placement.plan_id) return;
    api<WorkshopPlan>(`${base}/workshop-plans/${placement.plan_id}`).then(setWplan).catch((e) => setErr((e as Error).message));
  }, [placement?.plan_id, base]); // eslint-disable-line react-hooks/exhaustive-deps

  const applyPlan = async (planId: string, assignment: Record<string, string[]> = {}) => {
    setBusy("plan"); setErr("");
    try {
      const pl = await post<Placement>(`${base}/runs/${runId}/twin/plan`, { plan_id: planId, assignment });
      setPlacement(pl); setLayout(pl.layout); setDirty(true); setSaved(false);
    } catch (e) { setErr((e as Error).message); } finally { setBusy(""); }
  };

  const balanceOnPlan = async (opts: { solver: string; mct: number; maxM: number }) => {
    if (!placement || !data?.run.problem_id) { setErr("Gamme du calcul introuvable : relancez un calcul depuis la gamme."); return; }
    setBusy("balance"); setErr("");
    try {
      const prob = await api<ProblemRow>(`${base}/problems/${data.run.problem_id}`);
      const inv = await api<{ workstations: (Record<string, unknown> & { id: string; machine_id?: string })[] }>(`${base}/workshop-plans/${placement.plan_id}/inventory`);
      const ws = inv.workstations.map(({ machine_id: _m, ...w }) => w);
      if (!ws.length) throw new Error("Le plan ne contient aucune machine (hors chariots).");
      const ids = new Set(ws.map((w) => w.id));
      const payload = prob.payload!;
      const problem = { ...payload, name: `${payload.name} · plan ${placement.plan_name}`.slice(0, 120), workstations: ws,
        workers: (payload.workers ?? []).map((w) => ({ ...w, assigned_station: w.assigned_station && ids.has(w.assigned_station) ? w.assigned_station : null })),
        machine_change_time: opts.mct, max_machines_per_station: opts.maxM };
      const run = await post<Run>(`${base}/runs`, { kind: "balance", solver: opts.solver, problem, save_problem: true, time_limit_seconds: opts.solver === "cp_sat" ? 30 : 10 });
      let r: Run = run;
      for (let i = 0; i < 150 && r.status !== "done" && r.status !== "failed"; i++) {
        await new Promise((ok) => setTimeout(ok, 1500));
        r = await api<Run>(`${base}/runs/${run.id}`);
      }
      if (r.status !== "done") throw new Error(r.error ? `Calcul en échec : ${r.error}` : "Le calcul prend trop de temps : retrouvez-le dans l'historique.");
      if (!r.stations_used) throw new Error("Aucune répartition trouvée avec les machines du plan : voir le détail du calcul (machines manquantes ?).");
      nav(`/jumeau/${run.id}?plan=${placement.plan_id}&compare=${runId}`);
    } catch (e) { setErr((e as Error).message); } finally { setBusy(""); }
  };

  const saveLayout = async () => {
    if (!layout) return;
    setBusy("layout");
    try {
      const body = placement ? { kind: "free", positions: {}, plan_id: placement.plan_id, assignment: placement.assignment } : { kind: layout.kind, positions: layout.positions };
      const r = await api<{ layout: Layout; placement: Placement | null }>(`${base}/runs/${runId}/layout`, { method: "PUT", body: JSON.stringify(body) });
      setLayout(r.layout); setPlacement(r.placement); setData((d) => d && { ...d, layout_saved: true }); setSaved(true);
    } catch (e) { setErr((e as Error).message); } finally { setBusy(""); }
  };

  if (err && !data) return <div className="page"><p className="notice err">{err}</p><Link to={`/calculs/${runId}`}>Retour au calcul</Link></div>;
  if (!data || !layout) return <div className="page muted">Chargement du jumeau numérique…</div>;

  const items = sim?.status === "done" ? sim.results?.scenarios ?? [] : [];
  const current = items[Math.min(animIdx, Math.max(0, items.length - 1))];
  const ids = data.plan.stations.map((s) => s.station);
  const session = data.sessions[0];

  return (
    <div className="page wide">
      <div className="page-head">
        <div>
          <h1>Jumeau numérique</h1>
          <p className="muted">{data.problem_name || "Ligne"} · {data.plan.stations.length} stations · {Object.keys(data.plan.workers).length} ouvrières
            {data.plan.cycle_time ? ` · cycle ${fmt.n(data.plan.cycle_time, 2)} min` : ""} · <Link to={`/calculs/${runId}`}>voir le calcul</Link></p>
        </div>
        <div className="row">
          <div className="seg">
            {(["line", "u"] as LayoutKind[]).map((k) => (
              <button key={k} className={!placement && layout.kind === k ? "on" : ""} onClick={() => { setPlacement(null); setLayout(defaultLayout(ids, k)); setDirty(true); setSaved(false); }}>
                {k === "line" ? "En ligne" : "En U"}</button>
            ))}
            <button className={!placement && layout.kind === "free" ? "on" : ""} disabled title="Faites glisser un poste">Libre</button>
          </div>
          <select value={placement?.plan_id ?? ""} disabled={busy === "plan"} onChange={(e) => { if (e.target.value) applyPlan(e.target.value); else { setPlacement(null); setLayout(defaultLayout(ids, "line")); setDirty(true); setSaved(false); } }}
            aria-label="Plan d'atelier" className={placement ? "on-select" : ""}>
            <option value="">{data.workshop_plans.length ? "Sur un plan d'atelier…" : "Aucun plan d'atelier"}</option>
            {data.workshop_plans.map((p) => <option key={p.id} value={p.id}>Plan : {p.name} ({p.version})</option>)}
          </select>
          {!data.workshop_plans.length && <Link to="/atelier/plan" className="small">Dessiner le plan</Link>}
          {writable && <button className="btn" disabled={busy === "layout"} onClick={saveLayout}>{busy === "layout" ? "Enregistrement…" : saved ? "Implantation enregistrée ✓" : "Enregistrer l'implantation"}</button>}
        </div>
      </div>
      {err && <p className="notice err">{err}</p>}
      {dirty && items.length > 0 && <p className="notice warn">Implantation modifiée : relancez la simulation pour recalculer les transports et les déplacements.</p>}

      <div className="card">
        <LinePlan data={data} layout={layout} setLayout={(l) => { setLayout(l); setDirty(true); setSaved(false); }} res={current?.result ?? null}
          startHHMM={session?.shift_start?.slice(0, 5) || "08:00"} editable={writable && !placement} placement={placement} wplan={wplan} />
        {busy === "plan" && <p className="muted small"><span className="spinner inline" /> Placement des stations sur le plan…</p>}
        {busy === "sim" && <p className="muted small"><span className="spinner inline" /> Simulation de la journée en cours…</p>}
        {items.length > 1 && (
          <div className="row small" style={{ marginTop: ".5rem" }}>Animer :
            {items.map((it, i) => <button key={i} className={`chipbtn ${i === animIdx ? "on" : ""}`} onClick={() => setAnimIdx(i)}>{it.name}</button>)}
          </div>
        )}
      </div>

      {placement && wplan && <PlanPanel data={data} placement={placement} wplan={wplan} writable={writable} busy={busy}
        onAssign={(a) => applyPlan(placement.plan_id, a)} onBalance={balanceOnPlan} />}

      {writable && (
        <ScenarioEditor data={data} scenarios={scenarios} setScenarios={setScenarios} busy={busy === "sim"} onRun={() => launch(scenarios)} />
      )}

      {sim && sim.status === "done" && sim.results && <Comparison sim={sim} base={base} onAnimate={setAnimIdx} />}
      {sim && (sim.status === "queued" || sim.status === "running") && <div className="card center-block"><div className="spinner" /><p>Simulation en cours…</p></div>}

      <SyncPanel data={data} base={base} runId={runId} />
    </div>
  );
}

// =================================================================== plan animé
function LinePlan({ data, layout, setLayout, res, startHHMM, editable, placement, wplan }: {
  data: TwinData; layout: Layout; setLayout: (l: Layout) => void; res: SimResult | null; startHHMM: string; editable: boolean;
  placement?: Placement | null; wplan?: WorkshopPlan | null;
}) {
  const planMode = !!(placement && wplan && placement.plan_id === wplan.id);
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(30);
  const svgRef = useRef<SVGSVGElement>(null);
  const drag = useRef<{ sid: string; dx: number; dy: number } | null>(null);
  const shift = res?.shift_minutes ?? 480;
  const tracks = useMemo(() => (res ? buildTracks(res) : []), [res]);
  const lastSt = data.plan.stations[data.plan.stations.length - 1]?.station;
  const finishTimes = useMemo(() => {
    const out: [number, number][] = [];
    for (const b of tracks) { const g = b.segs[b.segs.length - 1]; if (g && g.st === lastSt && isFinite(g.e)) out.push([g.e, b.size]); }
    return out.sort((a, b) => a[0] - b[0]);
  }, [tracks, lastSt]);
  const traceEnd = useMemo(() => (res?.trace.truncated ? Math.max(0, ...res.trace.events.map((e) => Number(e[0]))) : shift), [res, shift]);

  useEffect(() => { setT(0); setPlaying(false); }, [res]);
  useEffect(() => {
    if (!playing) return;
    let raf = 0, prev = performance.now();
    const step = (now: number) => {
      const dt = (now - prev) / 1000; prev = now;
      setT((v) => { const n = v + dt * speed / 60; if (n >= shift) { setPlaying(false); return shift; } return n; });
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [playing, speed, shift]);

  const pos = layout.positions;
  const xs = Object.values(pos).map((p) => p.x), ys = Object.values(pos).map((p) => p.y);
  const [minX, maxX, minY, maxY] = planMode
    ? [Math.min(-0.5, ...xs.map((v) => v - 1)), Math.max(Number(wplan!.width_m) + 0.5, ...xs.map((v) => v + 1)), Math.min(-0.5, ...ys.map((v) => v - 1)), Math.max(Number(wplan!.length_m) + 0.5, ...ys.map((v) => v + 1))]
    : [Math.min(...xs) - 1.2, Math.max(...xs) + SW + 1.2, Math.min(...ys) - 1.4, Math.max(...ys) + SH + 1.6];
  const W = (maxX - minX) * PX, H = (maxY - minY) * PX;
  const X = (m: number) => (m - minX) * PX, Y = (m: number) => (m - minY) * PX;
  const center = (sid: number | string) => {
    const p = pos[String(sid)] ?? { x: 0, y: 0 };
    return planMode ? { x: X(p.x), y: Y(p.y) } : { x: X(p.x + SW / 2), y: Y(p.y + SH / 2) };
  };
  const route = (a: number, b: number): { x: number; y: number }[] | null => {
    const r = placement?.routes?.[`${a}-${b}`];
    return planMode && r && r.length >= 2 ? r.map(([x, y]) => ({ x: X(x), y: Y(y) })) : null;
  };
  const along = (pts: { x: number; y: number }[], f: number) => {
    const seg = pts.slice(1).map((p, i) => Math.hypot(p.x - pts[i].x, p.y - pts[i].y));
    let L = seg.reduce((a, b) => a + b, 0) * Math.max(0, Math.min(1, f));
    for (let i = 0; i < seg.length; i++) {
      if (L <= seg[i] || i === seg.length - 1) { const k = seg[i] ? Math.min(1, L / seg[i]) : 0; return { x: pts[i].x + (pts[i + 1].x - pts[i].x) * k, y: pts[i].y + (pts[i + 1].y - pts[i].y) * k }; }
      L -= seg[i];
    }
    return pts[pts.length - 1];
  };

  const toMeters = (e: React.PointerEvent) => {
    const svg = svgRef.current!; const r = svg.getBoundingClientRect();
    return { x: (e.clientX - r.left) * (W / r.width) / PX + minX, y: (e.clientY - r.top) * (H / r.height) / PX + minY };
  };
  const onDown = (sid: string) => (e: React.PointerEvent) => {
    if (!editable) return;
    const m = toMeters(e); const p = pos[sid];
    drag.current = { sid, dx: m.x - p.x, dy: m.y - p.y };
    (e.target as Element).setPointerCapture?.(e.pointerId);
  };
  const onMove = (e: React.PointerEvent) => {
    const d = drag.current; if (!d) return;
    const m = toMeters(e);
    const snap = (v: number) => Math.round(v * 10) / 10;
    setLayout({ kind: "free", positions: { ...pos, [d.sid]: { x: snap(m.x - d.dx), y: snap(m.y - d.dy) } } });
  };
  const onUp = () => { drag.current = null; };

  // État courant
  const stState = new Map<number, { queue: number; working: Set<string> }>();
  data.plan.stations.forEach((s) => stState.set(s.station, { queue: 0, working: new Set() }));
  const dots: { x: number; y: number; size: number; kind: string; key: number }[] = [];
  const queueIdx = new Map<number, number>();
  for (const b of tracks) {
    const st = bundleAt(b, t);
    if (!st) continue;
    if (st.kind === "queue") {
      const s = stState.get(st.st); if (s) s.queue += b.size;
      const k = queueIdx.get(st.st) ?? 0; queueIdx.set(st.st, k + 1);
      const c = center(st.st);
      dots.push(planMode ? { x: c.x - 26 - (k % 3) * 9, y: c.y - 8 + Math.floor(k / 3) * 9, size: b.size, kind: "q", key: b.id }
        : { x: c.x - SW * PX / 2 - 9 - (k % 3) * 9, y: c.y - SH * PX / 2 + 6 + Math.floor(k / 3) * 9, size: b.size, kind: "q", key: b.id });
    } else if (st.kind === "work") {
      stState.get(st.st)?.working.add(st.w);
      const c = center(st.st);
      dots.push({ x: c.x + 10, y: c.y - 4, size: b.size, kind: "w", key: b.id });
    } else {
      const a = center(st.from), z = center(st.to);
      const rt = route(st.from, st.to);
      if (rt) { const q = along(rt, st.f); dots.push({ x: q.x, y: q.y, size: b.size, kind: "m", key: b.id }); }
      else dots.push({ x: a.x + (z.x - a.x) * st.f, y: a.y + (z.y - a.y) * st.f - (planMode ? 0 : SH * PX / 2 + 6), size: b.size, kind: "m", key: b.id });
    }
  }
  let done = 0; for (const [ft, n] of finishTimes) { if (ft <= t) done += n; else break; }
  const wip = [...stState.values()].reduce((a, s) => a + s.queue, 0);
  const simStations = new Map(res?.stations.map((s) => [s.station, s]) ?? []);
  const planStations = new Map(res?.plan.stations.map((s) => [s.station, s]) ?? []);
  const warnPairs = new Set((res?.lean.warnings ?? []).filter((w) => w.kind === "backtrack" || w.kind === "long_transfer")
    .map((w) => `${w.stations?.[0]}-${w.stations?.[1]}`));

  return (
    <div>
      <div className="twin-controls">
        <button className="btn primary" disabled={!res} onClick={() => { if (t >= shift) setT(0); setPlaying(!playing); }}>{playing ? "⏸ Pause" : "▶ Lecture"}</button>
        <div className="seg">{SPEEDS.map((s) => <button key={s} className={speed === s ? "on" : ""} onClick={() => setSpeed(s)}>x{s}</button>)}</div>
        <input type="range" min={0} max={shift} step={0.5} value={t} onChange={(e) => setT(Number(e.target.value))} disabled={!res} />
        <span className="twin-clock">{clock(startHHMM, t)}</span>
        <span className="muted small">{done} pièces finies · encours {wip} pcs</span>
      </div>
      {res?.trace.truncated && t > traceEnd && <p className="muted small">Animation détaillée limitée aux {Math.round(traceEnd)} premières minutes (paquets très petits) ; les résultats couvrent toute la journée.</p>}
      <div className="twin-canvas">
        <svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} style={{ minWidth: Math.min(W, 1100) }} onPointerMove={onMove} onPointerUp={onUp} onPointerLeave={onUp}>
          <defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0L10,5L0,10z" fill="#9aa6b5" /></marker>
            <marker id="arrw" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0,0L10,5L0,10z" fill="#c0392b" /></marker></defs>
          {Array.from({ length: Math.ceil(maxX - minX) }, (_, i) => <line key={`gx${i}`} x1={X(Math.ceil(minX) + i)} x2={X(Math.ceil(minX) + i)} y1={0} y2={H} className="twin-grid" />)}
          {Array.from({ length: Math.ceil(maxY - minY) }, (_, i) => <line key={`gy${i}`} y1={Y(Math.ceil(minY) + i)} y2={Y(Math.ceil(minY) + i)} x1={0} x2={W} className="twin-grid" />)}
          {planMode && <PlanUnderlay wplan={wplan!} placement={placement!} X={X} Y={Y} colorOf={(sid) => {
            const ss = simStations.get(sid); const st0 = data.plan.stations.find((x) => x.station === sid);
            const u = ss?.worker_util_max ?? ss?.utilization_pct ?? st0?.load_pct ?? 0; return res ? loadColor(u) : "#dfe6ee";
          }} />}
          {planMode && data.plan.stations.slice(0, -1).map((s, i) => {
            const nx = data.plan.stations[i + 1]; const rt = route(s.station, nx.station);
            if (!rt) return null;
            const bad = warnPairs.has(`${s.station}-${nx.station}`) || placement!.flow.backtracks.some((b) => b.from === s.station && b.to === nx.station);
            return <polyline key={`r${i}`} points={rt.map((p) => `${p.x},${p.y}`).join(" ")} fill="none" stroke={bad ? "#c0392b" : "#6f8fb3"}
              strokeWidth={bad ? 2.5 : 2} strokeDasharray={bad ? "6 4" : undefined} markerEnd={bad ? "url(#arrw)" : "url(#arr)"} opacity={0.85} />;
          })}
          {!planMode && data.plan.stations.slice(0, -1).map((s, i) => {
            const nx = data.plan.stations[i + 1]; const a = center(s.station), z = center(nx.station);
            const bad = warnPairs.has(`${s.station}-${nx.station}`);
            const dx = z.x - a.x, dy = z.y - a.y, L = Math.hypot(dx, dy) || 1, off = (SW * PX) / 2 + 2;
            return <line key={`f${i}`} x1={a.x + dx / L * off} y1={a.y + dy / L * off} x2={z.x - dx / L * off} y2={z.y - dy / L * off}
              stroke={bad ? "#c0392b" : "#9aa6b5"} strokeWidth={bad ? 2 : 1.5} strokeDasharray={bad ? "5 4" : undefined} markerEnd={bad ? "url(#arrw)" : "url(#arr)"} />;
          })}
          {data.plan.stations.map((s) => {
            const p = pos[String(s.station)]; const ss = simStations.get(s.station); const st = stState.get(s.station)!;
            const util = ss?.worker_util_max ?? ss?.utilization_pct ?? (s.load_pct ?? 0);
            const workers = planStations.get(s.station)?.worker_ids ?? s.worker_ids;
            const names = planStations.get(s.station)?.workers ?? s.workers;
            const isBn = res?.bottleneck === s.station;
            if (planMode) {
              const c = center(s.station); const virt = placement!.virtual.includes(s.station);
              return (
                <g key={s.station} transform={`translate(${c.x},${c.y})`}>
                  <rect x={-24} y={-11} width={48} height={22} rx={11} fill={res ? loadColor(util) : "#fff"} stroke={isBn ? "#7a1f12" : virt ? "#c0392b" : "#1f2a37"}
                    strokeWidth={isBn ? 3 : 1.2} strokeDasharray={virt ? "4 3" : undefined} />
                  <text x={0} y={4} textAnchor="middle" className="twin-st">{s.station}{res ? ` · ${Math.round(util)}%` : ""}</text>
                  {st.queue > 0 && <g transform="translate(26,-20)"><rect x={0} y={0} width={30} height={14} rx={7} fill={st.queue >= 40 ? "#c0392b" : st.queue >= 20 ? "#b7791f" : "#5b6878"} />
                    <text x={15} y={10.5} textAnchor="middle" className="twin-badge">{st.queue}</text></g>}
                  {workers.map((w, k) => {
                    const on = st.working.has(w);
                    return <g key={w + k} transform={`translate(${-14 + k * 20},22)`}>
                      <circle r={8} fill={on ? "#1f4e79" : "#fff"} stroke="#1f4e79" strokeWidth={1.5} />
                      <text y={3} textAnchor="middle" className={on ? "twin-w on" : "twin-w"}>{initials(names[k] ?? w)}</text><title>{names[k] ?? w}</title></g>;
                  })}
                  {isBn && <text x={0} y={-16} textAnchor="middle" className="twin-bn">goulot</text>}
                  <title>{`Station ${s.station} · ${s.operations.map((o) => `${o.id} ${o.name}`).join(" + ")}\n${fmt.n(s.minutes, 2)} min/pièce · ${names.join(", ") || "sans ouvrière"}${virt ? "\nAucune machine du plan : station placée à côté" : ""}${ss ? `\nOccupation ${ss.utilization_pct} % · encours max ${ss.max_wip}` : ""}`}</title>
                </g>
              );
            }
            return (
              <g key={s.station} transform={`translate(${X(p.x)},${Y(p.y)})`} onPointerDown={onDown(String(s.station))} style={{ cursor: editable ? "grab" : "default" }}>
                <rect width={SW * PX} height={SH * PX} rx={7} fill={res ? loadColor(util) : "#dfe6ee"} fillOpacity={0.9}
                  stroke={isBn ? "#7a1f12" : "#5b6878"} strokeWidth={isBn ? 3 : 1} />
                <text x={6} y={15} className="twin-st">{s.station}</text>
                <text x={SW * PX - 5} y={15} textAnchor="end" className="twin-small">{res ? `${Math.round(util)} %` : `${fmt.n(s.minutes, 2)} min`}</text>
                <text x={6} y={SH * PX - 6} className="twin-small">{s.operations.map((o) => o.id).join(", ").slice(0, 16)}</text>
                {st.queue > 0 && <g transform={`translate(${SW * PX - 4},${SH * PX + 4})`}>
                  <rect x={-34} y={0} width={34} height={15} rx={7} fill={st.queue >= 40 ? "#c0392b" : st.queue >= 20 ? "#b7791f" : "#5b6878"} />
                  <text x={-17} y={11} textAnchor="middle" className="twin-badge">{st.queue}</text></g>}
                {workers.map((w, k) => {
                  const on = st.working.has(w);
                  return <g key={w + k} transform={`translate(${12 + k * 22},${SH * PX + 14})`}>
                    <circle r={9} fill={on ? "#1f4e79" : "#fff"} stroke="#1f4e79" strokeWidth={1.5} />
                    <text y={3.5} textAnchor="middle" className={on ? "twin-w on" : "twin-w"}>{initials(names[k] ?? w)}</text>
                    <title>{names[k] ?? w}{on ? " (au travail)" : ""}</title></g>;
                })}
                {isBn && <text x={SW * PX / 2} y={-6} textAnchor="middle" className="twin-bn">goulot</text>}
                <title>{`Station ${s.station} · ${s.operations.map((o) => `${o.id} ${o.name}`).join(" + ")}\n${fmt.n(s.minutes, 2)} min/pièce · ${names.join(", ") || "sans ouvrière"}${ss ? `\nOccupation ${ss.utilization_pct} % · attente moy. ${ss.avg_wait_min} min · encours max ${ss.max_wip}` : ""}`}</title>
              </g>
            );
          })}
          {dots.map((d) => <rect key={d.key} x={d.x - 3.5} y={d.y - 3.5} width={7} height={7} rx={1.5}
            fill={d.kind === "w" ? "#ffffff" : d.kind === "m" ? "#1f4e79" : "#7b8794"} stroke="#1f2a37" strokeWidth={0.6} />)}
        </svg>
      </div>
      <div className="legend">
        <span><i style={{ background: "#3fa66b" }} />occupation &lt; 75 %</span><span><i style={{ background: "#f0b429" }} />75–92 %</span>
        <span><i style={{ background: "#e4572e" }} />&gt; 92 % (saturée)</span><span>▪ paquet ({res?.config?.bundle_size ?? 10} pcs)</span>
        <span>● ouvrière (pleine = au travail)</span>{editable && <span>Glissez un poste pour le déplacer (grille 10 cm).</span>}
      </div>
    </div>
  );
}

// =================================================================== scénarios
function ScenarioEditor({ data, scenarios, setScenarios, busy, onRun }: {
  data: TwinData; scenarios: Scenario[]; setScenarios: (s: Scenario[]) => void; busy: boolean; onRun: () => void;
}) {
  const upd = (i: number, patch: Partial<Scenario>) => setScenarios(scenarios.map((s, k) => (k === i ? { ...s, ...patch } : s)));
  const workers = data.plan.stations.flatMap((s) => s.worker_ids.map((w, k) => ({ id: w, name: s.workers[k] ?? w, station: s.station })));
  return (
    <div className="card">
      <div className="card-head"><h2>Scénarios « et si »</h2>
        <div className="row">
          {scenarios.length < 3 && <button className="btn ghost" onClick={() => setScenarios([...scenarios, newScenario(`Scénario ${scenarios.length + 1}`)])}>+ Scénario</button>}
          <button className="btn primary" disabled={busy || !scenarios.length} onClick={onRun}>{busy ? "Simulation…" : "Lancer la simulation"}</button>
        </div>
      </div>
      <div className="scen-grid">
        {scenarios.map((s, i) => (
          <div key={i} className="scen" style={{ borderTopColor: SCEN_COLORS[i] }}>
            <div className="row"><input value={s.name} onChange={(e) => upd(i, { name: e.target.value })} maxLength={60} />
              {scenarios.length > 1 && <button className="link" onClick={() => setScenarios(scenarios.filter((_, k) => k !== i))}>Retirer</button>}</div>
            {data.other_runs.length > 0 && <label>Modèle / gamme
              <select value={s.run_id ?? ""} onChange={(e) => upd(i, { run_id: e.target.value || null })}>
                <option value="">Ce calcul</option>
                {data.other_runs.map((r) => <option key={r.id} value={r.id}>Calcul du {fmt.date(r.created_at)} · {r.stations_used} st.</option>)}
              </select></label>}
            <label>Absentes {!s.run_id && <small className="muted">(réaffectation selon compétences)</small>}</label>
            <div className="chips-wrap">
              {workers.map((w) => {
                const on = s.absent.includes(w.id);
                return <button key={w.id + w.station} className={`chipbtn ${on ? "on danger" : ""}`} disabled={!!s.run_id}
                  onClick={() => upd(i, { absent: on ? s.absent.filter((x) => x !== w.id) : [...s.absent, w.id] })}>{w.name} <small>st.{w.station}</small></button>;
              })}
            </div>
            <label className="check"><input type="checkbox" checked={s.reassign} onChange={(e) => upd(i, { reassign: e.target.checked })} /> Réaffecter une ouvrière si un poste se vide</label>
            <label>Panne machine</label>
            {s.breakdowns.map((b, k) => (
              <div key={k} className="row tight">
                st.<select value={b.station} onChange={(e) => upd(i, { breakdowns: s.breakdowns.map((x, j) => (j === k ? { ...x, station: +e.target.value } : x)) })}>
                  {data.plan.stations.map((st) => <option key={st.station}>{st.station}</option>)}</select>
                à <input type="number" min={0} max={600} step={15} value={b.start_min} onChange={(e) => upd(i, { breakdowns: s.breakdowns.map((x, j) => (j === k ? { ...x, start_min: +e.target.value } : x)) })} /> min,
                <input type="number" min={5} max={600} step={5} value={b.duration_min} onChange={(e) => upd(i, { breakdowns: s.breakdowns.map((x, j) => (j === k ? { ...x, duration_min: +e.target.value } : x)) })} /> min
                <button className="link" onClick={() => upd(i, { breakdowns: s.breakdowns.filter((_, j) => j !== k) })}>×</button>
              </div>
            ))}
            {s.breakdowns.length < 5 && <button className="link small" onClick={() => upd(i, { breakdowns: [...s.breakdowns, { station: data.plan.bottleneck_station ?? data.plan.stations[0].station, start_min: 120, duration_min: 30 }] })}>+ ajouter une panne</button>}
            <label>Effectif par station</label>
            {Object.entries(s.operators).map(([st, n]) => (
              <div key={st} className="row tight">st. {st} : <input type="number" min={0} max={10} value={n}
                onChange={(e) => upd(i, { operators: { ...s.operators, [st]: +e.target.value } })} /> ouvrière(s)
                <button className="link" onClick={() => { const o = { ...s.operators }; delete o[st]; upd(i, { operators: o }); }}>×</button></div>
            ))}
            {!s.run_id && <select value="" onChange={(e) => { if (e.target.value) { const st = data.plan.stations.find((x) => String(x.station) === e.target.value)!; upd(i, { operators: { ...s.operators, [e.target.value]: st.operators + 1 } }); } }}>
              <option value="">+ changer l'effectif d'une station…</option>
              {data.plan.stations.filter((st) => !(String(st.station) in s.operators)).map((st) => <option key={st.station} value={st.station}>Station {st.station} ({st.operators} actuellement)</option>)}
            </select>}
            <div className="form-grid tight3">
              <label>Paquet (pcs)<input type="number" min={1} max={100} value={s.bundle_size} onChange={(e) => upd(i, { bundle_size: +e.target.value })} /></label>
              <label>Efficience %<input type="number" min={10} max={200} step={5} value={s.efficiency_pct} onChange={(e) => upd(i, { efficiency_pct: +e.target.value })} /></label>
              <label>Variabilité %<input type="number" min={0} max={60} step={5} value={s.variability_pct} onChange={(e) => upd(i, { variability_pct: +e.target.value })} /></label>
              <label>Durée (h)<input type="number" min={0.5} max={10} step={0.5} value={s.shift_minutes / 60} onChange={(e) => upd(i, { shift_minutes: Math.round(+e.target.value * 60) })} /></label>
            </div>
          </div>
        ))}
      </div>
      <p className="muted small">Durée simulée limitée à 10 h par scénario (serveur gratuit). Les écarts de quelques pièces entre deux scénarios proches relèvent du hasard de la variabilité.</p>
    </div>
  );
}

// =================================================================== comparaison
function Comparison({ sim, base, onAnimate }: { sim: Simulation; base: string; onAnimate: (i: number) => void }) {
  const [busy, setBusy] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const items = sim.results!.scenarios;
  const exportAs = async (ext: "xlsx" | "pdf") => {
    setBusy(ext);
    try { await download(`${base}/simulations/${sim.id}/export.${ext}`, `simulation_${sim.id.slice(0, 8)}.${ext}`); } finally { setBusy(""); }
  };
  const fmtV = (key: string, v: number | null) => (v == null ? "—" : key === "bottleneck" ? `Station ${v}` : fmt.n(v, 1));
  const better: Record<string, 1 | -1> = { pieces: 1, per_hour: 1, wip_max: -1, wip_avg: -1, lead_time_min: -1, avg_wait_min: -1, transport_m: -1, walk_m: -1 };
  return (
    <div className="card">
      <div className="card-head"><h2>Résultats {items.length > 1 ? "comparés" : ""}</h2>
        <div className="row">
          <button className="btn" disabled={busy === "xlsx"} onClick={() => exportAs("xlsx")}>{busy === "xlsx" ? "Préparation…" : "Excel"}</button>
          <button className="btn" disabled={busy === "pdf"} onClick={() => exportAs("pdf")}>{busy === "pdf" ? "Préparation…" : "Rapport PDF"}</button>
        </div>
      </div>
      <div className="table-wrap">
        <table className="cmp">
          <thead><tr><th>Indicateur</th>{items.map((it, i) => <th key={i} style={{ color: SCEN_COLORS[i] }}>{it.name}</th>)}</tr></thead>
          <tbody>
            {sim.results!.comparison.map((row) => (
              <tr key={row.key} className={row.key === "pieces" ? "strong" : ""}>
                <td>{row.label}</td>
                {row.values.map((v, i) => {
                  const ref = row.values[0];
                  const dir = better[row.key];
                  const delta = i > 0 && dir && ref && v != null ? ((v - ref) / ref) * 100 : null;
                  const cls = delta == null || Math.abs(delta) < 1 ? "" : delta * dir > 0 ? "up" : "down";
                  return <td key={i}>{fmtV(row.key, v)}{delta != null && Math.abs(delta) >= 1 && <small className={`delta ${cls}`}> {delta > 0 ? "+" : ""}{fmt.n(delta, 0)} %</small>}</td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="row" style={{ marginTop: ".6rem" }}>
        {items.map((it, i) => <button key={i} className="btn ghost" onClick={() => setOpen(open === i ? null : i)}>{open === i ? "Masquer" : "Détail"} : {it.name}</button>)}
      </div>
      {open != null && items[open] && (() => {
        const r = items[open].result;
        return (
          <div className="scen-detail">
            <div className="row"><button className="btn" onClick={() => onAnimate(open)}>Animer ce scénario</button></div>
            {(r.notes.length > 0 || r.lean.warnings.length > 0) && <ul className="issues">
              {r.notes.map((n, k) => <li key={`n${k}`} className="info">{n}</li>)}
              {r.lean.warnings.map((w, k) => <li key={`w${k}`} className="warning"><b>Lean</b>{w.message}</li>)}
            </ul>}
            <p className="muted small">Implantation : {r.lean.kind === "u" ? "cellule en U" : r.lean.kind === "free" ? "libre" : "en ligne"} · {fmt.n(r.lean.meters_per_bundle, 1)} m parcourus par paquet · longueur {fmt.n(r.lean.line_length_m, 1)} m</p>
            <div className="table-wrap"><table>
              <thead><tr><th>Station</th><th>Ouvrières</th><th>Pièces</th><th>Occupation</th><th>Attente moy.</th><th>Encours max</th><th>Arrêt</th></tr></thead>
              <tbody>{r.stations.map((s, k) => (
                <tr key={s.station} className={s.station === r.bottleneck ? "row-over" : ""}>
                  <td>{s.station}{s.station === r.bottleneck && <span className="badge warn">goulot</span>}</td>
                  <td>{r.plan.stations[k]?.workers.join(", ") || "—"}</td><td>{s.pieces}</td>
                  <td><span className="meter"><div className={s.utilization_pct > 92 ? "over" : ""} style={{ width: `${Math.min(100, s.utilization_pct)}%` }} /></span>{fmt.n(s.utilization_pct, 0)} %</td>
                  <td>{fmt.n(s.avg_wait_min, 1)} min</td><td>{s.max_wip} pcs</td><td>{s.down_min ? `${fmt.n(s.down_min, 0)} min` : "—"}</td>
                </tr>))}</tbody>
            </table></div>
          </div>
        );
      })()}
    </div>
  );
}

// =================================================================== réel vs simulé
function SyncPanel({ data, base, runId }: { data: TwinData; base: string; runId: string }) {
  const [sid, setSid] = useState(data.sessions[0]?.id ?? "");
  const [qty, setQty] = useState("");
  const [doneBefore, setDoneBefore] = useState("");
  const [res, setRes] = useState<Sync | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const run = useCallback(async () => {
    if (!sid) return;
    setBusy(true); setErr("");
    try {
      const q = new URLSearchParams({ session_id: sid });
      if (qty) q.set("order_qty", qty);
      if (doneBefore) q.set("order_done", doneBefore);
      setRes(await api<Sync>(`${base}/runs/${runId}/twin/sync?${q}`));
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }, [sid, qty, doneBefore, base, runId]);
  useEffect(() => { if (sid) run(); }, [sid]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!data.sessions.length) return (
    <div className="card"><h2>Réel vs simulé</h2>
      <p className="muted">Aucune session de production suivie depuis ce calcul. Démarrez-en une depuis <Link to={`/production?calcul=${runId}`}>Production</Link> : les saisies de la tablette recaleront la simulation et donneront la prévision de fin de journée.</p></div>
  );
  const max = res ? Math.max(1, ...res.hourly.flatMap((h) => [h.real, h.simulated ?? 0, h.target ?? 0])) : 1;
  return (
    <div className="card">
      <div className="card-head"><h2>Réel vs simulé</h2>
        <div className="row">
          <select value={sid} onChange={(e) => setSid(e.target.value)}>
            {data.sessions.map((s) => <option key={s.id} value={s.id}>{fmt.day(s.session_date)} · {s.model || "session"} {s.status === "open" ? "(ouverte)" : ""}</option>)}
          </select>
          <input type="number" placeholder="Commande (pcs)" value={qty} onChange={(e) => setQty(e.target.value)} style={{ width: 140 }} />
          <input type="number" placeholder="Déjà produit" value={doneBefore} onChange={(e) => setDoneBefore(e.target.value)} style={{ width: 120 }} />
          <button className="btn" disabled={busy} onClick={run}>{busy ? "Calcul…" : "Actualiser"}</button>
        </div>
      </div>
      {err && <p className="notice err">{err}</p>}
      {res && <>
        <div className="kpis">
          <div className="kpi"><span>Réalisé</span><b>{res.output}</b><small>{fmt.n(res.elapsed_minutes, 0)} / {fmt.n(res.shift_minutes, 0)} min</small></div>
          <div className="kpi ok"><span>Prévision fin de journée</span><b>{res.forecast_end_of_day}</b><small>simulation recalée{res.forecast_linear != null ? ` · au rythme actuel ${res.forecast_linear}` : ""}</small></div>
          <div className="kpi"><span>Journée simulée (100 %)</span><b>{res.planned_day}</b><small>objectif {fmt.n(res.target_shift, 0)}</small></div>
          <div className="kpi"><span>Efficience réelle</span><b>{res.real_efficiency != null ? `${fmt.n(res.real_efficiency, 0)} %` : "—"}</b><small>journée recalée : {res.calibrated_day} pcs</small></div>
          <div className="kpi"><span>Goulot calculé / observé</span><b>{res.bottleneck_planned ?? "—"} / {res.bottleneck_observed ?? "—"}</b><small>stations</small></div>
          {res.order && <div className="kpi warn"><span>Fin de commande prévue</span><b>{fmt.day(res.order.finish_date)}</b><small>{res.order.left_after_today} pcs après aujourd'hui · {res.order.extra_days} j ouvrés</small></div>}
        </div>
        <div className="hbars">
          {res.hourly.map((h) => (
            <div key={h.hour} className="hbar">
              <div className="hbar-cols">
                <div style={{ height: `${(h.simulated ?? 0) / max * 100}%` }} className="sim" title={`Simulé : ${h.simulated}`} />
                <div style={{ height: `${h.real / max * 100}%` }} className="real" title={`Réel : ${h.real}`} />
              </div>
              <span>{h.hour} h</span>
            </div>
          ))}
        </div>
        <div className="legend"><span><i style={{ background: "#b9c9dc" }} />simulé (temps standard)</span><span><i style={{ background: "#1f4e79" }} />réel (pièces finies)</span></div>
        {res.notes.length > 0 && <ul className="issues" style={{ marginTop: ".6rem" }}>{res.notes.map((n, i) => <li key={i} className="info">{n}</li>)}</ul>}
        <div className="table-wrap" style={{ marginTop: ".6rem" }}><table>
          <thead><tr><th>Station</th><th>Réel</th><th>Simulé à date</th><th>Simulé journée</th><th>Efficience réelle</th><th>Arrêts</th></tr></thead>
          <tbody>{res.stations.map((s) => (
            <tr key={s.station} className={s.real < s.simulated_to_date * 0.8 ? "row-over" : ""}>
              <td>{s.station}</td><td>{s.real}</td><td>{s.simulated_to_date}</td><td>{s.simulated_day}</td>
              <td>{s.real_efficiency != null ? `${fmt.n(s.real_efficiency, 0)} %` : "—"}</td><td>{s.downtime_minutes ? `${fmt.n(s.downtime_minutes, 0)} min` : "—"}</td>
            </tr>))}</tbody>
        </table></div>
      </>}
    </div>
  );
}

// =================================================================== plan d'atelier sous la ligne
function PlanUnderlay({ wplan, placement, X, Y, colorOf }: {
  wplan: WorkshopPlan; placement: Placement; X: (m: number) => number; Y: (m: number) => number; colorOf: (sid: number) => string;
}) {
  const owner = new Map<string, number>();
  for (const [sid, mids] of Object.entries(placement.assignment)) for (const m of mids) owner.set(m, Number(sid));
  const k = X(1) - X(0);
  return (
    <g className="twin-underlay">
      <rect x={X(0)} y={Y(0)} width={Number(wplan.width_m) * k} height={Number(wplan.length_m) * k} fill="#fbfaf7" stroke="#d5d0c4" />
      {wplan.elements.map((e) => {
        if (e.kind === "zone") return <g key={e.id}><rect x={X(e.x)} y={Y(e.y)} width={e.w * k} height={e.h * k} fill={ZONES[e.zone]?.color ?? "#eee"} fillOpacity={0.35} stroke="#c9c2b0" strokeDasharray="6 4" />
          <text x={X(e.x) + 6} y={Y(e.y) + 15} className="twin-small" fill="#7a735f">{e.name || ZONES[e.zone]?.label}</text></g>;
        if (e.kind === "aisle") return <rect key={e.id} x={X(e.x)} y={Y(e.y)} width={e.w * k} height={e.h * k} fill="#efece4" stroke="#c9c2b0" strokeDasharray="5 4" />;
        return null;
      })}
      {wplan.elements.map((e) => {
        if (e.kind === "wall") return <line key={e.id} x1={X(e.x1)} y1={Y(e.y1)} x2={X(e.x2)} y2={Y(e.y2)} stroke="#3a3f47" strokeWidth={Math.max(2, e.thickness * k)} strokeLinecap="square" />;
        if (e.kind === "pillar") return <rect key={e.id} x={X(e.x - e.w / 2)} y={Y(e.y - e.d / 2)} width={e.w * k} height={e.d * k} fill="#3a3f47" />;
        if (e.kind === "door") return <g key={e.id} transform={`translate(${X(e.x)},${Y(e.y)}) rotate(${e.rot})`}>
          <rect x={-e.width * k / 2} y={-0.14 * k} width={e.width * k} height={0.28 * k} fill="#fbfaf7" />
          <path d={`M${-e.width * k / 2},0 L${-e.width * k / 2},${-e.width * k} A${e.width * k},${e.width * k} 0 0 1 ${e.width * k / 2},0`} fill="none" stroke={e.exit ? "#1f8a5b" : "#8a8f98"} strokeWidth={1.5} /></g>;
        if (e.kind === "machine") {
          const sid = owner.get(e.id); const used = sid != null; const op = operatorPoint(e);
          return <g key={e.id}>
            <g transform={`translate(${X(e.x)},${Y(e.y)}) rotate(${e.rot})`}>
              <rect x={-e.w * k / 2} y={-e.d * k / 2} width={e.w * k} height={e.d * k} rx={4}
                fill={e.status === "panne" ? "#f6d0d0" : used ? colorOf(sid!) : "#ffffff"} fillOpacity={used ? 0.95 : 0.8}
                stroke={used ? "#1f2a37" : "#a3abb6"} strokeWidth={used ? 1.4 : 1} strokeDasharray={e.status === "reserve" ? "5 3" : undefined} />
            </g>
            <text x={X(e.x)} y={Y(e.y) + 4} textAnchor="middle" className="twin-small" fill={used ? "#1f2a37" : "#8a929d"}>{e.label}</text>
            {!used && e.type !== "chariot" && <circle cx={X(op[0])} cy={Y(op[1])} r={3} fill="#c3c9d1" />}
            <title>{`${e.label} · ${MACHINE_CATALOG[e.type]?.label ?? e.type}${e.status !== "service" ? ` (${e.status === "panne" ? "en panne" : "réserve"})` : ""}${used ? ` · station ${sid}` : " · non utilisée"}`}</title>
          </g>;
        }
        return null;
      })}
    </g>
  );
}

// =================================================================== association stations ↔ machines
function PlanPanel({ data, placement, wplan, writable, busy, onAssign, onBalance }: {
  data: TwinData; placement: Placement; wplan: WorkshopPlan; writable: boolean; busy: string;
  onAssign: (a: Record<string, string[]>) => void; onBalance: (o: { solver: string; mct: number; maxM: number }) => void;
}) {
  const [showBal, setShowBal] = useState(false);
  const [solver, setSolver] = useState("rpw");
  const [mct, setMct] = useState(String(placement.travel.minutes || 0));
  const [maxM, setMaxM] = useState("2");
  useEffect(() => { setMct(String(placement.travel.minutes || 0)); }, [placement.travel.minutes]);
  const machines = wplan.elements.filter((e): e is Machine => e.kind === "machine" && e.type !== "chariot");
  const byId = new Map(machines.map((m) => [m.id, m]));
  const owner = new Map<string, number>();
  for (const [sid, mids] of Object.entries(placement.assignment)) for (const m of mids) owner.set(m, Number(sid));
  const transfer = new Map(placement.flow.transfers.map((t) => [t.from, t]));
  const setMachine = (sid: number, idx: number, mid: string) => {
    const a: Record<string, string[]> = {};
    for (const s of data.plan.stations) a[String(s.station)] = [...(placement.assignment[String(s.station)] ?? [])];
    const cur = a[String(sid)];
    if (mid) { for (const k of Object.keys(a)) a[k] = a[k].filter((m) => m !== mid); if (idx < cur.length) cur[idx] = mid; else cur.push(mid); a[String(sid)] = cur.filter(Boolean); }
    else a[String(sid)] = cur.filter((_, i) => i !== idx);
    onAssign(a);
  };
  const statusTxt = (m: Machine) => (m.status === "service" ? "" : m.status === "panne" ? " (en panne)" : " (réserve)");
  return (
    <div className="card">
      <div className="card-head"><h2>Stations sur le plan « {placement.plan_name} »</h2>
        <div className="row">
          <Link className="btn small" to={`/atelier/plan?id=${placement.plan_id}`}>Modifier le plan</Link>
          {writable && <button className="btn small" disabled={!!busy} onClick={() => onAssign({})}>Association automatique</button>}
          {writable && <button className="btn small primary" disabled={!!busy} onClick={() => setShowBal(!showBal)}>Simuler l'équilibrage sur ce plan</button>}
        </div>
      </div>
      <div className="kpis">
        <div className="kpi"><span>Parcours d'un paquet</span><b>{fmt.n(placement.flow.meters_per_bundle, 1)} m</b><small>par les allées</small></div>
        <div className="kpi"><span>Retours en arrière</span><b>{placement.flow.backtracks.length}</b><small>{placement.flow.u_cell ? "cellule en U détectée" : "sens du flux : 1re → dernière station"}</small></div>
        <div className="kpi"><span>Entrée ↔ sortie</span><b>{fmt.n(placement.flow.entry_exit_m, 1)} m</b><small>emprise {fmt.n(placement.flow.extent_m, 1)} m</small></div>
        <div className="kpi"><span>Machines libres</span><b>{placement.unused.length}</b><small>en service, non utilisées</small></div>
      </div>
      {showBal && writable && (
        <div className="notice warn">
          <p><b>Équilibrage avec les machines réelles du plan</b> : un nouveau calcul est lancé avec la même gamme, les postes = machines en service du plan
            (pannes et réserve exclues) et un temps de déplacement par machine supplémentaire tenue par une ouvrière, déduit des distances du plan
            {placement.travel.neighbour_m ? ` (machine voisine à ${fmt.n(placement.travel.neighbour_m, 2)} m en médiane)` : ""}. Puis la journée est simulée sur le plan et comparée au calcul d'origine.</p>
          <div className="row">
            <label>Solveur<select value={solver} onChange={(e) => setSolver(e.target.value)}><option value="rpw">RPW (rapide)</option><option value="cp_sat">CP-SAT (optimal)</option></select></label>
            <label>Déplacement (min/pièce/machine)<input type="number" min={0} max={2} step={0.01} value={mct} onChange={(e) => setMct(e.target.value)} style={{ width: 120 }} /></label>
            <label>Machines max par ouvrière<input type="number" min={1} max={3} value={maxM} onChange={(e) => setMaxM(e.target.value)} style={{ width: 90 }} /></label>
            <button className="btn primary" disabled={busy === "balance"} onClick={() => onBalance({ solver, mct: Math.max(0, Number(mct.replace(",", ".")) || 0), maxM: Math.min(3, Math.max(1, Number(maxM) || 1)) })}>
              {busy === "balance" ? "Calcul en cours…" : "Lancer le calcul puis la simulation"}</button>
          </div>
        </div>
      )}
      {(placement.notes.length > 0 || placement.flow.warnings.length > 0) && <ul className="issues">
        {placement.flow.warnings.map((w, k) => <li key={`w${k}`} className="warning">{w.message}</li>)}
        {placement.notes.map((n, k) => <li key={`n${k}`} className="info">{n}</li>)}
      </ul>}
      <div className="table-wrap"><table>
        <thead><tr><th>Station</th><th>Opérations</th><th>Machine(s) demandée(s)</th><th>Machine(s) du plan</th><th>Vers la suivante</th></tr></thead>
        <tbody>{data.plan.stations.map((s) => {
          const mids = placement.assignment[String(s.station)] ?? [];
          const types = (s.machine_types?.length ? s.machine_types : [...new Set(s.operations.map((o) => o.machine_type).filter(Boolean))]);
          const t = transfer.get(s.station);
          const slots = Math.max(1, mids.length, Math.min(3, types.length * Math.max(1, s.operators)));
          return (
            <tr key={s.station} className={placement.virtual.includes(s.station) ? "row-over" : ""}>
              <td>{s.station}</td>
              <td className="small">{s.operations.map((o) => o.id).join(", ")}</td>
              <td className="small">{types.join(", ") || "manuel"}{s.operators > 1 ? ` × ${s.operators}` : ""}</td>
              <td className="row tight">{Array.from({ length: slots }, (_, i) => (
                <select key={i} value={mids[i] ?? ""} disabled={!writable || !!busy} onChange={(e) => setMachine(s.station, i, e.target.value)}>
                  <option value="">— aucune —</option>
                  {[...machines].sort((a, b) => Number(types.includes(machineType(b))) - Number(types.includes(machineType(a))) || a.label.localeCompare(b.label, "fr", { numeric: true }))
                    .map((m) => <option key={m.id} value={m.id}>{m.label} · {MACHINE_CATALOG[m.type]?.label ?? m.type}{statusTxt(m)}{owner.has(m.id) && owner.get(m.id) !== s.station ? ` (st. ${owner.get(m.id)})` : ""}</option>)}
                </select>))}
                {mids.some((m) => byId.get(m) && !types.includes(machineType(byId.get(m)!)) && types.length > 0) && <span className="badge warn">autre type</span>}
              </td>
              <td>{t ? `${fmt.n(t.meters, 1)} m` : "—"}{t && t.meters > 1.8 * t.straight + 1 ? <small className="muted"> ({fmt.n(t.straight, 1)} à vol d'oiseau)</small> : null}</td>
            </tr>);
        })}</tbody>
      </table></div>
      {placement.missing.length > 0 && <p className="notice warn">Machines manquantes sur le plan : {placement.missing.map((m) => `st. ${m.station} (${m.type})`).join(", ")}. Ajoutez-les au plan ou choisissez une machine à la main.</p>}
      {placement.unused.length > 0 && <p className="muted small">Machines en service non utilisées : {placement.unused.map((id) => byId.get(id)?.label ?? id).join(", ")}.</p>}
      <p className="muted small">Association automatique : machine liée au poste (WS) de la station, sinon même type de machine en suivant les n° de machine (M01, M02…), puis la plus proche. Les distances sont mesurées de poste opératrice à poste opératrice en contournant murs, poteaux et machines.</p>
    </div>
  );
}
