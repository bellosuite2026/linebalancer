// Optimiseur de la simulation (phase 2.3, type OptQuest) : recherche multi-objectif (NSGA-II léger côté
// API) sur le modèle à événements discrets — effectifs, taille de paquet, encours max, agents de liaison,
// cintres, placement des postes. Front de Pareto, détail des solutions, « Appliquer » = scénario simulé.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, fmt, post } from "../lib/api";
import { canWrite, useSession } from "../lib/session";
import type { CI, DesModelResponse } from "../lib/des";

type ObjKey = "pieces" | "cost_minute" | "wip_avg" | "walk_m";
const OBJ: Record<ObjKey, { label: string; unit: string; sense: "max" | "min"; d: number }> = {
  pieces: { label: "Pièces / jour", unit: "pcs", sense: "max", d: 0 },
  cost_minute: { label: "Coût minute", unit: "TND/min", sense: "min", d: 4 },
  wip_avg: { label: "Encours moyen", unit: "pcs", sense: "min", d: 0 },
  walk_m: { label: "Marche + transport", unit: "m", sense: "min", d: 0 },
};
interface Mean { pieces: number; per_hour: number; cost_minute: number; cost_piece: number | null; wip_avg: number; walk_m: number;
  lead_time_avg: number; operator_util_avg: number; people: number; operators: number; transporters: number; bottleneck: string }
interface Solution { id?: number; key: string; genes: Record<string, unknown>; mean: Mean; kpis: Record<string, CI>; feasible: boolean;
  changes: string[]; vs_base?: Record<string, number | null> }
interface OptResults { engine?: string; progress?: { pct?: number; evals?: number; elapsed_s?: number; gen?: number; best_pieces?: number };
  pareto?: Solution[]; base?: Solution; cloud?: { mean: Partial<Mean>; feasible: boolean }[]; evals?: number; simulations?: number;
  elapsed_s?: number; stopped_by?: string; feasible_found?: boolean; variants?: string[];
  config?: { objectives: ObjKey[]; replications: number; cost_per_minute: number } }
interface OptSim { id: string; status: string; name: string; error?: string | null; created_at?: string; results?: OptResults | null }

const num = (v: string) => (v.trim() === "" ? null : Number(v.replace(",", ".")));

