import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, download, fmt, post } from "../lib/api";
import { canWrite, useSession } from "../lib/session";
import {
  buildTracks, bundleAt, clock, defaultLayout, newScenario,
  type Layout, type LayoutKind, type Scenario, type SimResult, type Simulation, type Sync, type Twin as TwinData,
} from "../lib/twin";

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

  const launch = useCallback(async (list: Scenario[], name = "") => {
    setBusy("sim"); setErr("");
    try {
      const body = { name, scenarios: list.map((s) => ({ ...s, run_id: s.run_id || null })), layout: layout ?? undefined };
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
        setData(d); setLayout(d.layout);
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
  }, [base, runId, org, pollSim]);

  const saveLayout = async () => {
    if (!layout) return;
    setBusy("layout");
    try {
      const r = await api<{ layout: Layout }>(`${base}/runs/${runId}/layout`, { method: "PUT", body: JSON.stringify(layout) });
      setLayout(r.layout); setData((d) => d && { ...d, layout_saved: true }); setSaved(true);
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
              <button key={k} className={layout.kind === k ? "on" : ""} onClick={() => { setLayout(defaultLayout(ids, k)); setDirty(true); setSaved(false); }}>
                {k === "line" ? "En ligne" : "En U"}</button>
            ))}
            <button className={layout.kind === "free" ? "on" : ""} disabled title="Faites glisser un poste">Libre</button>
          </div>
          {writable && <button className="btn" disabled={busy === "layout"} onClick={saveLayout}>{busy === "layout" ? "Enregistrement…" : saved ? "Implantation enregistrée ✓" : "Enregistrer l'implantation"}</button>}
        </div>
      </div>
      {err && <p className="notice err">{err}</p>}
      {dirty && items.length > 0 && <p className="notice warn">Implantation modifiée : relancez la simulation pour recalculer les transports et les déplacements.</p>}

      <div className="card">
        <LinePlan data={data} layout={layout} setLayout={(l) => { setLayout(l); setDirty(true); setSaved(false); }} res={current?.result ?? null}
          startHHMM={session?.shift_start?.slice(0, 5) || "08:00"} editable={writable} />
        {busy === "sim" && <p className="muted small"><span className="spinner inline" /> Simulation de la journée en cours…</p>}
        {items.length > 1 && (
          <div className="row small" style={{ marginTop: ".5rem" }}>Animer :
            {items.map((it, i) => <button key={i} className={`chipbtn ${i === animIdx ? "on" : ""}`} onClick={() => setAnimIdx(i)}>{it.name}</button>)}
          </div>
        )}
      </div>

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
function LinePlan({ data, layout, setLayout, res, startHHMM, editable }: {
  data: TwinData; layout: Layout; setLayout: (l: Layout) => void; res: SimResult | null; startHHMM: string; editable: boolean;
}) {
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
  const minX = Math.min(...xs) - 1.2, maxX = Math.max(...xs) + SW + 1.2, minY = Math.min(...ys) - 1.4, maxY = Math.max(...ys) + SH + 1.6;
  const W = (maxX - minX) * PX, H = (maxY - minY) * PX;
  const X = (m: number) => (m - minX) * PX, Y = (m: number) => (m - minY) * PX;
  const center = (sid: number | string) => { const p = pos[String(sid)] ?? { x: 0, y: 0 }; return { x: X(p.x + SW / 2), y: Y(p.y + SH / 2) }; };

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
      dots.push({ x: c.x - SW * PX / 2 - 9 - (k % 3) * 9, y: c.y - SH * PX / 2 + 6 + Math.floor(k / 3) * 9, size: b.size, kind: "q", key: b.id });
    } else if (st.kind === "work") {
      stState.get(st.st)?.working.add(st.w);
      const c = center(st.st);
      dots.push({ x: c.x + 10, y: c.y - 4, size: b.size, kind: "w", key: b.id });
    } else {
      const a = center(st.from), z = center(st.to);
      dots.push({ x: a.x + (z.x - a.x) * st.f, y: a.y + (z.y - a.y) * st.f - SH * PX / 2 - 6, size: b.size, kind: "m", key: b.id });
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
          {data.plan.stations.slice(0, -1).map((s, i) => {
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
