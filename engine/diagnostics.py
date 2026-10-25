"""
Diagnostics de faisabilité et validation de résultats d'équilibrage.

- `precheck(problem)` : détecte AVANT résolution les causes classiques
  d'infaisabilité et propose une action corrective.
- `parallel_replicas(op, cycle)` : nombre de postes en parallèle nécessaires
  pour une opération plus longue que le temps de cycle (dédoublement).
- `validate_result(problem, result)` : contrôle APRÈS résolution qu'une
  solution respecte réellement les contraintes (cycle, postes, ouvriers).
- `line_kpis(...)` : KPIs cohérents (efficacité calculée sur le cycle réel
  et le nombre réel d'opérateurs, postes parallèles compris).
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict

from engine.models import LineBalancingProblem, Operation

EPS = 1e-6


@dataclass
class Issue:
    code: str
    severity: str  # "error" | "warning"
    message: str
    suggestion: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def __str__(self) -> str:
        s = f"[{self.code}] {self.message}"
        return f"{s} → {self.suggestion}" if self.suggestion else s


def parallel_replicas(op: Operation, cycle: float) -> int:
    """Nombre de postes parallèles requis pour tenir le cycle (>= 1)."""
    if cycle <= 0:
        return 1
    return max(1, math.ceil(op.duration / cycle - EPS))


def precheck(problem: LineBalancingProblem, allow_parallel: bool = True) -> list[Issue]:
    issues: list[Issue] = []
    C = problem.target_cycle_time
    ops = problem.operations
    if C <= 0:
        return [Issue("CYCLE_INVALID", "error", "Le temps de cycle cible doit être > 0.")]
    ids = {o.id for o in ops}

    for o in ops:
        for p in o.predecessors:
            if p not in ids:
                issues.append(Issue("PRED_UNKNOWN", "error",
                                    f"{o.id} référence un prédécesseur inconnu « {p} ».",
                                    "Corriger la colonne Predecesseurs du fichier SAM."))

    long_ops = [o for o in ops if o.duration > C + EPS]
    for o in long_ops:
        n = parallel_replicas(o, C)
        if allow_parallel:
            issues.append(Issue("OP_GT_CYCLE", "warning",
                                f"{o.id} ({o.duration:.2f} min) dépasse le cycle {C:.2f} min.",
                                f"Dédoublement automatique sur {n} postes parallèles."))
        else:
            issues.append(Issue("OP_GT_CYCLE", "error",
                                f"{o.id} ({o.duration:.2f} min) dépasse le cycle {C:.2f} min.",
                                f"Autoriser {n} postes en parallèle ou passer le cycle à ≥ {o.duration:.2f} min."))

    avail_ws = [w for w in problem.workstations if w.available]
    ws_count = Counter(w.machine_type for w in avail_ws)
    if avail_ws:
        load = defaultdict(float)
        need = defaultdict(int)
        for o in ops:
            if o.machine_type:
                load[o.machine_type] += o.duration
                need[o.machine_type] = max(need[o.machine_type], parallel_replicas(o, C))
        for m, total in load.items():
            have = ws_count.get(m, 0)
            mini = max(math.ceil(total / C - EPS), need[m])
            if have == 0:
                issues.append(Issue("MACHINE_MISSING", "error",
                                    f"Aucun poste « {m} » disponible ({total:.2f} min de travail).",
                                    f"Ajouter au moins {mini} poste(s) {m}."))
            elif have < mini:
                issues.append(Issue("MACHINE_CAPACITY", "error",
                                    f"{total:.2f} min sur « {m} » demandent ≥ {mini} poste(s) au cycle {C:.2f} ; {have} disponible(s).",
                                    f"Ajouter {mini - have} poste(s) {m} ou allonger le cycle à ≥ {total / have:.2f} min."))

    avail_workers = [w for w in problem.workers if w.available]
    if avail_workers:
        for o in ops:
            if o.required_skills and not any(set(o.required_skills) <= set(w.skills) for w in avail_workers):
                issues.append(Issue("SKILL_MISSING", "error",
                                    f"Aucun ouvrier ne maîtrise {', '.join(o.required_skills)} ({o.id}).",
                                    "Former un ouvrier ou corriger les compétences requises."))
        total = sum(o.duration for o in ops)
        mini = math.ceil(total / C - EPS)
        if len(avail_workers) < mini:
            issues.append(Issue("WORKERS_SHORT", "error",
                                f"{total:.2f} min de travail exigent ≥ {mini} opérateurs au cycle {C:.2f} ; {len(avail_workers)} disponibles.",
                                f"Allonger le cycle à ≥ {total / len(avail_workers):.2f} min ou renforcer l'effectif."))
    return issues


def line_kpis(problem: LineBalancingProblem, station_details: list[dict]) -> dict:
    """KPIs cohérents. `total_time` d'une station = temps par pièce et par poste
    (déjà divisé par le nombre de postes parallèles)."""
    C = problem.target_cycle_time
    total_work = sum(o.duration for o in problem.operations)
    operators = sum(int(sd.get("parallel", 1)) for sd in station_details)
    actual = max((sd["total_time"] for sd in station_details), default=0.0)
    eff_cycle = max(C, actual)
    eff = total_work / (operators * eff_cycle) * 100 if operators and eff_cycle > 0 else 0.0
    smooth = math.sqrt(sum((actual - sd["total_time"]) ** 2 for sd in station_details)) if station_details else 0.0
    return {
        "operators": operators,
        "actual_cycle_time": round(actual, 3),
        "efficiency": round(eff, 1),
        "balance_delay": round(100 - eff, 1) if eff > 0 else 100.0,
        "smoothness_index": round(smooth, 2),
    }


def validate_result(problem: LineBalancingProblem, station_details: list[dict]) -> list[Issue]:
    C = problem.target_cycle_time
    out: list[Issue] = []
    for sd in station_details:
        if sd["total_time"] > C + EPS:
            out.append(Issue("CYCLE_EXCEEDED", "error",
                             f"Station {sd['station']} : {sd['total_time']:.2f} min > cycle {C:.2f} min."))
    if problem.workstations:
        for sd in station_details:
            if not sd.get("workstation") and not sd.get("workstations"):
                out.append(Issue("NO_WORKSTATION", "error",
                                 f"Station {sd['station']} : aucun poste physique compatible disponible."))
    if problem.workers:
        for sd in station_details:
            need_skill = any(problem_op(problem, o).required_skills for o in sd["operations"])
            if need_skill and len(sd.get("worker_ids", sd.get("workers", []))) < int(sd.get("parallel", 1)):
                out.append(Issue("NO_WORKER", "error",
                                 f"Station {sd['station']} : ouvrier(s) qualifié(s) manquant(s)."))
    return out


def problem_op(problem: LineBalancingProblem, op_id: str) -> Operation:
    for o in problem.operations:
        if o.id == op_id:
            return o
    raise KeyError(op_id)
