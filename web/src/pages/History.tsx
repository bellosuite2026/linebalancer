import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useSession } from "../lib/session";
import type { Run } from "../lib/types";
import { RunTable } from "./Dashboard";

export default function History() {
  const { currentOrg } = useSession();
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => { api<Run[]>(`/v1/orgs/${currentOrg!.id}/runs?limit=200`).then(setRuns).catch((e) => setErr(e.message)); }, [currentOrg]);
  return (
    <div className="page">
      <div className="page-head"><div><h1>Historique des calculs</h1><p className="muted">Tous les calculs de l'atelier, du plus récent au plus ancien.</p></div></div>
      {err && <p className="notice err">{err}</p>}
      <section className="card">{runs === null ? <p className="muted">Chargement…</p> : runs.length ? <RunTable runs={runs} /> : <p className="muted">Aucun calcul.</p>}</section>
    </div>
  );
}
