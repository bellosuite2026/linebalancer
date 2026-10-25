import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { post } from "../lib/api";
import { supabase } from "../lib/supabase";
import { useSession } from "../lib/session";
import type { Org } from "../lib/types";

export default function Onboarding({ inLayout = false }: { inLayout?: boolean }) {
  const { refreshOrgs, setCurrentOrgId, session } = useSession();
  const nav = useNavigate();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const submit = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setErr("");
    try {
      const org = await post<Org>("/v1/orgs", { name, country: "TN" });
      setCurrentOrgId(org.id);
      await refreshOrgs();
      nav("/");
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };

  const form = (
    <form className="card narrow" onSubmit={submit}>
      <h2>{inLayout ? "Nouvel atelier" : "Bienvenue 👋"}</h2>
      <p className="muted">Créez votre atelier pour commencer. Votre essai gratuit de 30 jours démarre aussitôt.</p>
      <label>Nom de l'atelier<input required minLength={2} maxLength={120} placeholder="ex. Confection Sahel – Ksar Hellal"
        value={name} onChange={(e) => setName(e.target.value)} /></label>
      {err && <p className="notice err">{err}</p>}
      <button className="btn primary full" disabled={busy}>{busy ? "Création…" : "Créer l'atelier"}</button>
      {!inLayout && <p className="muted small">Connecté en tant que {session?.user.email} · <button type="button" className="link" onClick={() => supabase.auth.signOut()}>Se déconnecter</button></p>}
    </form>
  );
  return inLayout ? <div className="page">{form}</div> : <div className="center">{form}</div>;
}
