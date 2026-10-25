import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, download, fmt, post, SOLVER_LABEL } from "../lib/api";
import { canWrite, useSession } from "../lib/session";
import type { MinCycle, Result, Run } from "../lib/types";
import ResultView from "../components/ResultView";
import StatusBadge from "../components/StatusBadge";

export default function RunDetail() {
  const { id } = useParams();
  const { currentOrg } = useSession();
  const org = currentOrg!;
  const nav = useNavigate();
  const [run, setRun] = useState<Run | null>(null);
  const [err, setErr] = useState("");
  const [exporting, setExporting] = useState("");

  const exportAs = async (ext: "pdf" | "xlsx" | "json") => {
    if (!run) return;
    setExporting(ext);
    try {
      const base = ext === "json" ? "calcul" : "equilibrage";
      await download(`/v1/orgs/${org.id}/runs/${run.id}/export.${ext}`, `${base}_${run.id.slice(0, 8)}.${ext}`);
    } catch (e) { setErr((e as Error).message); } finally { setExporting(""); }
  };

  useEffect(() => {
    let stop = false, timer: number;
    const tick = async () => {
      try {
        const r = await api<Run>(`/v1/orgs/${org.id}/runs/${id}`);
        if (stop) return;
        setRun(r);
        if (r.status === "queued" || r.status === "running") timer = window.setTimeout(tick, 1500);
      } catch (e) { if (!stop) setErr((e as Error).message); }
    };
    tick();
    return () => { stop = true; clearTimeout(timer); };
  }, [id, org.id]);

  const relaunch = async (kind: "balance" | "min_cycle", solver: string) => {
    if (!run?.problem_id) return;
    try {
      const r = await post<Run>(`/v1/orgs/${org.id}/runs`, { problem_id: run.problem_id, kind, solver, time_limit_seconds: 20 });
      nav(`/calculs/${r.id}`);
    } catch (e) { setErr((e as Error).message); }
  };

  if (err && !run) return <div className="page"><p className="notice err">{err}</p><Link to="/calculs">Retour à l'historique</Link></div>;
  if (!run) return <div className="page muted">Chargement…</div>;

  const pending = run.status === "queued" || run.status === "running";
  const res = run.result as Result | MinCycle | null | undefined;
  const mc = run.kind === "min_cycle" ? (res as MinCycle | null) : null;
  const bal = run.kind === "balance" ? (res as Result | null) : mc?.result ?? null;

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>{run.kind === "balance" ? "Équilibrage" : "Cadence minimale"} <StatusBadge run={run} /></h1>
          <p className="muted">{SOLVER_LABEL[run.solver] ?? run.solver} · lancé le {fmt.date(run.created_at)}</p>
        </div>
        <div className="row">
          {run.status === "done" && (["pdf", "xlsx", "json"] as const).map((ext) => (
            <button key={ext} className="btn" disabled={exporting === ext} onClick={() => exportAs(ext)}>
              {exporting === ext ? "Préparation…" : ext === "pdf" ? "Rapport PDF" : ext === "xlsx" ? "Excel" : "JSON"}
            </button>
          ))}
        </div>
      </div>

      {err && <p className="notice err">{err}</p>}
      {pending && (
        <div className="card center-block">
          <div className="spinner" />
          <p>{run.status === "queued" ? "En attente d'un calculateur…" : "Calcul en cours…"}</p>
          <p className="muted small">{run.solver === "cp_sat" ? "L'optimisation CP-SAT peut prendre jusqu'à quelques minutes." : "Quelques secondes."} Vous pouvez quitter cette page, le résultat sera dans l'historique.</p>
        </div>
      )}
      {run.status === "failed" && <p className="notice err">Le calcul a échoué : {run.error || "erreur inconnue"}</p>}

      {run.status === "done" && mc && (
        mc.found
          ? <p className="notice ok">Cadence minimale atteignable : <b>{fmt.n(mc.min_cycle_time, 3)} min / pièce</b>, soit {fmt.n(60 / (mc.min_cycle_time || 1), 0)} pièces/heure avec vos moyens actuels.</p>
          : <p className="notice warn">Aucune cadence réalisable trouvée avec ces données (postes ou compétences insuffisants ?).</p>
      )}
      {run.status === "done" && bal && <ResultView r={bal} />}

      {run.status === "done" && canWrite(org) && run.problem_id && (
        <div className="row actions">
          {run.kind === "balance" && <button className="btn" onClick={() => relaunch("min_cycle", run.solver)}>Chercher la cadence minimale</button>}
          {run.solver === "rpw" && <button className="btn" onClick={() => relaunch(run.kind, "cp_sat")}>Optimiser avec CP-SAT</button>}
          <Link className="btn ghost" to="/calcul">Nouveau calcul</Link>
        </div>
      )}
    </div>
  );
}
