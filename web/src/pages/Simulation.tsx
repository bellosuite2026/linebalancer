// Simulation à événements discrets de l'atelier (type FlexSim) : modèle généré depuis un calcul et le
// plan d'atelier, réglages, scénarios × réplications, lecture 2D/3D synchronisée de la trace et
// tableaux de bord.
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, download, fmt, post } from "../lib/api";
import { canWrite, useSession } from "../lib/session";
import {
  STATE_COLOR, STATE_LABEL, STATION_STATES, TR_LABEL, TraceCursor, fmtClock, lotColor,
  type CI, type DesModel, type DesModelResponse, type DesResults, type DesSim, type Frame, type ScenarioResult,
} from "../lib/des";
import type { WorkshopPlan } from "../lib/workshop";
import SimCanvas2D from "../components/SimCanvas2D";
import { Bars, Gantt, Histogram, Legend, LineChart, StateBars, StatePie } from "../components/SimCharts";

const SimScene3D = lazy(() => import("../components/SimScene3D"));
const SPEEDS = [1, 10, 30, 60, 120, 300, 600];
const SCEN_COLORS = ["#1f4e79", "#e67e22", "#8e44ad"];
type View = "2d" | "3d" | "both";
type Tab = "states" | "wip" | "throughput" | "lead" | "operators" | "compare";
interface ScenarioForm { name: string; bundle_size: string; efficiency: string; cv: string; transporters: string; transfer: string;
  mtbf: string; mttr: string; defect: string; setup: string; absent: string[] }
const emptyForm = (name: string): ScenarioForm => ({ name, bundle_size: "", efficiency: "", cv: "", transporters: "", transfer: "", mtbf: "", mttr: "", defect: "", setup: "", absent: [] });

function formToOverrides(f: ScenarioForm): Record<string, unknown> {
  const o: Record<string, Record<string, unknown> | unknown> = {};
  const settings: Record<string, unknown> = {}, source: Record<string, unknown> = {};
  const num = (v: string) => (v.trim() === "" ? null : Number(v.replace(",", ".")));
  if (num(f.bundle_size) != null) source.bundle_size = num(f.bundle_size);
  if (num(f.efficiency) != null) settings.efficiency = num(f.efficiency)! / 100;
  if (num(f.cv) != null) settings.dist = { kind: "normal", cv: num(f.cv)! / 100 };
  if (num(f.mtbf) != null) settings.mtbf_min = num(f.mtbf);
  if (num(f.mttr) != null) settings.mttr_min = num(f.mttr);
  if (num(f.defect) != null) settings.defect_pct = num(f.defect);
  if (num(f.setup) != null) settings.setup_min = num(f.setup);
  if (f.transfer) settings.transfer = f.transfer;
  if (num(f.transporters) != null) o.transporters = { count: num(f.transporters), capacity: 4, speed_m_per_min: 60 };
  if (Object.keys(settings).length) o.settings = settings;
  if (Object.keys(source).length) o.source = source;
  return o;
}

const ciTxt = (v: CI | undefined, d = 1) => {
  if (!v || v.mean == null) return "—";
  if (typeof v.mean === "string") return `Poste ${v.mean}`;
  const m = fmt.n(v.mean, d);
  return (v.n ?? 1) > 1 && v.lo != null ? `${m} ± ${fmt.n((Number(v.hi) - Number(v.lo)) / 2, d)}` : m;
};

