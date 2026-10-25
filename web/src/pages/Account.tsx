import { useEffect, useState } from "react";
import { api, fmt, ROLE_LABEL } from "../lib/api";
import { useSession } from "../lib/session";
import type { OrgDetail } from "../lib/types";

const STATUS: Record<string, string> = { trialing: "Essai en cours", active: "Actif", past_due: "Paiement en retard", canceled: "Résilié" };

export default function Account() {
  const { currentOrg, session } = useSession();
  const [d, setD] = useState<OrgDetail | null>(null);
  const [err, setErr] = useState("");
  useEffect(() => { api<OrgDetail>(`/v1/orgs/${currentOrg!.id}`).then(setD).catch((e) => setErr(e.message)); }, [currentOrg]);
  const p = d?.plan?.plan;
  return (
    <div className="page">
      <div className="page-head"><div><h1>Atelier</h1><p className="muted">Offre, limites et membres.</p></div></div>
      {err && <p className="notice err">{err}</p>}
      {d && (
        <>
          <section className="card">
            <h3>{d.name}</h3>
            <p>Votre rôle : <b>{ROLE_LABEL[d.role]}</b></p>
            {d.plan && p && (
              <div className="kpis">
                <div className="kpi"><span>Offre</span><b>{p.name}</b><small>{STATUS[d.plan.status] ?? d.plan.status}</small></div>
                <div className="kpi"><span>{d.plan.status === "trialing" ? "Fin d'essai" : "Échéance"}</span><b>{fmt.day(d.plan.trial_ends_at ?? d.plan.current_period_end)}</b></div>
                <div className="kpi"><span>Lignes</span><b>{p.max_lines}</b><small>maximum</small></div>
                <div className="kpi"><span>Utilisateurs</span><b>{p.max_users}</b><small>maximum</small></div>
                <div className="kpi"><span>Opérations / gamme</span><b>{p.max_operations}</b></div>
              </div>
            )}
            <p className="muted small">Pour passer à l'offre Atelier (149 TND/mois) ou Usine (390 TND/mois), contactez-nous.</p>
          </section>
          <section className="card">
            <h3>Membres</h3>
            <table><thead><tr><th>Utilisateur</th><th>Rôle</th><th>Depuis</th></tr></thead>
              <tbody>{d.members.map((m) => (
                <tr key={m.user_id}><td>{m.user_id === session?.user.id ? `${session.user.email} (vous)` : m.user_id.slice(0, 8) + "…"}</td>
                  <td>{ROLE_LABEL[m.role]}</td><td>{fmt.day(m.created_at)}</td></tr>))}</tbody></table>
            <p className="muted small">L'invitation de collègues arrive dans la prochaine version.</p>
          </section>
        </>
      )}
    </div>
  );
}
