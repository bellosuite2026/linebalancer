import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useSession } from "./lib/session";
import Layout from "./components/Layout";
import Login from "./pages/Login";
import NewPassword from "./pages/NewPassword";
import Onboarding from "./pages/Onboarding";
import Dashboard from "./pages/Dashboard";
import NewRun from "./pages/NewRun";
import RunDetail from "./pages/RunDetail";
import History from "./pages/History";
import Account from "./pages/Account";
import GammeEditor from "./pages/GammeEditor";
import FileHelp from "./pages/FileHelp";
import Admin from "./pages/Admin";
import Production from "./pages/Production";
import ProductionEntry from "./pages/ProductionEntry";
import ProductionDashboard from "./pages/ProductionDashboard";
import Twin from "./pages/Twin";
import TwinHome from "./pages/TwinHome";
import WorkshopPlan from "./pages/WorkshopPlan";

export default function App() {
  const { session, loading, recovery, orgs, orgsLoaded, orgsError, refreshOrgs, isSuperAdmin } = useSession();
  const location = useLocation();

  if (loading) return <div className="center muted">Chargement…</div>;
  if (recovery) return <NewPassword />;
  if (!session) return <Login />;
  if (!orgsLoaded) return <div className="center muted">Connexion au serveur…<br /><small>Le premier accès peut prendre jusqu'à une minute.</small></div>;
  if (orgsError) return (
    <div className="center">
      <div className="card narrow">
        <h2>Serveur indisponible</h2>
        <p className="muted">{orgsError}</p>
        <button className="btn" onClick={() => refreshOrgs()}>Réessayer</button>
      </div>
    </div>
  );
  if (orgs.length === 0 && !(isSuperAdmin && location.pathname.startsWith("/admin"))) return <Onboarding />;

  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/gamme" element={<GammeEditor />} />
        <Route path="/aide/fichiers" element={<FileHelp />} />
        <Route path="/calcul" element={<NewRun />} />
        <Route path="/calculs" element={<History />} />
        <Route path="/calculs/:id" element={<RunDetail />} />
        <Route path="/production" element={<Production />} />
        <Route path="/production/:id" element={<ProductionDashboard />} />
        <Route path="/production/:id/saisie" element={<ProductionEntry />} />
        <Route path="/jumeau" element={<TwinHome />} />
        <Route path="/jumeau/:runId" element={<Twin />} />
        <Route path="/atelier/plan" element={<WorkshopPlan />} />
        <Route path="/atelier" element={<Account />} />
        <Route path="/admin" element={isSuperAdmin ? <Admin /> : <Navigate to="/" replace />} />
        <Route path="/nouvel-atelier" element={<Onboarding inLayout />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
}
