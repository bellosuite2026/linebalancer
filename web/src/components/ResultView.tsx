import type { Result } from "../lib/types";
import { fmt, SOLVER_LABEL } from "../lib/api";
import LoadChart from "./LoadChart";

export default function ResultView({ r }: { r: Result }) {
  const output = r.actual_cycle_time > 0 ? 60 / r.actual_cycle_time : 0;
  const errors = r.violations.filter((v) => v.severity === "error");
  const otherWarnings = r.warnings.filter((w) => !w.startsWith("["));
  return (
    <>
      {!r.success && r.error_message && <p className="notice err">{r.error_message}</p>}
      {r.success && !r.compliant && (
        <p className="notice warn">Solution trouvée, mais {errors.length || r.violations.length} point(s) à corriger avant de l'appliquer en atelier (voir ci-dessous).</p>
      )}
      <div className="kpis">
        <Kpi label="Stations" value={r.stations_used} />
        <Kpi label="Opérateurs" value={r.operators} />
        <Kpi label="Cycle réel" value={`${fmt.n(r.actual_cycle_time)} min`} sub={`cible ${fmt.n(r.target_cycle_time)}`} />
        <Kpi label="Rendement ligne" value={`${fmt.n(r.efficiency, 1)} %`} tone={r.efficiency >= 85 ? "ok" : r.efficiency >= 70 ? "" : "warn"} />
        <Kpi label="Production" value={`${fmt.n(output, 0)} pcs/h`} sub={`${fmt.n(output * 8, 0)} pcs / 8 h`} />
        <Kpi label="Perte d'équilibrage" value={`${fmt.n(r.balance_delay, 1)} %`} />
      </div>

      <section className="card">
        <h3>Charge par station</h3>
        <LoadChart stations={r.station_details} cycle={r.target_cycle_time} />
      </section>

      <section className="card">
        <h3>Répartition</h3>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Station</th><th>Opérations</th><th>Temps (min)</th><th>Charge</th><th>Poste(s)</th><th>Ouvrier(s)</th></tr></thead>
            <tbody>
              {r.station_details.map((s) => (
                <tr key={s.station} className={s.load_pct > 100.01 ? "row-over" : ""}>
                  <td><b>{s.station}</b>{(s.parallel ?? 1) > 1 && <span className="badge small">×{s.parallel}</span>}</td>
                  <td>{s.operations.join(", ")}</td>
                  <td>{fmt.n(s.total_time)}</td>
                  <td><div className="meter"><div style={{ width: `${Math.min(100, s.load_pct)}%` }} className={s.load_pct > 100.01 ? "over" : ""} /></div>{fmt.n(s.load_pct, 0)} %</td>
                  <td>{(s.workstations ?? (s.workstation ? [s.workstation] : [])).join(", ") || <span className="err-text">aucun</span>}</td>
                  <td>{s.workers.join(", ") || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {(r.violations.length > 0 || r.warnings.length > 0) && (
        <section className="card">
          <h3>Points d'attention</h3>
          <ul className="issues">
            {r.violations.map((v, i) => <li key={"v" + i} className={v.severity}><b>{v.code}</b> {v.message}{v.suggestion && <em> → {v.suggestion}</em>}</li>)}
            {r.warnings.filter((w) => w.startsWith("[")).map((w, i) => <li key={"w" + i} className="warning">{w}</li>)}
          </ul>
        </section>
      )}
      <p className="muted small">Solveur : {SOLVER_LABEL[r.solver] ?? r.solver} · statut {r.status} · {fmt.n(r.solve_time_seconds, 2)} s{otherWarnings.length ? " · " + otherWarnings.join(" · ") : ""}</p>
    </>
  );
}

function Kpi({ label, value, sub, tone = "" }: { label: string; value: string | number; sub?: string; tone?: string }) {
  return <div className={`kpi ${tone}`}><span>{label}</span><b>{value}</b>{sub && <small>{sub}</small>}</div>;
}
