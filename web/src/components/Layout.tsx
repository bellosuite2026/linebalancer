import type { ReactNode } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import { supabase } from "../lib/supabase";
import { useSession } from "../lib/session";
import { fmt } from "../lib/api";

export default function Layout({ children }: { children: ReactNode }) {
  const { orgs, currentOrg, setCurrentOrgId, session, isSuperAdmin } = useSession();
  const nav = useNavigate();
  const location = useLocation();
  const sub = currentOrg?.subscription;
  const trialDays = !isSuperAdmin && sub?.status === "trialing" && sub.trial_ends_at
    ? Math.max(0, Math.ceil((new Date(sub.trial_ends_at).getTime() - Date.now()) / 86400000)) : null;

  // Page tablette : plein écran, sans barre de navigation.
  if (/^\/production\/[^/]+\/saisie/.test(location.pathname)) return <main key={currentOrg?.id}>{children}</main>;

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand"><span className="logo" />Line Balancer</div>
        <nav>
          <NavLink to="/" end>Tableau de bord</NavLink>
          <NavLink to="/gamme">Gamme</NavLink>
          <NavLink to="/calcul">Nouveau calcul</NavLink>
          <NavLink to="/calculs">Historique</NavLink>
          <NavLink to="/production">Production</NavLink>
          <NavLink to="/atelier">Atelier</NavLink>
          {isSuperAdmin && <NavLink to="/admin" className={({ isActive }) => `nav-admin${isActive ? " active" : ""}`}>Super admin</NavLink>}
        </nav>
        <div className="top-right">
          {orgs.length > 0 && <select value={currentOrg?.id} onChange={(e) => {
            if (e.target.value === "__new") nav("/nouvel-atelier"); else { setCurrentOrgId(e.target.value); nav("/"); }
          }}>
            {orgs.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
            <option value="__new">+ Nouvel atelier…</option>
          </select>}
          <button className="link" title={session?.user.email} onClick={() => supabase.auth.signOut()}>Déconnexion</button>
        </div>
      </header>
      {isSuperAdmin && <div className="banner admin">Super admin : accès illimité à toutes les fonctionnalités, sans essai ni quota.</div>}
      {trialDays !== null && (
        <div className={`banner ${trialDays <= 5 ? "warn" : ""}`}>
          Essai gratuit : {trialDays} jour{trialDays > 1 ? "s" : ""} restant{trialDays > 1 ? "s" : ""} (jusqu'au {fmt.day(sub?.trial_ends_at)}).
        </div>
      )}
      <main key={currentOrg?.id}>{children}</main>
    </div>
  );
}
