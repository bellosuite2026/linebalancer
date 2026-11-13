// Menu « Optimiseur » : choix du calcul à optimiser.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, fmt, SOLVER_LABEL } from "../lib/api";
import { canWrite, useSession } from "../lib/session";
import type { Run } from "../lib/types";
import OptimizeButton from "../components/OptimizeButton";
import StatusBadge from "../components/StatusBadge";

export default function OptimizerHome() {
  const { currentOrg } = useSession();
  const org = currentOrg!;
  const writable = canWrite(org);
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => {
    api<Run[]>(`/v1/orgs/${org.id}/runs?limit=60`).then(setRuns).catch((e) => { setErr((e as Error).message); setRuns([]); });
  }, [org.id]);
  const ok = (runs ?? []).filter((r) => r.status === "done" && (r.stations_used ?? 0) > 0);

  return (
    <div className="page">
      <div className="page-head">
        <div><h1>Optimiseur</h1>
          <p className="muted">Choisissez un calcul : l'optimiseur simule des centaines de variantes (renforts, taille de paquet, encours, agents de liaison, placement) et vous propose les meilleurs compromis.</p></div>
      </div>
      {!writable && <p className="notice warn">Votre rôle est « lecteur » : vous pouvez consulter les optimisations déjà faites, mais pas en lancer de nouvelles. Demandez au propriétaire de l'atelier un rôle « méthodes » ou « chef de ligne ».</p>}
      {err && <p className="notice err">{err}</p>}
      <section className="card">
        {runs === null ? <p className="muted">Chargement des calculs…</p> : runs.length === 0 ? (
          <div className="empty-state"><b>Aucun calcul pour l'instant</b>Saisissez une gamme puis lancez un équilibrage : il pourra ensuite être optimisé.<br /><br />
            <Link className="btn primary" to="/calcul">Nouveau calcul</Link></div>
        ) : <>
          {ok.length === 0 && <p className="notice warn">Aucun de vos calculs n'a de solution à optimiser pour l'instant.</p>}
          <div className="table-wrap"><table>
            <thead><tr><th>Date</th><th>Calcul</th><th>Statut</th><th>Postes</th><th>Cycle (min)</th><th></th></tr></thead>
            <tbody>{runs.map((r) => (
              <tr key={r.id}>
                <td>{fmt.date(r.created_at)}</td>
                <td><Link to={`/calculs/${r.id}`}>{r.kind === "balance" ? "Équilibrage" : "Cadence min."}</Link> <small className="muted">{SOLVER_LABEL[r.solver] ?? r.solver}</small></td>
                <td><StatusBadge run={r} /></td>
                <td>{r.stations_used ?? "—"}</td>
                <td>{fmt.n(r.kind === "min_cycle" ? r.min_cycle_time : r.actual_cycle_time)}</td>
                <td><OptimizeButton run={r} runId={r.id} writable={writable} size="small" showWhy={false} /></td>
              </tr>))}</tbody>
          </table></div>
          <p className="muted small">Un bouton grisé = calcul sans solution, échoué ou en cours (survolez-le pour la raison).</p>
        </>}
      </section>
    </div>
  );
}
