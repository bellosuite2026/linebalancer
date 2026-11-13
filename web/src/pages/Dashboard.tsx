import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api, fmt, post } from "../lib/api";
import { canManage, canWrite, useSession } from "../lib/session";
import type { Line, Run } from "../lib/types";
import StatusBadge from "../components/StatusBadge";
import OptimizeButton from "../components/OptimizeButton";

export default function Dashboard() {
  const { currentOrg } = useSession();
  const org = currentOrg!;
  const [lines, setLines] = useState<Line[] | null>(null);
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [err, setErr] = useState("");
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ name: "", product: "", target_cycle_time: "" });

  const load = () => {
    api<Line[]>(`/v1/orgs/${org.id}/lines`).then(setLines).catch((e) => setErr(e.message));
    api<Run[]>(`/v1/orgs/${org.id}/runs?limit=8`).then(setRuns).catch((e) => setErr(e.message));
  };
  useEffect(load, [org.id]);

  const addLine = async (e: FormEvent) => {
    e.preventDefault(); setErr("");
    try {
      await post(`/v1/orgs/${org.id}/lines`, { name: form.name, product: form.product,
        target_cycle_time: form.target_cycle_time ? Number(form.target_cycle_time) : null });
      setForm({ name: "", product: "", target_cycle_time: "" }); setAdding(false); load();
    } catch (e) { setErr((e as Error).message); }
  };
  const delLine = async (l: Line) => {
    if (!confirm(`Supprimer la ligne « ${l.name} » ? Les calculs restent dans l'historique.`)) return;
    try { await api(`/v1/orgs/${org.id}/lines/${l.id}`, { method: "DELETE" }); load(); } catch (e) { setErr((e as Error).message); }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div><h1>{org.name}</h1><p className="muted">Vos lignes de production et vos derniers calculs.</p></div>
        <Link className="btn primary" to="/calcul">Nouveau calcul</Link>
      </div>
      {err && <p className="notice err">{err}</p>}

      <section className="card">
        <div className="card-head">
          <h3>Lignes de production</h3>
          {canManage(org) && !adding && <button className="btn" onClick={() => setAdding(true)}>+ Ajouter une ligne</button>}
        </div>
        {adding && (
          <form className="inline-form" onSubmit={addLine}>
            <input required placeholder="Nom (ex. Ligne 1)" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            <input placeholder="Produit (ex. chemise homme)" value={form.product} onChange={(e) => setForm({ ...form, product: e.target.value })} />
            <input type="number" step="0.01" min="0.01" placeholder="Cadence cible (min)" value={form.target_cycle_time}
              onChange={(e) => setForm({ ...form, target_cycle_time: e.target.value })} />
            <button className="btn primary">Créer</button>
            <button type="button" className="btn ghost" onClick={() => setAdding(false)}>Annuler</button>
          </form>
        )}
        {lines === null ? <p className="muted">Chargement…</p> : lines.length === 0 ? (
          <p className="muted">Aucune ligne pour l'instant. Une ligne regroupe les gammes et calculs d'une chaîne de montage.</p>
        ) : (
          <div className="grid-cards">
            {lines.map((l) => (
              <div key={l.id} className="mini-card">
                <b>{l.name}</b>
                <span className="muted">{l.product || "—"}</span>
                <span className="muted small">Cadence cible : {l.target_cycle_time ? `${fmt.n(l.target_cycle_time)} min` : "—"}</span>
                <div className="row">
                  <Link className="btn small" to={`/calcul?ligne=${l.id}`}>Calculer</Link>
                  {canManage(org) && <button className="link small" onClick={() => delLine(l)}>Supprimer</button>}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="card">
        <div className="card-head"><h3>Derniers calculs</h3><Link to="/calculs" className="link">Tout l'historique</Link></div>
        {runs === null ? <p className="muted">Chargement…</p> : runs.length === 0 ? (
          <div className="empty">
            <p>Pas encore de calcul. Lancez-en un avec l'exemple « chemise homme » pour voir le résultat.</p>
            <Link className="btn primary" to="/calcul?exemple=1">Essayer avec l'exemple</Link>
          </div>
        ) : <RunTable runs={runs} />}
      </section>
    </div>
  );
}

export function RunTable({ runs }: { runs: Run[] }) {
  const writable = canWrite(useSession().currentOrg);
  return (
    <div className="table-wrap">
      <table>
        <thead><tr><th>Date</th><th>Type</th><th>Solveur</th><th>Statut</th><th>Stations</th><th>Cycle (min)</th><th>Rendement</th><th></th><th></th></tr></thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.id}>
              <td>{fmt.date(r.created_at)}</td>
              <td>{r.kind === "balance" ? "Équilibrage" : "Cadence min."}</td>
              <td>{r.solver === "cp_sat" ? "CP-SAT" : "RPW"}</td>
              <td><StatusBadge run={r} /></td>
              <td>{r.stations_used ?? "—"}</td>
              <td>{r.kind === "min_cycle" ? fmt.n(r.min_cycle_time) : fmt.n(r.actual_cycle_time)}</td>
              <td>{r.efficiency != null ? `${fmt.n(r.efficiency, 1)} %` : "—"}</td>
              <td><Link to={`/calculs/${r.id}`} className="link">Voir</Link></td>
              <td><OptimizeButton run={r} runId={r.id} writable={writable} size="small" showWhy={false} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
