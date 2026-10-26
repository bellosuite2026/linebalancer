import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, download, fmt } from "../lib/api";
import { canWrite, useSession } from "../lib/session";
import { sessionsPath, type Dashboard, type PlanStation, type ProdSession } from "../lib/production";

const OP_COLORS = ["#2f6ea5", "#5b9bd5", "#8fb8e0", "#1f4e79", "#7aa6c2", "#a9c5dc"];

export default function ProductionDashboard() {
  const { id = "" } = useParams();
  const { currentOrg } = useSession();
  const org = currentOrg!;
  const [session, setSession] = useState<ProdSession | null>(null);
  const [d, setD] = useState<Dashboard | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState("");
  const [updated, setUpdated] = useState<Date | null>(null);
  const [confirmClose, setConfirmClose] = useState(false);

  const load = useCallback(async () => {
    try {
      const [s, dash] = await Promise.all([
        api<ProdSession>(`${sessionsPath(org.id)}/${id}`), api<Dashboard>(`${sessionsPath(org.id)}/${id}/dashboard`)]);
      setSession(s); setD(dash); setUpdated(new Date()); setErr("");
    } catch (e) { setErr((e as Error).message); }
  }, [org.id, id]);

  useEffect(() => {
    load();
    const t = window.setInterval(() => { if (document.visibilityState === "visible") load(); }, 15000);
    return () => clearInterval(t);
  }, [load]);

  const setStatus = async (status: "open" | "closed") => {
    setBusy(status);
    try {
      await api(`${sessionsPath(org.id)}/${id}`, { method: "PATCH", body: JSON.stringify({ status }) });
      setConfirmClose(false); await load();
    } catch (e) { setErr((e as Error).message); } finally { setBusy(""); }
  };
  const exportAs = async (ext: "xlsx" | "pdf") => {
    setBusy(ext);
    try { await download(`${sessionsPath(org.id)}/${id}/export.${ext}`, `production_${session?.session_date}_${id.slice(0, 8)}.${ext}`); }
    catch (e) { setErr((e as Error).message); } finally { setBusy(""); }
  };

  if (err && !d) return <div className="page"><p className="notice err">{err}</p><Link to="/production">Retour</Link></div>;
  if (!d || !session) return <div className="page muted">Chargement…</div>;
  const plan = session.plan;
  const open = session.status === "open";
  const pctCls = d.pct_target == null ? "" : d.pct_target >= 95 ? "ok" : d.pct_target >= 80 ? "" : "warn";

  return (
    <div className="page wide">
      <div className="page-head">
        <div>
          <h1>{session.model || "Session de production"} {open ? <span className="badge ok">Ouverte</span> : <span className="badge">Fermée</span>}</h1>
          <p className="muted">{session.line_name ? `${session.line_name} · ` : ""}{fmt.day(session.session_date)} · poste {session.shift_start.slice(0, 5)}, {fmt.n(session.shift_hours, 1)} h · objectif {fmt.n(session.target_per_hour, 1)} pcs/h
            {updated && <> · actualisé à {updated.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</>}</p>
        </div>
        <div className="row">
          {open && canWrite(org) && <Link className="btn primary" to={`/production/${id}/saisie`}>Saisie tablette</Link>}
          <button className="btn" disabled={busy === "xlsx"} onClick={() => exportAs("xlsx")}>{busy === "xlsx" ? "Préparation…" : "Excel"}</button>
          <button className="btn" disabled={busy === "pdf"} onClick={() => exportAs("pdf")}>{busy === "pdf" ? "Préparation…" : "Rapport PDF"}</button>
          {canWrite(org) && (open
            ? <button className="btn ghost" onClick={() => setConfirmClose(true)}>Fermer la session</button>
            : <button className="btn ghost" disabled={busy === "open"} onClick={() => setStatus("open")}>Rouvrir</button>)}
        </div>
      </div>
      {err && <p className="notice err">{err}</p>}

      {d.alerts.length > 0 && (
        <ul className="issues alerts">
          {d.alerts.map((a, i) => <li key={i} className={a.level === "danger" ? "error" : "warning"}><b>{a.level === "danger" ? "Urgent" : "Alerte"}</b>{a.message}</li>)}
        </ul>
      )}

      <div className="kpis">
        <div className={`kpi ${pctCls}`}><span>Réalisé (pièces finies)</span><b>{d.output} / {fmt.n(d.expected_to_date, 0)}</b><small>{d.pct_target != null ? `${fmt.n(d.pct_target, 0)} % de l'objectif à date` : "le poste n'a pas commencé"}</small></div>
        <div className="kpi"><span>Objectif du poste</span><b>{fmt.n(d.target_shift, 0)}</b><small>{fmt.n(d.elapsed_minutes, 0)} / {fmt.n(d.shift_minutes, 0)} min écoulées</small></div>
        <div className={`kpi ${d.efficiency != null && d.efficiency < 70 ? "warn" : d.efficiency != null ? "ok" : ""}`}><span>Efficience</span><b>{d.efficiency != null ? `${fmt.n(d.efficiency, 0)} %` : "—"}</b><small>minutes produites / présence</small></div>
        <div className={`kpi ${d.bottleneck_observed && d.bottleneck_observed !== d.bottleneck_planned ? "warn" : ""}`}><span>Goulot observé / calculé</span><b>{d.bottleneck_observed ? `S${d.bottleneck_observed}` : "—"} / {d.bottleneck_planned ? `S${d.bottleneck_planned}` : "—"}</b><small>{d.bottleneck_observed && d.bottleneck_observed !== d.bottleneck_planned ? "différent du calcul" : "conforme au calcul"}</small></div>
        <div className="kpi"><span>Encours</span><b>{d.wip_total}</b><small>pièces entre stations</small></div>
        <div className={`kpi ${d.downtime_total > 15 ? "warn" : ""}`}><span>Arrêts cumulés</span><b>{fmt.n(d.downtime_total, 0)} min</b><small>{d.defects} défauts · {d.rework} retouches</small></div>
      </div>

      <section className="card">
        <div className="card-head"><h3>Réalisé et objectif par heure</h3><span className="muted small">pièces sorties de la dernière station</span></div>
        <HourlyChart d={d} />
      </section>

      {plan && (
        <section className="card">
          <div className="card-head"><h3>Yamazumi : prévu et réel</h3><span className="muted small">min par pièce et par opérateur ; réel = temps de marche / pièces sorties</span></div>
          <Yamazumi stations={plan.stations} d={d} cycle={plan.cycle_time || plan.takt_time || 0} />
        </section>
      )}

      <section className="card">
        <h3>Par station</h3>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Station</th><th>Opérations</th><th>Ouvriers</th><th>Pièces</th><th>Objectif à date</th><th>% objectif</th><th>Efficience</th><th>Défauts / ret.</th><th>Arrêts</th><th>Encours aval</th></tr></thead>
            <tbody>
              {d.stations.map((s, i) => {
                const low = s.pct_target != null && s.pct_target < 80;
                return (
                  <tr key={s.station} className={low || s.ongoing_stop ? "row-over" : ""}>
                    <td><b>S{s.station}</b>{s.station === d.bottleneck_planned && <span className="badge small info">goulot calc.</span>}{s.station === d.bottleneck_observed && <span className="badge small warn">goulot obs.</span>}</td>
                    <td>{s.operations.join(", ")}</td>
                    <td>{s.workers.join(", ") || "—"}</td>
                    <td><b>{s.pieces}</b></td>
                    <td>{fmt.n(s.expected, 0)}</td>
                    <td><span className="meter"><div className={low ? "over" : ""} style={{ width: `${Math.min(100, s.pct_target || 0)}%` }} /></span>{s.pct_target != null ? `${fmt.n(s.pct_target, 0)} %` : "—"}</td>
                    <td>{s.efficiency != null ? `${fmt.n(s.efficiency, 0)} %` : "—"}</td>
                    <td>{s.defects} / {s.rework}</td>
                    <td>{fmt.n(s.downtime_minutes, 0)} min{s.ongoing_stop && <span className="badge small err">en cours</span>}</td>
                    <td>{d.wip[i] ? d.wip[i].pieces : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section className="card">
        <h3>Arrêts par motif</h3>
        <div className="reasons">
          {d.downtime_by_reason.map((r) => {
            const max = Math.max(1, ...d.downtime_by_reason.map((x) => x.minutes));
            return (
              <div key={r.reason} className="reason-row">
                <span>{r.label}</span>
                <div className="reason-bar"><div style={{ width: `${(r.minutes / max) * 100}%` }} /></div>
                <b>{fmt.n(r.minutes, 0)} min</b>
              </div>
            );
          })}
        </div>
        {d.stops.length > 0 && (
          <div className="table-wrap" style={{ marginTop: ".8rem" }}>
            <table>
              <thead><tr><th>Heure</th><th>Station</th><th>Motif</th><th>Durée</th><th>Commentaire</th></tr></thead>
              <tbody>
                {[...d.stops].reverse().map((s) => (
                  <tr key={s.client_id}><td>{s.slot_hour} h</td><td>S{s.station}</td><td>{s.label}</td>
                    <td>{fmt.n(s.minutes, 0)} min {s.ongoing && <span className="badge small err">en cours</span>}</td><td>{s.comment || "—"}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {confirmClose && (
        <div className="modal-back" onClick={() => setConfirmClose(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3>Fermer la session ?</h3>
            <p className="muted">La saisie sera verrouillée et le tableau de bord figé à cette heure. Vous pourrez la rouvrir si besoin.</p>
            <div className="row">
              <button className="btn primary" disabled={busy === "closed"} onClick={() => setStatus("closed")}>Fermer la session</button>
              <button className="btn ghost" onClick={() => setConfirmClose(false)}>Annuler</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function HourlyChart({ d }: { d: Dashboard }) {
  const hs = d.hourly;
  if (!hs.length) return null;
  const max = Math.max(1, ...hs.map((h) => Math.max(h.output, h.target, d.target_per_hour))) * 1.15;
  const W = Math.max(560, hs.length * 60), H = 240, pad = { l: 40, r: 10, t: 14, b: 28 };
  const bw = (W - pad.l - pad.r) / hs.length;
  const y = (v: number) => pad.t + (H - pad.t - pad.b) * (1 - v / max);
  const pts = hs.map((h, i) => `${pad.l + i * bw + bw / 2},${y(h.target)}`).join(" ");
  return (
    <div className="chart-wrap">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Réalisé par heure">
        {[0, d.target_per_hour, max / 1.15].filter((v, i, a) => a.indexOf(v) === i).map((t) => (
          <g key={t}><line x1={pad.l} x2={W - pad.r} y1={y(t)} y2={y(t)} className="grid" />
            <text x={pad.l - 6} y={y(t) + 4} textAnchor="end" className="axis">{Math.round(t)}</text></g>
        ))}
        {hs.map((h, i) => {
          const ok = h.target > 0 ? h.output >= 0.8 * h.target : h.output > 0;
          return (
            <g key={h.hour}>
              <rect x={pad.l + i * bw + bw * 0.2} width={bw * 0.6} y={y(h.output)} height={Math.max(0, y(0) - y(h.output))} className={`bar ${ok ? "good" : h.target > 0 ? "mid" : "low"}`}>
                <title>{`${h.hour} h : ${h.output} pièces / objectif ${Math.round(h.target)}${h.downtime_minutes ? ` · arrêts ${Math.round(h.downtime_minutes)} min` : ""}`}</title>
              </rect>
              {h.output > 0 && <text x={pad.l + i * bw + bw / 2} y={y(h.output) - 4} textAnchor="middle" className="axis">{h.output}</text>}
              <text x={pad.l + i * bw + bw / 2} y={H - 10} textAnchor="middle" className="axis">{h.hour} h</text>
            </g>
          );
        })}
        <polyline points={pts} fill="none" className="target" />
      </svg>
      <div className="legend"><span><i className="good" />≥ 80 % de l'objectif</span><span><i className="mid" />&lt; 80 %</span><span><i style={{ background: "transparent", borderTop: "2px dashed #1f4e79", borderRadius: 0 }} />objectif de l'heure</span></div>
    </div>
  );
}

function Yamazumi({ stations, d, cycle }: { stations: PlanStation[]; d: Dashboard; cycle: number }) {
  if (!stations.length) return null;
  const real = Object.fromEntries(d.stations.map((s) => [s.station, s.real_minutes_per_piece != null ? s.real_minutes_per_piece / Math.max(1, s.operators) : null]));
  const planned = (s: PlanStation) => s.minutes / Math.max(1, s.operators);
  const capped = (v: number) => Math.min(v, cycle * 3 || v);
  const max = Math.max(cycle * 1.2, ...stations.map(planned), ...stations.map((s) => capped(real[s.station] ?? 0))) || 1;
  const W = Math.max(560, stations.length * 70), H = 260, pad = { l: 40, r: 10, t: 14, b: 30 };
  const gw = (W - pad.l - pad.r) / stations.length;
  const y = (v: number) => pad.t + (H - pad.t - pad.b) * (1 - v / max);
  return (
    <div className="chart-wrap">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Yamazumi réel et prévu">
        {[0, cycle / 2, cycle].filter((v, i, a) => a.indexOf(v) === i).map((t) => (
          <g key={t}><line x1={pad.l} x2={W - pad.r} y1={y(t)} y2={y(t)} className="grid" />
            <text x={pad.l - 6} y={y(t) + 4} textAnchor="end" className="axis">{t.toLocaleString("fr-FR", { maximumFractionDigits: 2 })}</text></g>
        ))}
        {stations.map((s, i) => {
          const x0 = pad.l + i * gw + gw * 0.12, bw = gw * 0.36;
          let acc = 0;
          const ops = s.operations.length ? s.operations : [{ id: `S${s.station}`, name: "", minutes: s.minutes }];
          const scale = ops.reduce((a, o) => a + o.minutes, 0) > 0 ? planned(s) / ops.reduce((a, o) => a + o.minutes, 0) : 0;
          const r = real[s.station];
          const over = r != null && r > cycle * 1.0001;
          return (
            <g key={s.station}>
              {ops.map((o, j) => {
                const v = o.minutes * scale, top = acc + v;
                const el = <rect key={o.id} x={x0} width={bw} y={y(top)} height={Math.max(0, y(acc) - y(top))} fill={OP_COLORS[j % OP_COLORS.length]} stroke="#fff" strokeWidth={0.6}>
                  <title>{`${o.id} ${o.name} : ${v.toFixed(2)} min`}</title></rect>;
                acc = top;
                return el;
              })}
              {r != null && (
                <rect x={x0 + bw + gw * 0.04} width={bw} y={y(capped(r))} height={Math.max(0, y(0) - y(capped(r)))} className={`bar ${over ? "over" : "good"}`}>
                  <title>{`Réel S${s.station} : ${r.toFixed(2)} min/pièce`}</title>
                </rect>
              )}
              <text x={pad.l + i * gw + gw / 2} y={H - 12} textAnchor="middle" className="axis">S{s.station}</text>
            </g>
          );
        })}
        {cycle > 0 && <><line x1={pad.l} x2={W - pad.r} y1={y(cycle)} y2={y(cycle)} className="target" />
          <text x={W - pad.r} y={y(cycle) - 5} textAnchor="end" className="target-label">Cycle {cycle.toLocaleString("fr-FR", { maximumFractionDigits: 2 })} min</text></>}
      </svg>
      <div className="legend"><span><i style={{ background: OP_COLORS[0] }} />prévu (empilé par opération)</span><span><i className="good" />réel ≤ cycle</span><span><i className="over" />réel &gt; cycle</span></div>
    </div>
  );
}