export default function Simulation() {
  const { runId } = useParams();
  const [sp, setSp] = useSearchParams();
  const { currentOrg } = useSession();
  const org = currentOrg!;
  const base = `/v1/orgs/${org.id}`;
  const writable = canWrite(org);
  const [data, setData] = useState<DesModelResponse | null>(null);
  const [model, setModel] = useState<DesModel | null>(null);
  const [planId, setPlanId] = useState<string>(sp.get("plan") ?? "");
  const [forms, setForms] = useState<ScenarioForm[]>([emptyForm("Référence")]);
  const [reps, setReps] = useState(5);
  const [sim, setSim] = useState<DesSim | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [view, setView] = useState<View>("both");
  const [scIdx, setScIdx] = useState(0);
  const [tab, setTab] = useState<Tab>("states");
  const [picked, setPicked] = useState<string | null>(null);
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(60);
  const [openSt, setOpenSt] = useState(false);

  // ---------------------------------------------------------------- chargement
  const load = useCallback(async (pid: string) => {
    setErr("");
    try {
      const d = await api<DesModelResponse>(`${base}/runs/${runId}/des/model${pid ? `?plan_id=${pid}` : ""}`);
      setData(d); setModel(d.model);
      if (!pid && d.model.plan_id) setPlanId(d.model.plan_id);
      const last = sp.get("sim") ?? d.simulations.find((s) => s.status === "done")?.id;
      if (last) openSim(last);
    } catch (e) { setErr((e as Error).message); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [base, runId]);
  useEffect(() => { load(planId); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [load]);

  const openSim = async (id: string) => {
    try {
      const s = await api<DesSim>(`${base}/simulations/${id}`);
      setSim(s); setScIdx(0); setT(0); setPlaying(false);
      if (s.status === "queued" || s.status === "running") poll(id);
    } catch (e) { setErr((e as Error).message); }
  };
  const pollRef = useRef<number>();
  const poll = (id: string) => {
    window.clearTimeout(pollRef.current);
    pollRef.current = window.setTimeout(async () => {
      try {
        const s = await api<DesSim>(`${base}/simulations/${id}`);
        setSim(s);
        if (s.status === "queued" || s.status === "running") poll(id);
        else { setBusy(false); if (s.status === "done") { setT(0); setPlaying(true); setSp((p) => { p.set("sim", id); return p; }, { replace: true }); } }
      } catch (e) { setErr((e as Error).message); setBusy(false); }
    }, 1800);
  };
  useEffect(() => () => window.clearTimeout(pollRef.current), []);

  const run = async () => {
    if (!model) return;
    setBusy(true); setErr("");
    try {
      const scenarios = forms.map((f, i) => ({ name: f.name || `Scénario ${i + 1}`, overrides: i === 0 ? {} : formToOverrides(f), absent: i === 0 ? [] : f.absent }));
      const s = await post<DesSim>(`${base}/runs/${runId}/des`, { name: scenarios.map((x) => x.name).join(" / ").slice(0, 120), model, scenarios, replications: reps, plan_id: planId || null });
      setSim(s); poll(s.id);
    } catch (e) { setErr((e as Error).message); setBusy(false); }
  };

  // ---------------------------------------------------------------- lecture
  const results: DesResults | null = sim?.status === "done" ? sim.results ?? null : null;
  const sc = results?.scenarios[scIdx];
  const res: ScenarioResult | undefined = sc?.result;
  const vModel = res?.model ?? model;
  const plan: WorkshopPlan | null = data?.workshop_plan && (!vModel?.plan_id || vModel.plan_id === data.workshop_plan.id) ? data.workshop_plan : null;
  const cursor = useMemo(() => (res?.trace && res.model ? new TraceCursor(res.trace, res.model) : null), [res]);
  const T = res?.shift_minutes ?? model?.shift.minutes ?? 480;
  const until = res?.trace?.until ?? T;
  const frame: Frame | null = useMemo(() => (cursor ? cursor.frame(Math.min(t, until)) : null), [cursor, t, until]);

  useEffect(() => {
    if (!playing || !cursor) return;
    let raf = 0, last = performance.now();
    const tick = (now: number) => {
      const dt = Math.min(0.25, (now - last) / 1000); last = now;
      setT((x) => { const nx = x + (dt * speed) / 60; if (nx >= until) { setPlaying(false); return until; } return nx; });
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing, speed, cursor, until]);

  // ---------------------------------------------------------------- édition du modèle
  const setS = (k: string, v: unknown) => setModel((m) => (m ? { ...m, settings: { ...m.settings, [k]: v } } : m));
  const setSrc = (k: string, v: unknown) => setModel((m) => (m ? { ...m, source: { ...m.source, [k]: v } } : m));
  const setStation = (id: string, k: string, v: unknown) => setModel((m) => (m ? { ...m, stations: m.stations.map((s) => (s.id === id ? { ...s, [k]: v } : s)) } : m));
  const numIn = (v: unknown, d: number) => (v == null || v === "" ? d : Number(v));
  const S = model?.settings ?? {};
  const dist = S.dist ?? { kind: "normal", cv: 0.1 };

  if (err && !data) return <div className="page"><p className="notice err">{err}</p><Link to="/jumeau">← Jumeau numérique</Link></div>;
  if (!data || !model) return <div className="page muted">Génération du modèle de simulation…</div>;

  const opName = (id: string) => model.operators.find((o) => o.id === id)?.name ?? id;
  const kpi = res?.kpis, rk = res?.replications.kpis;
  const pickedSt = res?.stations.find((s) => s.id === picked);

  return (
    <div className="page sim-page">
      <div className="page-head">
        <div>
          <h1>Simulation de l'atelier</h1>
          <p className="muted">{data.problem_name || model.name} · {data.summary.stations} postes · {data.summary.operators} opérateurs · SAM {fmt.n(data.summary.sam_total, 2)} min ·
            {" "}<Link to={`/calculs/${runId}`}>calcul</Link> · <Link to={`/jumeau/${runId}`}>jumeau numérique</Link></p>
        </div>
        <div className="actions">
          <label className="small">Plan d'atelier{" "}
            <select value={planId} onChange={(e) => { setPlanId(e.target.value); setSp((p) => { if (e.target.value) p.set("plan", e.target.value); else p.delete("plan"); return p; }, { replace: true }); load(e.target.value); }}>
              <option value="">Implantation du jumeau (sans plan)</option>
              {data.workshop_plans.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select></label>
          {results && <>
            <button className="btn small" onClick={() => download(`${base}/simulations/${sim!.id}/des.pdf`, `simulation_${sim!.id.slice(0, 8)}.pdf`)}>PDF</button>
            <button className="btn small" onClick={() => download(`${base}/simulations/${sim!.id}/des.xlsx`, `simulation_${sim!.id.slice(0, 8)}.xlsx`)}>Excel</button>
          </>}
        </div>
      </div>
      {err && <p className="notice err">{err}</p>}

      <div className="sim-grid">
        {/* ------------------------------------------------ réglages du modèle */}
        <aside className="card sim-panel">
          <h3>Modèle</h3>
          <p className="muted small">Généré depuis le calcul{plan ? ` et le plan « ${plan.name} »` : ""} : un poste par station, un chariot d'encours devant chaque poste, les opérateurs de l'équilibrage.</p>
          <details open><summary>Équipe et pauses</summary>
            <label>Durée simulée (min)<input type="number" min={30} max={960} value={model.shift.minutes} onChange={(e) => setModel({ ...model, shift: { ...model.shift, minutes: +e.target.value } })} /></label>
            {model.shift.breaks.map((b, i) => (
              <div key={i} className="row small sim-break">
                <input aria-label="Libellé" value={b.label} onChange={(e) => setModel({ ...model, shift: { ...model.shift, breaks: model.shift.breaks.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)) } })} />
                <input aria-label="Début (min)" type="number" value={b.start_min} onChange={(e) => setModel({ ...model, shift: { ...model.shift, breaks: model.shift.breaks.map((x, j) => (j === i ? { ...x, start_min: +e.target.value } : x)) } })} />
                <input aria-label="Durée (min)" type="number" value={b.minutes} onChange={(e) => setModel({ ...model, shift: { ...model.shift, breaks: model.shift.breaks.map((x, j) => (j === i ? { ...x, minutes: +e.target.value } : x)) } })} />
                <button className="link" onClick={() => setModel({ ...model, shift: { ...model.shift, breaks: model.shift.breaks.filter((_, j) => j !== i) } })} aria-label="Supprimer la pause">✕</button>
              </div>))}
            <button className="link small" onClick={() => setModel({ ...model, shift: { ...model.shift, breaks: [...model.shift.breaks, { start_min: 360, minutes: 10, label: "Pause" }] } })}>+ Pause (début, durée en min)</button>
          </details>
          <details open><summary>Source : ordre de coupe</summary>
            <label>Pièces par paquet<input type="number" min={1} max={200} value={model.source.bundle_size} onChange={(e) => setSrc("bundle_size", +e.target.value)} /></label>
            {model.source.lots.map((l, i) => (
              <div key={i} className="row small sim-break">
                <i className="sim-dot" style={{ background: lotColor(i) }} />
                <input aria-label="Modèle" value={l.style} onChange={(e) => setSrc("lots", model.source.lots.map((x, j) => (j === i ? { ...x, style: e.target.value } : x)))} />
                <input aria-label="Taille" placeholder="taille" value={l.size} onChange={(e) => setSrc("lots", model.source.lots.map((x, j) => (j === i ? { ...x, size: e.target.value } : x)))} />
                <input aria-label="Quantité (0 = illimité)" type="number" value={l.qty} onChange={(e) => setSrc("lots", model.source.lots.map((x, j) => (j === i ? { ...x, qty: +e.target.value } : x)))} />
                {model.source.lots.length > 1 && <button className="link" onClick={() => setSrc("lots", model.source.lots.filter((_, j) => j !== i))} aria-label="Supprimer le lot">✕</button>}
              </div>))}
            <button className="link small" onClick={() => setSrc("lots", [...model.source.lots, { style: model.source.lots[0]?.style ?? "Modèle", size: "L", qty: 200 }])}>+ Lot (modèle, taille, quantité ; 0 = illimité)</button>
            <label>Lancement<select value={model.source.interval_min > 0 ? "int" : "pull"} onChange={(e) => setSrc("interval_min", e.target.value === "int" ? 5 : 0)}>
              <option value="pull">Tiré (dès qu'il y a de la place au 1er poste)</option><option value="int">Un paquet toutes les… min</option></select></label>
            {model.source.interval_min > 0 && <label>Intervalle (min)<input type="number" min={0.1} step={0.5} value={model.source.interval_min} onChange={(e) => setSrc("interval_min", +e.target.value)} /></label>}
            <label>Encours de départ (paquets par poste)<input type="number" min={0} max={20} value={model.source.start_wip_bundles} onChange={(e) => setSrc("start_wip_bundles", +e.target.value)} /></label>
          </details>
          <details><summary>Temps et variabilité</summary>
            <label>Efficience de la ligne (%)<input type="number" min={10} max={250} value={Math.round(numIn(S.efficiency, 1) * 100)} onChange={(e) => setS("efficiency", +e.target.value / 100)} /></label>
            <label>Loi des temps<select value={dist.kind} onChange={(e) => setS("dist", { ...dist, kind: e.target.value })}>
              <option value="constant">Constante</option><option value="normal">Normale tronquée</option><option value="triangular">Triangulaire</option><option value="lognormal">Lognormale</option></select></label>
            {(dist.kind === "normal" || dist.kind === "lognormal") && <label>Coefficient de variation (%)<input type="number" min={0} max={150} value={Math.round(numIn(dist.cv, 0.1) * 100)} onChange={(e) => setS("dist", { ...dist, cv: +e.target.value / 100 })} /></label>}
            {dist.kind === "triangular" && <div className="row small"><label>Min (% du temps)<input type="number" value={dist.low_pct ?? 80} onChange={(e) => setS("dist", { ...dist, low_pct: +e.target.value })} /></label>
              <label>Max (%)<input type="number" value={dist.high_pct ?? 140} onChange={(e) => setS("dist", { ...dist, high_pct: +e.target.value })} /></label></div>}
            <label>Mise en route au changement de lot (min)<input type="number" min={0} step={0.5} value={numIn(S.setup_min, 0)} onChange={(e) => setS("setup_min", +e.target.value)} /></label>
            <label>Prise + dépose d'un paquet (min)<input type="number" min={0} step={0.05} value={numIn(S.handling_min, 0.1)} onChange={(e) => setS("handling_min", +e.target.value)} /></label>
          </details>
          <details><summary>Pannes et qualité</summary>
            <div className="row small"><label>MTBF (min)<input type="number" min={0} value={numIn(S.mtbf_min, 0)} onChange={(e) => setS("mtbf_min", +e.target.value)} /></label>
              <label>MTTR (min)<input type="number" min={0} value={numIn(S.mttr_min, 0)} onChange={(e) => setS("mttr_min", +e.target.value)} /></label></div>
            <p className="muted small">0 = sans panne. Temps moyen entre pannes et de réparation, tirés au hasard (loi exponentielle) pour chaque poste.</p>
            <label>Défauts au contrôle (dernier poste, %)<input type="number" min={0} max={60} step={0.5} value={numIn(S.defect_pct, 0)} onChange={(e) => setS("defect_pct", +e.target.value)} /></label>
            <p className="muted small">Les pièces défectueuses repartent en retouche au poste précédent (réglable par poste ci-dessous).</p>
          </details>
          <details><summary>Déplacements et transport</summary>
            <label>Vitesse de marche (m/s)<input type="number" min={0.2} max={3} step={0.1} value={fmt.n(numIn(S.walk_speed_m_per_min, 60) / 60, 2).replace(",", ".")} onChange={(e) => setS("walk_speed_m_per_min", +e.target.value * 60)} /></label>
            <label>Passage des paquets<select value={S.transfer ?? "auto"} onChange={(e) => setS("transfer", e.target.value)}>
              <option value="auto">Automatique (main à main si proche, sinon porté)</option><option value="handoff">Main à main</option>
              <option value="operator">Porté par l'opérateur</option><option value="transporter">Agent de liaison / chariot</option></select></label>
            <label>Distance au-delà de laquelle on porte (m)<input type="number" min={0} step={0.5} value={numIn(S.carry_threshold_m, 2.5)} onChange={(e) => setS("carry_threshold_m", +e.target.value)} /></label>
            <div className="row small"><label>Agents de liaison<input type="number" min={0} max={12} value={model.transporters.length} onChange={(e) => {
              const n = Math.max(0, Math.min(12, +e.target.value)); const cap = model.transporters[0]?.capacity ?? 4, spd = model.transporters[0]?.speed_m_per_min ?? 60;
              setModel({ ...model, transporters: Array.from({ length: n }, (_, k) => ({ id: `T${k + 1}`, name: `Agent de liaison ${k + 1}`, capacity: cap, speed_m_per_min: spd, load_min: 0.2 })) });
            }} /></label>
              {model.transporters.length > 0 && <label>Capacité (paquets)<input type="number" min={1} max={50} value={model.transporters[0].capacity} onChange={(e) => setModel({ ...model, transporters: model.transporters.map((x) => ({ ...x, capacity: +e.target.value })) })} /></label>}</div>
          </details>
          <details open={openSt} onToggle={(e) => setOpenSt((e.target as HTMLDetailsElement).open)}><summary>Postes ({model.stations.length})</summary>
            {openSt && <div className="table-wrap"><table className="sim-st-table">
              <thead><tr><th>Poste</th><th>min/pc</th><th>Serv.</th><th>File max</th><th>Défauts %</th><th>MTBF</th><th>MTTR</th></tr></thead>
              <tbody>{model.stations.map((s) => (
                <tr key={s.id} title={`${s.operations.join(", ")} · ${s.operators.map(opName).join(", ")}`}>
                  <td>{s.id}</td>
                  <td><input type="number" step={0.01} value={s.minutes} onChange={(e) => setStation(s.id, "minutes", +e.target.value)} /></td>
                  <td><input type="number" min={1} max={20} value={s.servers} onChange={(e) => setStation(s.id, "servers", +e.target.value)} /></td>
                  <td><input type="number" min={1} value={s.queue_capacity ?? ""} placeholder={String(S.queue_capacity ?? 6)} onChange={(e) => setStation(s.id, "queue_capacity", e.target.value === "" ? undefined : +e.target.value)} /></td>
                  <td><input type="number" min={0} max={60} value={s.defect_pct ?? ""} onChange={(e) => setStation(s.id, "defect_pct", e.target.value === "" ? undefined : +e.target.value)} /></td>
                  <td><input type="number" min={0} value={s.mtbf_min ?? ""} onChange={(e) => setStation(s.id, "mtbf_min", e.target.value === "" ? undefined : +e.target.value)} /></td>
                  <td><input type="number" min={0} value={s.mttr_min ?? ""} onChange={(e) => setStation(s.id, "mttr_min", e.target.value === "" ? undefined : +e.target.value)} /></td>
                </tr>))}</tbody></table></div>}
          </details>
          <h3>Scénarios</h3>
          {forms.map((f, i) => (
            <details key={i} open={i > 0} className="sim-scen" style={{ borderLeftColor: SCEN_COLORS[i] }}>
              <summary><input aria-label="Nom du scénario" value={f.name} onChange={(e) => setForms(forms.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} />
                {i > 0 && <button className="link" onClick={() => setForms(forms.filter((_, j) => j !== i))} aria-label="Supprimer le scénario">✕</button>}</summary>
              {i === 0 ? <p className="muted small">Le modèle tel que réglé ci-dessus.</p> : <>
                <p className="muted small">Vide = comme la référence.</p>
                <div className="row small">
                  <label>Paquet (pcs)<input value={f.bundle_size} onChange={(e) => setForms(forms.map((x, j) => (j === i ? { ...x, bundle_size: e.target.value } : x)))} /></label>
                  <label>Efficience %<input value={f.efficiency} onChange={(e) => setForms(forms.map((x, j) => (j === i ? { ...x, efficiency: e.target.value } : x)))} /></label>
                  <label>Variabilité %<input value={f.cv} onChange={(e) => setForms(forms.map((x, j) => (j === i ? { ...x, cv: e.target.value } : x)))} /></label>
                  <label>Agents de liaison<input value={f.transporters} onChange={(e) => setForms(forms.map((x, j) => (j === i ? { ...x, transporters: e.target.value, transfer: e.target.value && +e.target.value > 0 ? "transporter" : x.transfer } : x)))} /></label>
                  <label>MTBF<input value={f.mtbf} onChange={(e) => setForms(forms.map((x, j) => (j === i ? { ...x, mtbf: e.target.value } : x)))} /></label>
                  <label>MTTR<input value={f.mttr} onChange={(e) => setForms(forms.map((x, j) => (j === i ? { ...x, mttr: e.target.value } : x)))} /></label>
                  <label>Défauts %<input value={f.defect} onChange={(e) => setForms(forms.map((x, j) => (j === i ? { ...x, defect: e.target.value } : x)))} /></label>
                  <label>Mise en route<input value={f.setup} onChange={(e) => setForms(forms.map((x, j) => (j === i ? { ...x, setup: e.target.value } : x)))} /></label>
                </div>
                <label>Absentes<select multiple value={f.absent} onChange={(e) => setForms(forms.map((x, j) => (j === i ? { ...x, absent: Array.from(e.target.selectedOptions).map((o) => o.value) } : x)))}>
                  {model.operators.map((o) => <option key={o.id} value={o.id}>{o.name} (postes {o.stations.join(", ")})</option>)}</select></label>
              </>}
            </details>
          ))}
          {forms.length < 3 && <button className="btn small" onClick={() => setForms([...forms, emptyForm(forms.length === 1 ? "Paquets de 5" : "Avec agent de liaison")].map((f, i, arr) => (i === arr.length - 1 ? (forms.length === 1 ? { ...f, bundle_size: "5" } : { ...f, transporters: "1", transfer: "transporter" }) : f)))}>+ Scénario à comparer</button>}
          <label>Réplications (graines)<input type="number" min={1} max={20} value={reps} onChange={(e) => setReps(Math.max(1, Math.min(20, +e.target.value)))} /></label>
          {writable ? <button className="btn primary full" disabled={busy} onClick={run}>{busy ? (sim?.status === "running" ? "Simulation en cours…" : "En file d'attente…") : "▶ Lancer la simulation"}</button>
            : <p className="muted small">Votre rôle (lecteur) permet de consulter les simulations.</p>}
          {data.simulations.length > 0 && <>
            <h3>Historique</h3>
            <ul className="sim-hist">{data.simulations.map((s) => (
              <li key={s.id}><button className={`link ${sim?.id === s.id ? "on" : ""}`} onClick={() => openSim(s.id)}>{s.name || "Simulation"}</button>
                <small className="muted"> {fmt.date(s.created_at)} · {s.status === "done" ? "terminée" : s.status === "failed" ? "échec" : "en cours"}</small></li>))}</ul>
          </>}
        </aside>

        {/* ------------------------------------------------ lecture */}
        <section className="card sim-view">
          {sim && sim.status === "failed" && <p className="notice err">Échec de la simulation : {sim.error}</p>}
          {sim && (sim.status === "queued" || sim.status === "running") && <p className="notice warn">Simulation en cours ({forms.length} scénario(s) × {reps} réplication(s))… le serveur gratuit peut mettre une minute à se réveiller.</p>}
          {results && <div className="row sim-scen-tabs">
            {results.scenarios.map((s, i) => <button key={i} className={`chipbtn ${i === scIdx ? "on" : ""}`} style={{ borderColor: SCEN_COLORS[i] }} onClick={() => { setScIdx(i); }}>{s.name}</button>)}
            <span className="muted small">{results.replications} réplication(s) · ± = intervalle de confiance 95 %</span>
          </div>}
          {kpi && rk && <div className="kpis">
            <div className="kpi"><span>Pièces produites</span><b>{ciTxt(rk.pieces, 0)}</b><small>{fmt.n(kpi.per_hour, 1)} pcs/h{kpi.target_per_hour ? ` · objectif ${fmt.n(kpi.target_per_hour, 0)}/h` : ""}</small></div>
            <div className="kpi"><span>Temps de traversée</span><b>{ciTxt(rk.lead_time_avg, 0)} min</b><small>p90 {fmt.n(kpi.lead_time_p90, 0)} min</small></div>
            <div className="kpi"><span>Encours moyen</span><b>{ciTxt(rk.wip_avg, 0)}</b><small>max {fmt.n(kpi.wip_max, 0)} pièces</small></div>
            <div className="kpi warn"><span>Goulot</span><b>Poste {rk.bottleneck.mean}</b><small>le plus occupé (travail + panne + attente opérateur)</small></div>
            <div className="kpi"><span>Opérateurs</span><b>{ciTxt(rk.operator_util_avg, 0)} %</b><small>{fmt.n(kpi.walk_m, 0)} m à pied au total</small></div>
          </div>}
          <div className="row sim-toolbar">
            <div className="seg" aria-label="Vue">
              {(["2d", "3d", "both"] as View[]).map((v) => <button key={v} className={view === v ? "on" : ""} onClick={() => setView(v)}>{v === "both" ? "2D + 3D" : v.toUpperCase()}</button>)}
            </div>
            <Legend keys={STATION_STATES.slice(0, 6)} labels={STATE_LABEL} colors={STATE_COLOR} />
          </div>
          <div className={`sim-stage ${view}`}>
            {view !== "3d" && <SimCanvas2D model={vModel!} plan={plan} frame={frame} selected={picked} onSelect={setPicked} />}
            {view !== "2d" && <Suspense fallback={<div className="sim3d p3d-loading">Chargement de la vue 3D…</div>}>
              <SimScene3D model={vModel!} plan={plan} frame={frame} />
            </Suspense>}
          </div>
          {cursor ? <div className="sim-timeline">
            <button className="btn small" onClick={() => { setT(0); }} title="Début">⏮</button>
            <button className="btn small" onClick={() => setT((x) => Math.max(0, x - 10))} title="-10 min">−10</button>
            <button className="btn small primary" onClick={() => { if (t >= until) setT(0); setPlaying(!playing); }}>{playing ? "⏸ Pause" : "▶ Lecture"}</button>
            <button className="btn small" onClick={() => setT((x) => Math.min(until, x + 10))} title="+10 min">+10</button>
            <select aria-label="Vitesse" value={speed} onChange={(e) => setSpeed(+e.target.value)}>{SPEEDS.map((s) => <option key={s} value={s}>x{s}</option>)}</select>
            <input className="sim-range" type="range" min={0} max={until} step={0.1} value={Math.min(t, until)} onChange={(e) => setT(+e.target.value)} aria-label="Temps simulé" />
            <b className="sim-clock">{fmtClock(t)}</b>
            <span className="small muted">{frame ? `${frame.done} pcs terminées · encours ${frame.wip}` : ""}</span>
            {res?.trace?.truncated && <span className="badge warn">animation jusqu'à {fmtClock(until)}</span>}
          </div> : <p className="muted small">{sim ? "" : "Réglez le modèle puis lancez la simulation : les paquets, les opérateurs et les agents de liaison s'animeront ici, en 2D et en 3D."}</p>}
          {res?.notes?.length ? <ul className="small sim-notes">{res.notes.map((n, i) => <li key={i}>{n}</li>)}</ul> : null}
        </section>
      </div>

      {/* ------------------------------------------------ tableaux de bord */}
      {res && results && <section className="card">
        <div className="tabs">
          {([["states", "États des postes"], ["wip", "Encours"], ["throughput", "Débit"], ["lead", "Temps de traversée"], ["operators", "Opérateurs"], ["compare", "Comparaison"]] as [Tab, string][]).map(([k, l]) =>
            <button key={k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{l}</button>)}
        </div>
        {tab === "states" && <div className="sim-dash2">
          <div><StateBars stations={res.stations} bottleneck={kpi?.bottleneck} picked={picked} onPick={setPicked} /><Legend keys={STATION_STATES} labels={STATE_LABEL} colors={STATE_COLOR} /></div>
          <div>{pickedSt ? <>
            <h4>Poste {pickedSt.id} <small className="muted">{pickedSt.operators.map(opName).join(", ") || "sans opérateur"}</small></h4>
            <StatePie states={pickedSt.states} />
            <table className="small"><tbody>
              <tr><td>Pièces</td><td>{pickedSt.pieces}{pickedSt.defects ? ` (${pickedSt.defects} en retouche)` : ""}</td></tr>
              <tr><td>Temps</td><td>{fmt.n(pickedSt.minutes, 3)} min/pc · {pickedSt.servers} serveur(s)</td></tr>
              <tr><td>File</td><td>moy. {fmt.n(pickedSt.queue_avg, 1)} paquets · max {pickedSt.queue_max}</td></tr>
              <tr><td>Occupation</td><td>{ciTxt(res.replications.station_util[pickedSt.id])} %</td></tr>
              {STATION_STATES.filter((k) => pickedSt.states[k] > 0).map((k) => <tr key={k}><td><i className="sim-dot" style={{ background: STATE_COLOR[k] }} /> {STATE_LABEL[k]}</td><td>{fmt.n(pickedSt.states[k], 1)} %</td></tr>)}
            </tbody></table></> : <p className="muted small">Touchez un poste (plan ou barres) pour voir son camembert d'états.</p>}</div>
        </div>}
        {tab === "wip" && <LineChart xMax={T} yLabel="pièces en cours" breaks={res.breaks}
          series={results.scenarios.map((s, i) => ({ name: s.name, color: SCEN_COLORS[i], points: s.result.wip_series }))} />}
        {tab === "throughput" && <>
          <LineChart xMax={T} yLabel="pièces terminées (cumul)" breaks={res.breaks} series={[
            ...results.scenarios.map((s, i) => ({ name: s.name, color: SCEN_COLORS[i], points: s.result.throughput.cumulative })),
            ...(kpi?.target_per_hour ? [{ name: "Objectif", color: "#2e9e5b", dash: true, points: [[0, 0], [T, (kpi.target_per_hour * T) / 60]] as [number, number][] }] : []),
          ]} />
          <div className="chart-legend">{results.scenarios.map((s, i) => <span key={i}><i style={{ background: SCEN_COLORS[i] }} />{s.name}</span>)}{kpi?.target_per_hour ? <span><i style={{ background: "#2e9e5b" }} />Objectif ({fmt.n(kpi.target_per_hour, 0)}/h)</span> : null}</div>
          <h4>Pièces par heure · {sc?.name}</h4>
          <Bars values={res.throughput.hourly} target={kpi?.target_per_hour} label="Débit horaire" />
        </>}
        {tab === "lead" && <>
          <p className="small muted">Temps de traversée des paquets lancés pendant la journée ({res.lead_time.count} paquets) · moyenne {fmt.n(kpi?.lead_time_avg, 0)} min · p90 {fmt.n(kpi?.lead_time_p90, 0)} min.</p>
          <Histogram edges={res.lead_time.hist.edges} counts={res.lead_time.hist.counts} color={SCEN_COLORS[scIdx]} />
        </>}
        {tab === "operators" && <>
          <Gantt operators={res.operators} T={T} now={t} />
          <div className="table-wrap"><table className="small">
            <thead><tr><th>Opérateur</th><th>Postes</th><th>Occupation</th><th>Marche</th><th>Porte des paquets</th><th>Distance</th></tr></thead>
            <tbody>{res.operators.map((o) => <tr key={o.id}><td>{o.name}</td><td>{o.stations.join(", ")}</td><td>{fmt.n(o.utilization_pct, 1)} %</td>
              <td>{fmt.n(o.states.walk, 1)} %</td><td>{fmt.n(o.states.carry, 1)} %</td><td>{fmt.n(o.walk_m, 0)} m</td></tr>)}
              {res.transporters.map((x) => <tr key={x.id}><td>{x.name}</td><td>{x.loads} enlèvements (cap. {x.capacity})</td><td>{fmt.n(x.utilization_pct, 1)} %</td>
                <td>{fmt.n(x.states.empty, 1)} % {TR_LABEL.empty.toLowerCase()}</td><td>{fmt.n(x.states.loaded, 1)} % {TR_LABEL.loaded.toLowerCase()}</td><td>{fmt.n(x.distance_m, 0)} m</td></tr>)}
            </tbody></table></div>
        </>}
        {tab === "compare" && <div className="table-wrap"><table>
          <thead><tr><th>Indicateur</th>{results.scenarios.map((s, i) => <th key={i} style={{ color: SCEN_COLORS[i] }}>{s.name}</th>)}</tr></thead>
          <tbody>{results.comparison.map((r) => {
            const ref = r.values[0]?.mean;
            return <tr key={r.key}><td>{r.label}</td>{r.values.map((v, i) => {
              const d = i > 0 && typeof v.mean === "number" && typeof ref === "number" && ref ? ((v.mean - ref) / ref) * 100 : null;
              return <td key={i}>{ciTxt(v, r.key === "pieces" ? 0 : 1)}{d != null && Math.abs(d) >= 0.5 ? <small className={d > 0 === (r.key === "pieces" || r.key === "per_hour") ? "ok-t" : "err-t"}> ({d > 0 ? "+" : ""}{fmt.n(d, 0)} %)</small> : null}</td>;
            })}</tr>;
          })}</tbody></table>
          <p className="muted small">{results.replications} réplication(s) par scénario (graines différentes) ; « ± » = demi-largeur de l'intervalle de confiance à 95 % (loi de Student).</p>
        </div>}
      </section>}
    </div>
  );
}
