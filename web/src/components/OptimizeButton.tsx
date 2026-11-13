// Bouton « Optimiser » commun : visible partout où un calcul peut être optimisé (détail du calcul,
// historique, simulation 3D). Désactivé avec l'explication quand le calcul n'a pas de solution.
import { Link } from "react-router-dom";
import type { Run } from "../lib/types";

/** Raison pour laquelle le calcul ne peut pas être optimisé (null = possible). */
export function optimizeBlocker(run: Pick<Run, "status" | "stations_used" | "kind"> | null | undefined): string | null {
  if (!run) return "Choisissez d'abord un calcul.";
  if (run.status === "queued" || run.status === "running") return "Le calcul est encore en cours : attendez sa fin pour l'optimiser.";
  if (run.status === "failed") return "Ce calcul a échoué : il n'a pas de solution à optimiser. Relancez le calcul.";
  if (!run.stations_used) return "Ce calcul n'a pas de solution (aucune répartition en postes) : vérifiez la gamme, la cadence et l'effectif, puis relancez-le.";
  return null;
}

export default function OptimizeButton({ run, runId, writable, planId, size = "", showWhy = true }: {
  run?: Pick<Run, "status" | "stations_used" | "kind"> | null; runId: string; writable: boolean; planId?: string;
  size?: "" | "small" | "big"; showWhy?: boolean;
}) {
  const why = run === undefined ? null : optimizeBlocker(run);
  const to = `/optimiseur/${runId}${planId ? `?plan=${planId}` : ""}`;
  const cls = `btn optimize ${size}`;
  const title = why ?? (writable ? "Chercher automatiquement de meilleurs réglages (effectifs, paquets, encours, agents de liaison, placement) par simulation"
    : "Lecture seule : vous pouvez consulter les optimisations déjà faites, pas en lancer");
  return (
    <span className="opt-btn-wrap">
      {why ? <button className={cls} disabled title={why} aria-disabled>⚡ Optimiser</button>
        : <Link className={cls} to={to} title={title}>⚡ Optimiser</Link>}
      {showWhy && why && <small className="why">{why}</small>}
      {showWhy && !why && !writable && <small className="why">Lecture seule : vous pourrez consulter les résultats, pas lancer l'optimisation (rôle « lecteur »).</small>}
    </span>
  );
}
