import type { Run } from "../lib/types";

export default function StatusBadge({ run }: { run: Pick<Run, "status" | "compliant" | "success"> }) {
  if (run.status === "queued") return <span className="badge">En file</span>;
  if (run.status === "running") return <span className="badge info">En cours</span>;
  if (run.status === "failed") return <span className="badge err">Échec</span>;
  if (run.compliant) return <span className="badge ok">Conforme</span>;
  if (run.success) return <span className="badge warn">À vérifier</span>;
  return <span className="badge warn">Non conforme</span>;
}
