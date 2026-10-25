import { useState, type FormEvent } from "react";
import { supabase } from "../lib/supabase";
import { useSession } from "../lib/session";

export default function NewPassword() {
  const { clearRecovery } = useSession();
  const [pwd, setPwd] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setBusy(true); setErr("");
    const { error } = await supabase.auth.updateUser({ password: pwd });
    setBusy(false);
    if (error) setErr(error.message); else clearRecovery();
  };
  return (
    <div className="center">
      <form className="card narrow" onSubmit={submit}>
        <h2>Nouveau mot de passe</h2>
        <label>Mot de passe<input type="password" minLength={8} required value={pwd} onChange={(e) => setPwd(e.target.value)} /></label>
        {err && <p className="notice err">{err}</p>}
        <button className="btn primary full" disabled={busy}>Enregistrer</button>
      </form>
    </div>
  );
}
