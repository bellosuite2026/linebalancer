import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, fmt, post } from "../lib/api";
import { canWrite, useSession } from "../lib/session";
import type { Line, ProblemRow, Run } from "../lib/types";
import { sessionsPath, type ProdSession } from "../lib/production";

const today = () => new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Tunis" }).format(new Date());

export default function Production() {
  const { currentOrg } = useSession();
  const org = currentOrg!;
  const nav = useNavigate();
  const [params] = useSearchParams();
  const [sessions, setSessions] = useState<ProdSession[] | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [problems, setProblems] = useState<Record<string, string>>({});
  const [lines, setLines] = useState<Line[]>([]);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [showForm, setShowForm] = useState(!!params.get("calcul"));
  const [form, setForm] = useState({ run_id: params.get("calcul") || "", model: "", line_id: "", session_date: today(),
    shift_start: "08:00", shift_hours: "8", target_per_hour: "" });

  useEffect(() => {
    api<ProdSession[]>(sessionsPath(org.id)).then(setSessions).catch((e) => setErr(e.message));
    api<Run[]>(`/v1/orgs/${org.id}/runs?limit=100`).then((rs) => setRuns(rs.filter((r) => r.status === "done" && r.stations_used))).catch(() => {});
    api<ProblemRow[]>(`/v1/orgs/${org.id}/problems?limit=200`).then((ps) => setProblems(Object.fromEntries(ps.map((p) => [p.id, p.name])))).catch(() => {});
    api<Line[]>(`/v1/orgs/${org.id}/lines`).then(setLines).catch(() => {});
  }, [org.id]);

  const run = runs.find((r) => r.id === form.run_id);
  const suggested = run?.actual_cycle_time ? Math.round((600 / run.actual_cycle_time)) / 10 : null;
  const label = (r: Run) => `${(r.problem_id && problems[r.problem_id]) || "Gamme"} · ${fmt.date(r.created_at)} · ${r.stations_used} stations · cycle ${fmt.n(r.actual_cycle_time)} min`;
  const open = useMemo(() => (sessions || []).filter((s) => s.status === "open"), [sessions]);

  const start = async (e: FormEvent) => {
    e.preventDefault(); setErr(""); setBusy(true);
    try {
      const s = await post<ProdSession>(sessionsPath(org.id), {
        run_id: form.run_id, model: form.model, line_id: form.line_id || null, session_date: form.session_date,
        shift_start: form.shift_start, shift_hours: Number(form.shift_hours),
        target_per_hour: form.target_per_hour ? Number(form.target_per_hour) : null,
      });
      nav(`/production/${s.id}/saisie`);
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div><h1>Suivi de production</h1><p className="muted">Pilotez la ligne en direct : saisie sur tablette, tableau de bord heure par heure.</p></div>
        {canWrite(org) && !showForm && <button className="btn primary" onClick={() => setShowForm(true)}>Démarrer une session</button>}
      </div>
      {err && <p className="notice err">{err}</p>}

      {showForm && (
        <section className="card">
          <h3>Démarrer une session depuis un calcul</h3>
          {runs.length === 0 ? (
            <p className="muted">Il faut d'abord un calcul d'équilibrage terminé. <Link to="/calcul">Lancer un calcul</Link></p>
          ) : (
            <form onSubmit={start}>
              <label>Calcul de référence (stations, ouvriers, cadence)
                <select required value={form.run_id} onChange={(e) => setForm({ ...form, run_id: e.target.value })}>
                  <option value="">Choisir un calcul…</option>
                  {runs.map((r) => <option key={r.id} value={r.id}>{label(r)}</option>)}
                </select>
              </label>
              <div className="form-grid">
                <label>Modèle<input placeholder={(run?.problem_id && problems[run.problem_id]) || "ex. Polo M"} value={form.model} onChange={(e) => setForm({ ...form, model: e.target.value })} /></label>
                <label>Ligne
                  <select value={form.line_id} onChange={(e) => setForm({ ...form, line_id: e.target.value })}>
                    <option value="">—</option>
                    {lines.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
                  </select>
                </label>
                <label>Date<input type="date" required value={form.session_date} onChange={(e) => setForm({ ...form, session_date: e.target.value })} /></label>
                <label>Début du poste<input type="time" required value={form.shift_start} onChange={(e) => setForm({ ...form, shift_start: e.target.value })} /></label>
                <label>Durée (heures)<input type="number" min="0.5" max="24" step="0.5" required value={form.shift_hours} onChange={(e) => setForm({ ...form, shift_hours: e.target.value })} /></label>
                <label>Objectif (pièces / heure)
                  <input type="number" min="0.1" step="0.1" placeholder={suggested ? `${fmt.n(suggested, 1)} (selon le calcul)` : "selon le calcul"}
                    value={form.target_per_hour} onChange={(e) => setForm({ ...form, target_per_hour: e.target.value })} />
                </label>
              </div>
              <div className="row">
                <button className="btn primary" disabled={busy}>{busy ? "Ouverture…" : "Ouvrir la session et passer à la saisie"}</button>
                <button type="button" className="btn ghost" onClick={() => setShowForm(false)}>Annuler</button>
              </div>
            </form>
          )}
        </section>
      )}

      <section className="card">
        <div className="card-head"><h3>Sessions</h3>{open.length > 0 && <span className="badge ok">{open.length} ouverte{open.length > 1 ? "s" : ""}</span>}</div>
        {sessions === null ? <p className="muted">Chargement…</p> : sessions.length === 0 ? (
          <p className="muted">Aucune session pour l'instant. Démarrez-en une à partir d'un calcul : la tablette de la ligne affichera chaque station avec de gros boutons de comptage.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead><tr><th>Date</th><th>Ligne</th><th>Modèle</th><th>Poste</th><th>Objectif</th><th>Statut</th><th></th></tr></thead>
              <tbody>
                {sessions.map((s) => (
                  <tr key={s.id}>
                    <td>{fmt.day(s.session_date)}</td>
                    <td>{s.line_name || "—"}</td>
                    <td>{s.model || "—"}</td>
                    <td>{s.shift_start.slice(0, 5)} · {fmt.n(s.shift_hours, 1)} h</td>
                    <td>{fmt.n(s.target_per_hour, 1)} pcs/h</td>
                    <td>{s.status === "open" ? <span className="badge ok">Ouverte</span> : <span className="badge">Fermée</span>}</td>
                    <td className="row">
                      {s.status === "open" && canWrite(org) && <Link className="btn small primary" to={`/production/${s.id}/saisie`}>Saisie tablette</Link>}
                      <Link className="btn small" to={`/production/${s.id}`}>Tableau de bord</Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
