import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, fmt, SOLVER_LABEL } from "../lib/api";
import { canWrite, useSession } from "../lib/session";
import type { Run } from "../lib/types";
import type { PlanSummary } from "../lib/workshop";

const VERSION: Record<string, string> = { actuel: "Actuel", projet: "Projet", archive: "Archivé" };

export default function TwinHome() {
  const { currentOrg } = useSession();
  const org = currentOrg!;
  const nav = useNavigate();
  const [plans, setPlans] = useState<PlanSummary[] | null>(null);
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [pick, setPick] = useState<Record<string, string>>({});
  const [err, setErr] = useState("");
  const base = `/v1/orgs/${org.id}`;

  useEffect(() => {
    api<PlanSummary[]>(`${base}/workshop-plans`).then(setPlans).catch((e) => { setErr((e as Error).message); setPlans([]); });
    api<Run[]>(`${base}/runs?limit=30`).then((r) => setRuns(r.filter((x) => x.status === "done" && x.kind === "balance" && (x.stations_used ?? 0) > 0)))
      .catch((e) => { setErr((e as Error).message); setRuns([]); });
  }, [base]);

  const defaultPlan = plans?.find((p) => p.version === "actuel")?.id ?? plans?.[0]?.id ?? "";

  return (
    <div className="page">
      <div className="page-head">
        <div><h1>Jumeau numérique</h1>
          <p className="muted">Préparez le plan de l'atelier, puis simulez une journée de production et l'équilibrage sur vos machines réelles.</p></div>
        {canWrite(org) && <Link className="btn primary" to="/atelier/plan">Plan de l'atelier</Link>}
      </div>
      {err && <p className="notice err">{err}</p>}

      <ol className="steps">
        <li className={plans?.length ? "done" : ""}><b>1. Plan de l'atelier</b><span>Importez un plan (image, PDF, DXF) ou dessinez la salle, les allées et les zones, puis posez vos machines.</span></li>
        <li className={runs?.length ? "done" : ""}><b>2. Calcul d'équilibrage</b><span>Saisissez la gamme et lancez un calcul (<Link to="/calcul">nouveau calcul</Link>).</span></li>
        <li><b>3. Simulation sur le plan</b><span>Les stations sont placées sur les machines du plan : distances réelles, parcours des paquets, scénarios « et si ». « Simulation 3D » = simulation à événements discrets détaillée (paquets, opérateurs qui marchent, agents de liaison, pannes, pauses, réplications).</span></li>
      </ol>

      <section className="card">
        <div className="card-head"><h3>Plans d'atelier</h3>{canWrite(org) && <Link className="btn small" to="/atelier/plan">+ Nouveau plan</Link>}</div>
        {plans === null ? <p className="muted">Chargement…</p> : plans.length === 0 ? (
          <p className="muted">Aucun plan pour l'instant. <Link to="/atelier/plan">Dessinez ou importez le plan de l'atelier</Link> : c'est la base de la simulation.</p>
        ) : (
          <div className="table-wrap"><table>
            <thead><tr><th>Plan</th><th>Version</th><th>Salle</th><th>Machines</th><th>Modifié</th><th></th></tr></thead>
            <tbody>{plans.map((p) => (
              <tr key={p.id}>
                <td><Link to={`/atelier/plan?id=${p.id}`}>{p.name}</Link></td>
                <td><span className={`badge ${p.version === "actuel" ? "ok" : p.version === "projet" ? "info" : ""}`}>{VERSION[p.version] ?? p.version}</span></td>
                <td>{fmt.n(Number(p.width_m), 1)} × {fmt.n(Number(p.length_m), 1)} m</td>
                <td>{p.machine_count}</td><td>{fmt.date(p.updated_at)}</td>
                <td><Link className="btn small" to={`/atelier/plan?id=${p.id}`}>Ouvrir</Link></td>
              </tr>))}</tbody>
          </table></div>
        )}
      </section>

      <section className="card">
        <div className="card-head"><h3>Calculs récents</h3></div>
        {runs === null ? <p className="muted">Chargement…</p> : runs.length === 0 ? (
          <p className="muted">Aucun calcul terminé. <Link to="/calcul">Lancez un calcul d'équilibrage</Link> pour le simuler.</p>
        ) : (
          <div className="table-wrap"><table>
            <thead><tr><th>Date</th><th>Solveur</th><th>Stations</th><th>Cycle</th><th>Simuler</th></tr></thead>
            <tbody>{runs.map((r) => {
              const pid = pick[r.id] ?? defaultPlan;
              return (
                <tr key={r.id}>
                  <td><Link to={`/calculs/${r.id}`}>{fmt.date(r.created_at)}</Link></td>
                  <td>{SOLVER_LABEL[r.solver] ?? r.solver}</td><td>{r.stations_used}</td>
                  <td>{r.actual_cycle_time ? `${fmt.n(r.actual_cycle_time, 2)} min` : "—"}</td>
                  <td className="row tight">
                    <Link className="btn small" to={`/jumeau/${r.id}`}>Jumeau numérique</Link>
                    <Link className="btn small" to={`/simulation/${r.id}${pid ? `?plan=${pid}` : ""}`}>Simulation 3D</Link>
                    {plans && plans.length > 0 && <>
                      <select value={pid} onChange={(e) => setPick({ ...pick, [r.id]: e.target.value })} aria-label="Plan d'atelier">
                        {plans.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select>
                      <button className="btn small primary" disabled={!pid} onClick={() => nav(`/jumeau/${r.id}?plan=${pid}`)}>Simuler sur un plan</button>
                    </>}
                  </td>
                </tr>);
            })}</tbody>
          </table></div>
        )}
      </section>
    </div>
  );
}
