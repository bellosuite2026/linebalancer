import type { ReactNode } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { supabase } from "../lib/supabase";
import { useSession } from "../lib/session";
import { fmt } from "../lib/api";

export default function Layout({ children }: { children: ReactNode }) {
  const { orgs, currentOrg, setCurrentOrgId, session } = useSession();
  const nav = useNavigate();
  const sub = currentOrg?.subscription;
  const trialDays = sub?.status === "trialing" && sub.trial_ends_at
    ? Math.max(0, Math.ceil((new Date(sub.trial_ends_at).getTime() - Date.now()) / 86400000)) : null;

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand"><span className="logo" />Line Balancer</div>
        <nav>
          <NavLink to="/" end>Tableau de bord</NavLink>
          <NavLink to="/calcul">Nouveau calcul</NavLink>
          <NavLink to="/calculs">Historique</NavLink>
          <NavLink to="/atelier">Atelier</NavLink>
        </nav>
        <div className="top-right">
          <select value={currentOrg?.id} onChange={(e) => {
            if (e.target.value === "__new") nav("/nouvel-atelier"); else { setCurrentOrgId(e.target.value); nav("/"); }
          }}>
            {orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
            <option value="__new">+ Nouvel atelier…</option>
          </select>
          <button className="link" title={session?.user.email} onClick={() => supabase.auth.signOut()}>Déconnexion</button>
        </div>
      </header>
      {trialDays !== null && (
        <div className={`banner ${trialDays <= 5 ? "warn" : ""}`}>
          Essai gratuit : {trialDays} jour{trialDays > 1 ? "s" : ""} restant{trialDays > 1 ? "s" : ""} (jusqu'au {fmt.day(sub?.trial_ends_at)}).
        </div>
      )}
      <main key={currentOrg?.id}>{children}</main>
    </div>
  );
}
