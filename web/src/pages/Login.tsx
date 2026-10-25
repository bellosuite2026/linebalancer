import { useState, type FormEvent } from "react";
import { supabase } from "../lib/supabase";

type Mode = "login" | "signup" | "reset";

export default function Login() {
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true); setMsg(null);
    const redirect = window.location.origin;
    try {
      if (mode === "login") {
        const { error } = await supabase.auth.signInWithPassword({ email, password });
        if (error) throw error;
      } else if (mode === "signup") {
        const { data, error } = await supabase.auth.signUp({ email, password, options: { emailRedirectTo: redirect } });
        if (error) throw error;
        if (!data.session) setMsg({ kind: "ok", text: "Compte créé. Ouvrez l'e-mail de confirmation pour l'activer, puis connectez-vous." });
      } else {
        const { error } = await supabase.auth.resetPasswordForEmail(email, { redirectTo: redirect });
        if (error) throw error;
        setMsg({ kind: "ok", text: "Si ce compte existe, un lien de réinitialisation vient d'être envoyé." });
      }
    } catch (err) {
      setMsg({ kind: "err", text: translate((err as Error).message) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth">
      <section className="auth-pitch">
        <div className="brand big"><span className="logo" />Textile Line Balancer</div>
        <h1>Équilibrez vos lignes de confection en quelques minutes.</h1>
        <ul>
          <li>Importez votre gamme SAM, vos postes et vos ouvriers (Excel ou CSV)</li>
          <li>Diagnostic de faisabilité avant calcul</li>
          <li>Répartition optimale des opérations, charge par poste, rendement</li>
          <li>Cadence minimale atteignable avec vos moyens</li>
        </ul>
        <p className="muted">Essai gratuit 30 jours, sans carte bancaire.</p>
      </section>
      <section className="auth-form card">
        <h2>{mode === "login" ? "Connexion" : mode === "signup" ? "Créer un compte" : "Mot de passe oublié"}</h2>
        <form onSubmit={submit}>
          <label>E-mail<input type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} /></label>
          {mode !== "reset" && (
            <label>Mot de passe
              <input type="password" required minLength={8} autoComplete={mode === "login" ? "current-password" : "new-password"}
                value={password} onChange={(e) => setPassword(e.target.value)} />
            </label>
          )}
          {msg && <p className={msg.kind === "ok" ? "notice ok" : "notice err"}>{msg.text}</p>}
          <button className="btn primary full" disabled={busy}>
            {busy ? "Patientez…" : mode === "login" ? "Se connecter" : mode === "signup" ? "Créer mon compte" : "Envoyer le lien"}
          </button>
        </form>
        <div className="auth-links">
          {mode !== "login" && <button className="link" onClick={() => { setMode("login"); setMsg(null); }}>J'ai déjà un compte</button>}
          {mode !== "signup" && <button className="link" onClick={() => { setMode("signup"); setMsg(null); }}>Créer un compte</button>}
          {mode !== "reset" && <button className="link" onClick={() => { setMode("reset"); setMsg(null); }}>Mot de passe oublié ?</button>}
        </div>
      </section>
    </div>
  );
}

function translate(m: string) {
  if (/Invalid login credentials/i.test(m)) return "E-mail ou mot de passe incorrect.";
  if (/Email not confirmed/i.test(m)) return "E-mail pas encore confirmé : ouvrez le lien reçu par e-mail.";
  if (/already registered/i.test(m)) return "Un compte existe déjà avec cet e-mail.";
  if (/at least/i.test(m) && /password/i.test(m)) return "Mot de passe trop court (8 caractères minimum).";
  if (/rate limit/i.test(m)) return "Trop de tentatives, réessayez dans quelques minutes.";
  return m;
}