export default function Optimizer() {
  const { runId } = useParams();
  const [sp, setSp] = useSearchParams();
  const nav = useNavigate();
  const { currentOrg } = useSession();
  const org = currentOrg!;
  const base = `/v1/orgs/${org.id}`;
  const writable = canWrite(org);
  const [data, setData] = useState<DesModelResponse | null>(null);
  const [planId, setPlanId] = useState(sp.get("plan") ?? "");
  const [hist, setHist] = useState<OptSim[]>([]);
  const [sim, setSim] = useState<OptSim | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [objs, setObjs] = useState<ObjKey[]>(["pieces", "cost_minute", "wip_avg", "walk_m"]);
  const [cost, setCost] = useState("0.06");
  const [cons, setCons] = useState({ min_per_hour: "", max_wip_avg: "", max_people: "", max_cost_minute: "" });
  const [vary, setVary] = useState({ staffing: true, bundle_size: true, wip_cap: true, transporters: true, conveyor: true, layout: true });
  const [maxExtra, setMaxExtra] = useState(2), [maxFewer, setMaxFewer] = useState(2), [maxTr, setMaxTr] = useState(3);
  const [budget, setBudget] = useState(45), [reps, setReps] = useState(3);
  const [ax, setAx] = useState<ObjKey>("cost_minute"), [ay, setAy] = useState<ObjKey>("pieces");
  const [sel, setSel] = useState<number | null>(null);
  const [applying, setApplying] = useState<number | null>(null);

  const load = useCallback(async (pid: string) => {
    setErr("");
    try {
      const d = await api<DesModelResponse>(`${base}/runs/${runId}/des/model${pid ? `?plan_id=${pid}` : ""}`);
      setData(d);
      if (!pid && d.model.plan_id) setPlanId(d.model.plan_id);
      const h = await api<OptSim[]>(`${base}/runs/${runId}/optimizations`);
      setHist(h);
      const last = sp.get("opt") ?? h.find((s) => s.status === "done")?.id;
      if (last) openSim(last);
    } catch (e) { setErr((e as Error).message); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [base, runId]);
  useEffect(() => { load(planId); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [load]);

  const pollRef = useRef<number>();
  useEffect(() => () => window.clearTimeout(pollRef.current), []);
  const openSim = async (id: string) => {
    try {
      const s = await api<OptSim>(`${base}/simulations/${id}`);
      setSim(s); setSel(null);
      if (s.status === "queued" || s.status === "running") poll(id);
    } catch (e) { setErr((e as Error).message); }
  };
  const poll = (id: string) => {
    window.clearTimeout(pollRef.current);
    pollRef.current = window.setTimeout(async () => {
      try {
        const s = await api<OptSim>(`${base}/simulations/${id}`);
        setSim(s);
        if (s.status === "queued" || s.status === "running") poll(id);
        else {
          setBusy(false);
          setSp((p) => { p.set("opt", id); return p; }, { replace: true });
          api<OptSim[]>(`${base}/runs/${runId}/optimizations`).then(setHist).catch(() => undefined);
        }
      } catch (e) { setErr((e as Error).message); setBusy(false); }
    }, 2000);
  };

  const start = async () => {
    if (objs.length < 2) { setErr("Choisissez au moins deux objectifs."); return; }
    setBusy(true); setErr("");
    const constraints = Object.fromEntries(Object.entries(cons).map(([k, v]) => [k, num(v)]));
    try {
      const s = await post<OptSim>(`${base}/runs/${runId}/optimize`, {
        name: `Optimisation ${new Date().toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })}`,
        plan_id: planId || null,
        config: { objectives: objs, cost_per_minute: num(cost) ?? 0.06, constraints, vary, max_extra_operators: maxExtra,
          max_fewer_operators: maxFewer, max_transporters: maxTr, time_budget_s: budget, replications: reps },
      });
      setSim(s); poll(s.id);
    } catch (e) { setErr((e as Error).message); setBusy(false); }
  };

  const apply = async (sol: Solution) => {
    if (!sim || !sol.id) return;
    setApplying(sol.id); setErr("");
    try {
      const r = await post<{ simulation: { id: string }; layout_saved: boolean; plan_id: string | null }>(
        `${base}/optimizations/${sim.id}/apply`, { solution: sol.id, save_layout: true, replications: 5 });
      nav(`/simulation/${runId}?sim=${r.simulation.id}${r.plan_id ? `&plan=${r.plan_id}` : ""}`);
    } catch (e) { setErr((e as Error).message); setApplying(null); }
  };

  const res = sim?.status === "done" ? sim.results ?? null : null;
  const running = sim && (sim.status === "queued" || sim.status === "running");
  const pr = sim?.results?.progress;
  const pareto = res?.pareto ?? [];
  const picked = pareto.find((s) => s.id === sel) ?? null;

  if (err && !data) return <div className="page"><p className="error">{err}</p></div>;
  if (!data) return <div className="page muted">Préparation du modèle…</div>;

  return (
    <div className="page opt-page">
      <div className="page-head">
        <div>
          <h1>Optimiseur</h1>
          <p className="muted">{data.problem_name || data.model.name} · {data.summary.stations} postes · {data.summary.operators} opérateurs ·
            {" "}<Link to={`/simulation/${runId}${planId ? `?plan=${planId}` : ""}`}>simulation 3D</Link> · <Link to={`/calculs/${runId}`}>calcul</Link></p>
        </div>
        <div className="actions">
          <label className="small">Plan d'atelier{" "}
            <select value={planId} onChange={(e) => { setPlanId(e.target.value); setSp((p) => { if (e.target.value) p.set("plan", e.target.value); else p.delete("plan"); return p; }, { replace: true }); load(e.target.value); }}>
              <option value="">Implantation du jumeau (sans plan)</option>
              {data.workshop_plans.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select></label>
        </div>
      </div>
      {err && <p className="error">{err}</p>}
      <div className="opt-grid">
        <aside className="card opt-form">
          <h3>Objectifs</h3>
          {(Object.keys(OBJ) as ObjKey[]).map((k) => (
            <label key={k} className="check"><input type="checkbox" checked={objs.includes(k)} onChange={(e) => setObjs(e.target.checked ? [...objs, k] : objs.filter((x) => x !== k))} />
              {OBJ[k].sense === "max" ? "Maximiser" : "Minimiser"} : {OBJ[k].label.toLowerCase()}</label>))}
          <label>Coût d'une minute payée par personne (TND)<input type="number" min={0} step={0.005} value={cost} onChange={(e) => setCost(e.target.value)} /></label>
          <p className="muted small">Coût minute = salaires de la journée (opératrices + agents de liaison) ÷ minutes produites (pièces × SAM).</p>
          <h3>Contraintes</h3>
          <div className="row small">
            <label>Débit mini (pcs/h)<input type="number" min={0} value={cons.min_per_hour} onChange={(e) => setCons({ ...cons, min_per_hour: e.target.value })} placeholder="—" /></label>
            <label>Encours moyen max (pcs)<input type="number" min={0} value={cons.max_wip_avg} onChange={(e) => setCons({ ...cons, max_wip_avg: e.target.value })} placeholder="—" /></label>
            <label>Effectif max (personnes)<input type="number" min={1} value={cons.max_people} onChange={(e) => setCons({ ...cons, max_people: e.target.value })} placeholder="—" /></label>
            <label>Coût minute max (TND)<input type="number" min={0} step={0.001} value={cons.max_cost_minute} onChange={(e) => setCons({ ...cons, max_cost_minute: e.target.value })} placeholder="—" /></label>
          </div>
          <h3>Variables</h3>
          <label className="check"><input type="checkbox" checked={vary.staffing} onChange={(e) => setVary({ ...vary, staffing: e.target.checked })} /> Effectifs et affectations</label>
          {vary.staffing && <div className="row small">
            <label>Renforts max<input type="number" min={0} max={6} value={maxExtra} onChange={(e) => setMaxExtra(+e.target.value)} /></label>
            <label>Retraits max<input type="number" min={0} max={6} value={maxFewer} onChange={(e) => setMaxFewer(+e.target.value)} /></label></div>}
          <label className="check"><input type="checkbox" checked={vary.bundle_size} onChange={(e) => setVary({ ...vary, bundle_size: e.target.checked })} /> Taille de paquet (5 à 30)</label>
          <label className="check"><input type="checkbox" checked={vary.wip_cap} onChange={(e) => setVary({ ...vary, wip_cap: e.target.checked })} /> Encours max (plafond de lancement)</label>
          <label className="check"><input type="checkbox" checked={vary.transporters} onChange={(e) => setVary({ ...vary, transporters: e.target.checked })} /> Agents de liaison</label>
          {vary.transporters && <label className="small">Agents de liaison max<input type="number" min={0} max={6} value={maxTr} onChange={(e) => setMaxTr(+e.target.value)} /></label>}
          <label className="check"><input type="checkbox" checked={vary.conveyor} onChange={(e) => setVary({ ...vary, conveyor: e.target.checked })} /> Convoyeur : nombre de cintres et encours par poste</label>
          <label className="check"><input type="checkbox" checked={vary.layout} onChange={(e) => setVary({ ...vary, layout: e.target.checked })} /> Placement des postes (ligne, U, échanges sur machines du même type)</label>
          <h3>Recherche</h3>
          <div className="row small">
            <label>Durée max (s)<input type="number" min={10} max={90} value={budget} onChange={(e) => setBudget(Math.max(10, Math.min(90, +e.target.value)))} /></label>
            <label>Réplications / essai<input type="number" min={1} max={5} value={reps} onChange={(e) => setReps(Math.max(1, Math.min(5, +e.target.value)))} /></label>
          </div>
          <p className="muted small">Algorithme génétique multi-objectif (NSGA-II) : chaque essai est simulé (journée complète, pauses, variabilité) avec les mêmes graines pour comparer à armes égales.</p>
          {writable ? <button className="btn primary" disabled={busy || !!running} onClick={start}>{running ? "Recherche en cours…" : "Lancer l'optimisation"}</button>
            : <p className="muted small">Lecture seule : votre rôle ne permet pas de lancer une optimisation.</p>}
          {hist.length > 0 && <>
            <h3>Historique</h3>
            <ul className="opt-hist">{hist.map((h) => (
              <li key={h.id}><button className={`link${sim?.id === h.id ? " strong" : ""}`} onClick={() => openSim(h.id)}>{h.name}</button> <span className="muted small">{h.status === "done" ? "" : h.status}</span></li>))}</ul>
          </>}
        </aside>

        <section className="opt-main">
          {running && <div className="card">
            <h3>Recherche en cours…</h3>
            <div className="opt-bar"><i style={{ width: `${pr?.pct ?? 2}%` }} /></div>
            <p className="muted small">{pr?.evals ?? 0} configurations simulées · génération {pr?.gen ?? 0} · {fmt.n(pr?.elapsed_s ?? 0, 0)} s
              {pr?.best_pieces ? ` · meilleur débit ${fmt.n(pr.best_pieces, 0)} pcs/j` : ""}. Le serveur gratuit peut mettre une minute à se réveiller.</p>
          </div>}
          {sim?.status === "failed" && <p className="error">Optimisation en échec : {sim.error}</p>}
          {!sim && <div className="card muted">Réglez les objectifs puis lancez l'optimisation : le front de Pareto (meilleurs compromis) s'affichera ici.</div>}
          {res && res.base && <>
            <div className="card">
              <div className="row opt-head">
                <h3>Front de Pareto · {pareto.length} compromis</h3>
                <span className="muted small">{res.evals} configurations · {res.simulations} journées simulées · {fmt.n(res.elapsed_s, 0)} s · arrêt : {res.stopped_by}</span>
              </div>
              {!res.feasible_found && <p className="error small">Aucune configuration ne respecte toutes les contraintes : solutions les moins hors limites affichées.</p>}
              <div className="row small">
                <label>Axe horizontal<select value={ax} onChange={(e) => setAx(e.target.value as ObjKey)}>{(Object.keys(OBJ) as ObjKey[]).map((k) => <option key={k} value={k}>{OBJ[k].label}</option>)}</select></label>
                <label>Axe vertical<select value={ay} onChange={(e) => setAy(e.target.value as ObjKey)}>{(Object.keys(OBJ) as ObjKey[]).map((k) => <option key={k} value={k}>{OBJ[k].label}</option>)}</select></label>
              </div>
              <Scatter res={res} ax={ax} ay={ay} sel={sel} onPick={setSel} />
              <p className="muted small"><i className="opt-dot grey" /> configurations essayées · <i className="opt-dot blue" /> compromis du front · <i className="opt-dot star" /> configuration actuelle. Cliquez un point pour le détail.</p>
            </div>
            {picked && <SolutionCard s={picked} base={res.base} onApply={writable ? () => apply(picked) : undefined} applying={applying === picked.id} />}
            <div className="card table-wrap">
              <table className="opt-table">
                <thead><tr><th>#</th><th>Pièces/j</th><th>pcs/h</th><th>Coût minute</th><th>Coût/pièce</th><th>Encours</th><th>Marche (m)</th><th>Effectif</th><th>Changements</th><th /></tr></thead>
                <tbody>
                  <tr className="opt-base"><td>Actuel</td><td>{fmt.n(res.base.mean.pieces, 0)}</td><td>{fmt.n(res.base.mean.per_hour, 1)}</td><td>{fmt.n(res.base.mean.cost_minute, 4)}</td>
                    <td>{fmt.n(res.base.mean.cost_piece, 3)}</td><td>{fmt.n(res.base.mean.wip_avg, 0)}</td><td>{fmt.n(res.base.mean.walk_m, 0)}</td><td>{res.base.mean.people}</td><td className="muted">Configuration actuelle</td><td /></tr>
                  {pareto.map((s) => (
                    <tr key={s.key} className={sel === s.id ? "sel" : ""} onClick={() => setSel(s.id ?? null)}>
                      <td>{s.id}</td>
                      <td>{fmt.n(s.mean.pieces, 0)} <Delta v={s.vs_base?.pieces} d={0} good="up" /></td>
                      <td>{fmt.n(s.mean.per_hour, 1)}</td>
                      <td>{fmt.n(s.mean.cost_minute, 4)} <Delta v={s.vs_base?.cost_minute} d={4} good="down" /></td>
                      <td>{fmt.n(s.mean.cost_piece, 3)}</td>
                      <td>{fmt.n(s.mean.wip_avg, 0)} <Delta v={s.vs_base?.wip_avg} d={0} good="down" /></td>
                      <td>{fmt.n(s.mean.walk_m, 0)}</td>
                      <td>{s.mean.people}</td>
                      <td className="small">{s.changes.join(" · ")}</td>
                      <td>{writable && <button className="btn small" disabled={applying != null} onClick={(e) => { e.stopPropagation(); apply(s); }}>{applying === s.id ? "…" : "Appliquer"}</button>}</td>
                    </tr>))}
                </tbody>
              </table>
            </div>
            <p className="muted small">« Appliquer » crée une simulation 3D de la solution (5 réplications) et, si le placement change, enregistre la nouvelle implantation du calcul. Moyennes sur {res.config?.replications ?? 1} réplication(s) ; coût d'une minute payée : {fmt.n(res.config?.cost_per_minute, 3)} TND.</p>
          </>}
        </section>
      </div>
    </div>
  );
}

function Delta({ v, d, good }: { v: number | null | undefined; d: number; good: "up" | "down" }) {
  if (v == null || Math.abs(v) < Math.pow(10, -d) / 2) return null;
  const better = good === "up" ? v > 0 : v < 0;
  return <span className={`opt-delta ${better ? "good" : "bad"}`}>{v > 0 ? "+" : "−"}{fmt.n(Math.abs(v), d)}</span>;
}

function SolutionCard({ s, base, onApply, applying }: { s: Solution; base: Solution; onApply?: () => void; applying: boolean }) {
  const rows: [string, number | null, number | null, number][] = [
    ["Pièces / jour", s.mean.pieces, base.mean.pieces, 0], ["Pièces / heure", s.mean.per_hour, base.mean.per_hour, 1],
    ["Coût minute (TND)", s.mean.cost_minute, base.mean.cost_minute, 4], ["Coût par pièce (TND)", s.mean.cost_piece, base.mean.cost_piece, 3],
    ["Encours moyen (pcs)", s.mean.wip_avg, base.mean.wip_avg, 0], ["Traversée moyenne (min)", s.mean.lead_time_avg, base.mean.lead_time_avg, 0],
    ["Marche + transport (m)", s.mean.walk_m, base.mean.walk_m, 0], ["Occupation opérateurs (%)", s.mean.operator_util_avg, base.mean.operator_util_avg, 1],
    ["Effectif (personnes)", s.mean.people, base.mean.people, 0],
  ];
  return (
    <div className="card opt-sol">
      <div className="row opt-head"><h3>Solution {s.id}</h3>{onApply && <button className="btn primary" disabled={applying} onClick={onApply}>{applying ? "Création…" : "Appliquer"}</button>}</div>
      <ul>{s.changes.map((c) => <li key={c}>{c}</li>)}</ul>
      <table className="opt-table small"><thead><tr><th>Indicateur</th><th>Actuel</th><th>Solution</th></tr></thead>
        <tbody>{rows.map(([l, v, b, d]) => <tr key={l}><td>{l}</td><td>{fmt.n(b, d)}</td><td><b>{fmt.n(v, d)}</b></td></tr>)}</tbody></table>
      <p className="muted small">Goulot : poste {s.mean.bottleneck} (actuel : poste {base.mean.bottleneck}).</p>
    </div>
  );
}

function Scatter({ res, ax, ay, sel, onPick }: { res: OptResults; ax: ObjKey; ay: ObjKey; sel: number | null; onPick: (id: number) => void }) {
  const W = 640, H = 340, P = { l: 64, r: 16, t: 14, b: 40 };
  const pts = useMemo(() => {
    const all = [...(res.cloud ?? []).map((c) => c.mean), ...(res.pareto ?? []).map((s) => s.mean), res.base!.mean];
    const xs = all.map((m) => Number(m[ax] ?? 0)), ys = all.map((m) => Number(m[ay] ?? 0));
    const pad = (lo: number, hi: number) => (hi - lo < 1e-9 ? [lo - 1, hi + 1] : [lo - (hi - lo) * 0.06, hi + (hi - lo) * 0.06]);
    const [x0, x1] = pad(Math.min(...xs), Math.max(...xs)), [y0, y1] = pad(Math.min(...ys), Math.max(...ys));
    const sx = (v: number) => P.l + ((v - x0) / (x1 - x0)) * (W - P.l - P.r);
    const sy = (v: number) => H - P.b - ((v - y0) / (y1 - y0)) * (H - P.t - P.b);
    return { x0, x1, y0, y1, sx, sy };
  }, [res, ax, ay]);
  const ticks = (a: number, b: number) => Array.from({ length: 5 }, (_, i) => a + ((b - a) * i) / 4);
  const front = [...(res.pareto ?? [])].sort((a, b) => Number(a.mean[ax]) - Number(b.mean[ax]));
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="opt-scatter" role="img" aria-label="Front de Pareto">
      {ticks(pts.y0, pts.y1).map((v) => <g key={`y${v}`}><line x1={P.l} x2={W - P.r} y1={pts.sy(v)} y2={pts.sy(v)} stroke="#e5e8ec" />
        <text x={P.l - 6} y={pts.sy(v) + 4} textAnchor="end" fontSize="11" fill="#667">{fmt.n(v, OBJ[ay].d)}</text></g>)}
      {ticks(pts.x0, pts.x1).map((v) => <text key={`x${v}`} x={pts.sx(v)} y={H - P.b + 16} textAnchor="middle" fontSize="11" fill="#667">{fmt.n(v, OBJ[ax].d)}</text>)}
      <text x={(W + P.l) / 2} y={H - 6} textAnchor="middle" fontSize="12" fill="#334">{OBJ[ax].label} ({OBJ[ax].unit}) {OBJ[ax].sense === "max" ? "→ mieux" : "← mieux"}</text>
      <text x={14} y={(H - P.b) / 2} textAnchor="middle" fontSize="12" fill="#334" transform={`rotate(-90 14 ${(H - P.b) / 2})`}>{OBJ[ay].label} ({OBJ[ay].unit}) {OBJ[ay].sense === "max" ? "↑ mieux" : "↓ mieux"}</text>
      {(res.cloud ?? []).map((c, i) => <circle key={i} cx={pts.sx(Number(c.mean[ax] ?? 0))} cy={pts.sy(Number(c.mean[ay] ?? 0))} r={3} fill={c.feasible ? "#c4cad2" : "#f3c9c4"} />)}
      {front.map((s) => (
        <g key={s.key} onClick={() => onPick(s.id!)} style={{ cursor: "pointer" }}>
          <circle cx={pts.sx(Number(s.mean[ax]))} cy={pts.sy(Number(s.mean[ay]))} r={sel === s.id ? 8 : 6} fill="#3b7dd8" stroke={sel === s.id ? "#1f2d3d" : "#fff"} strokeWidth={2} />
          <text x={pts.sx(Number(s.mean[ax])) + 8} y={pts.sy(Number(s.mean[ay])) - 7} fontSize="10" fill="#1f4e79">{s.id}</text>
          <title>{`Solution ${s.id} : ${s.changes.join(" · ")}`}</title>
        </g>))}
      <path d={star(pts.sx(Number(res.base!.mean[ax])), pts.sy(Number(res.base!.mean[ay])), 9)} fill="#e67e22" stroke="#fff"><title>Configuration actuelle</title></path>
    </svg>
  );
}

function star(cx: number, cy: number, r: number) {
  let d = "";
  for (let i = 0; i < 10; i++) {
    const a = (Math.PI / 5) * i - Math.PI / 2, rr = i % 2 ? r * 0.45 : r;
    d += `${i ? "L" : "M"}${cx + rr * Math.cos(a)},${cy + rr * Math.sin(a)}`;
  }
  return d + "Z";
}
