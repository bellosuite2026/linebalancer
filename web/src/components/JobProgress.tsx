// Barre de progression commune des calculs longs (optimiseur, simulation DES, Process Flow, convoyeur) :
// étapes (réveil du serveur, file d'attente, calcul, résultats), pourcentage, compteur, temps restant.
import { useEffect, useState } from "react";
import type { JobProgressInfo } from "../lib/des";

export type JobPhase = "wake" | "queued" | "running" | "done" | "failed";
type Kind = "opt" | "des" | "flow";

const STEPS: { key: JobPhase; label: string }[] = [
  { key: "wake", label: "Réveil du serveur" }, { key: "queued", label: "File d'attente" },
  { key: "running", label: "Calcul" }, { key: "done", label: "Résultats" },
];

const mmss = (s: number) => {
  const v = Math.max(0, Math.round(s));
  return v >= 60 ? `${Math.floor(v / 60)} min ${String(v % 60).padStart(2, "0")} s` : `${v} s`;
};

/** Déduit la phase : envoi en cours (serveur peut-être en veille) puis statut de la tâche. */
export function jobPhase(launching: boolean, status: string | undefined | null): JobPhase | null {
  if (launching) return "wake";
  if (status === "queued") return "queued";
  if (status === "running") return "running";
  return null;
}

export default function JobProgress({ phase, progress, kind, since, title, detail }: {
  phase: JobPhase; progress?: JobProgressInfo | null; kind: Kind; since: number; title?: string; detail?: string;
}) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(t); }, []);
  const waited = (now - since) / 1000;
  const p = progress ?? {};
  const inner = Math.max(0, Math.min(100, p.pct ?? 0));
  const pct = phase === "wake" ? Math.min(8, 1 + waited / 8) : phase === "queued" ? 10 : phase === "running" ? 10 + inner * 0.88 : 100;

  let count = "", remaining: number | null = null;
  if (phase === "running") {
    if (kind === "opt") {
      if (p.evals != null) count = `${p.evals} configurations testées${p.max_evals ? ` / ${p.max_evals} max` : ""}${p.gen ? ` · génération ${p.gen}` : ""}`;
      if (p.budget_s != null && p.elapsed_s != null) remaining = Math.max(0, p.budget_s - p.elapsed_s);
    } else if (p.total) {
      count = `${p.done ?? 0} / ${p.total} journées simulées (scénarios × réplications)`;
      if (p.done && p.elapsed_s) remaining = (p.elapsed_s / p.done) * (p.total - p.done);
    }
    if (remaining == null && inner > 3 && p.elapsed_s) remaining = (p.elapsed_s * (100 - inner)) / inner;
  }
  const slowWake = phase === "wake" && waited > 3;
  const msg = phase === "wake"
    ? (slowWake ? "Réveil du serveur (offre gratuite Render : environ 1 minute la première fois)…" : "Envoi au serveur…")
    : phase === "queued" ? "En file d'attente : le calcul démarre dès qu'un calculateur est libre."
    : phase === "running" ? (title ?? "Calcul en cours…") : "Terminé.";
  const cur = STEPS.findIndex((s) => s.key === phase);

  return (
    <div className="job-progress card" role="status" aria-live="polite">
      <div className="job-head">
        <b>{msg}</b>
        <span className="job-pct">{Math.round(pct)} %</span>
      </div>
      <div className="job-bar" aria-label="Progression" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100} role="progressbar">
        <i style={{ width: `${pct}%` }} className={phase === "wake" || phase === "queued" ? "pulse" : ""} />
      </div>
      <ol className="job-steps">
        {STEPS.map((s, i) => <li key={s.key} className={i < cur ? "done" : i === cur ? "on" : ""}>{i < cur ? "✓ " : ""}{s.label}</li>)}
      </ol>
      <p className="muted small">
        {count && <>{count} · </>}
        {phase === "wake" ? `attente ${mmss(waited)}` : p.elapsed_s != null ? `écoulé ${mmss(p.elapsed_s)}` : `depuis ${mmss(waited)}`}
        {remaining != null && <> · reste environ {mmss(remaining)}</>}
        {kind === "opt" && p.best_pieces ? <> · meilleur débit trouvé {Math.round(p.best_pieces)} pcs/j</> : null}
      </p>
      {detail && <p className="muted small">{detail}</p>}
      <p className="muted small">Vous pouvez quitter la page : le résultat sera dans l'historique.</p>
    </div>
  );
}

/** Écran de chargement qui explique le réveil du serveur gratuit après quelques secondes. */
export function Waking({ label }: { label: string }) {
  const [s, setS] = useState(0);
  useEffect(() => { const t = window.setInterval(() => setS((x) => x + 1), 1000); return () => window.clearInterval(t); }, []);
  return (
    <div className="page"><div className="card center-block">
      <div className="spinner" />
      <p>{label}</p>
      {s >= 4 && <p className="muted small">Le serveur se réveille (offre gratuite : environ 1 minute après une période d'inactivité)… {s} s</p>}
    </div></div>
  );
}
