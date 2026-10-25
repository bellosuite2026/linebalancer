"""
Génération automatique de recommandations d'aide à la décision.

Analyse un BalancingResult (et optionnellement une ProductionTarget) et
produit une liste ordonnée de recommandations actionnables pour l'agent
de méthodes / le chef d'atelier : goulots, sous-charges, effectif,
qualité des données, faisabilité de la commande.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Any

from engine.models import BalancingResult

# Seuils métier confection
BOTTLENECK_LOAD_PCT = 95.0       # Poste saturé
UNDERLOADED_PCT = 70.0           # Poste sous-chargé
TARGET_LINE_EFFICIENCY = 85.0    # Bonne pratique atelier
HIGH_SMOOTHNESS_RATIO = 0.25     # SI > 25% du cycle => très déséquilibré

SEVERITY_ORDER = {"CRITIQUE": 0, "ATTENTION": 1, "INFO": 2}


@dataclass
class Recommendation:
    """Une recommandation actionnable."""
    severity: str       # CRITIQUE / ATTENTION / INFO
    category: str       # goulot / charge / effectif / qualité_données / faisabilité / solveur
    message: str
    action: str = ""

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "category": self.category,
            "message": self.message,
            "action": self.action,
        }

    def short(self) -> str:
        icons = {"CRITIQUE": "🔴", "ATTENTION": "🟠", "INFO": "🔵"}
        s = f"{icons.get(self.severity, '•')} [{self.category}] {self.message}"
        if self.action:
            s += f" → {self.action}"
        return s


def _longest_op(result: BalancingResult, op_ids: list[str]):
    """Retourne l'opération la plus longue d'une liste."""
    best = None
    for oid in op_ids:
        op = result.problem.get_operation(oid)
        if op and (best is None or op.duration > best.duration):
            best = op
    return best


def _check_solve_status(result: BalancingResult) -> list[Recommendation]:
    recs = []
    if not result.success:
        recs.append(Recommendation(
            "CRITIQUE", "solveur",
            f"Résolution échouée ({result.status}): {result.error_message or 'sans détail'}",
            "Augmenter le temps de cycle cible ou la limite de temps, "
            "puis vérifier problem.validate().",
        ))
    elif result.status not in ("OPTIMAL",):
        recs.append(Recommendation(
            "INFO", "solveur",
            f"Solution {result.status} (pas optimale garantie)",
            "Relancer en CP-SAT avec une limite de temps plus grande pour confirmer.",
        ))
    return recs


def _check_bottlenecks(result: BalancingResult) -> list[Recommendation]:
    recs = []
    details = result.station_details or []
    if not details:
        return recs
    max_load = max(sd.get("load_pct", 0) for sd in details)
    bottleneck = max(details, key=lambda sd: sd.get("load_pct", 0))
    for sd in details:
        load = sd.get("load_pct", 0)
        if load < BOTTLENECK_LOAD_PCT:
            continue
        op = _longest_op(result, sd.get("operations", []))
        is_main = sd is bottleneck
        title = "Goulot d'étranglement" if is_main else "Poste saturé"
        action = (
            f"déplacer l'opération '{op.id}' ({op.duration:.2f} min) vers un poste moins "
            f"chargé, ou la redécouper"
            if op and op.duration > result.problem.target_cycle_time * 0.3
            else "ajouter un poste en parallèle ou réduire les micro-arrêts"
        )
        recs.append(Recommendation(
            "CRITIQUE" if is_main else "ATTENTION", "goulot",
            f"{title}: station {sd['station']} chargée à {load:.0f}% "
            f"({sd.get('total_time', 0):.2f} min)",
            action,
        ))
    return recs


def _check_underload(result: BalancingResult) -> list[Recommendation]:
    recs = []
    details = result.station_details or []
    if not details:
        return recs
    under = [sd for sd in details if sd.get("load_pct", 100) < UNDERLOADED_PCT]
    for sd in under:
        idle = result.problem.target_cycle_time - sd.get("total_time", 0)
        recs.append(Recommendation(
            "INFO", "charge",
            f"Station {sd['station']} sous-chargée ({sd.get('load_pct', 0):.0f}%, "
            f"{idle:.2f} min perdues/pièce)",
            "lui affecter des opérations d'un poste saturé, ou des tâches NVA.",
        ))
    if len(details) >= 3 and len(under) / len(details) >= 0.25:
        recs.append(Recommendation(
            "ATTENTION", "effectif",
            f"{len(under)}/{len(details)} postes sous-chargés (< {UNDERLOADED_PCT:.0f}%)",
            f"retester avec {len(details) - 1} opérateurs (cycle plus long) — "
            "voir comparaison de scénarios.",
        ))
    return recs


def _check_kpis(result: BalancingResult) -> list[Recommendation]:
    recs = []
    if result.efficiency > 0 and result.efficiency < TARGET_LINE_EFFICIENCY:
        sev = "ATTENTION" if result.efficiency >= 70 else "CRITIQUE"
        recs.append(Recommendation(
            sev, "charge",
            f"Efficacité ligne {result.efficiency:.0f}% < cible {TARGET_LINE_EFFICIENCY:.0f}%",
            "réduire le nombre de postes ou allonger le cycle jusqu'à saturation.",
        ))
    cyc = result.problem.target_cycle_time
    if cyc > 0 and result.smoothness_index > HIGH_SMOOTHNESS_RATIO * cyc:
        recs.append(Recommendation(
            "INFO", "charge",
            f"Lissage faible (SI={result.smoothness_index:.2f}) — charges très hétérogènes",
            "objectif BALANCE_WORKLOAD ou réaffectations manuelles.",
        ))
    return recs


def _check_oversize_ops(result: BalancingResult) -> list[Recommendation]:
    recs = []
    cyc = result.problem.target_cycle_time
    if cyc <= 0:
        return recs
    for op in result.problem.operations:
        if op.duration > cyc:
            recs.append(Recommendation(
                "CRITIQUE", "qualité_données",
                f"Opération '{op.id}' ({op.duration:.2f} min) > temps de cycle ({cyc:.2f})",
                "découper l'opération, la dédoubler en postes parallèles, "
                "ou revoir le cycle cible.",
            ))
    return recs


def _check_data_quality(result: BalancingResult) -> list[Recommendation]:
    recs = []
    ops = result.problem.operations
    no_machine = [op.id for op in ops if not op.machine_type]
    no_skill = [op.id for op in ops if not op.required_skills]
    if no_machine:
        recs.append(Recommendation(
            "INFO", "qualité_données",
            f"{len(no_machine)} opérations sans type machine ({', '.join(no_machine[:4])}…)",
            "renseigner Type_Machine dans le fichier SAM pour fiabiliser l'affectation.",
        ))
    if no_skill:
        recs.append(Recommendation(
            "INFO", "qualité_données",
            f"{len(no_skill)} opérations sans compétence requise",
            "renseigner la colonne Compétences pour fiabiliser l'affectation ouvriers.",
        ))
    for warn in result.warnings or []:
        recs.append(Recommendation("ATTENTION", "qualité_données", warn))
    return recs


def _check_physical_resources(result: BalancingResult) -> list[Recommendation]:
    """La solution tient-elle dans le parc physique (postes, opérateurs) ?"""
    recs = []
    p = result.problem
    if not result.success or result.stations_used <= 0:
        return recs
    avail_ws = sum(1 for ws in p.workstations if ws.available)
    avail_workers = sum(1 for w in p.workers if w.available)
    if avail_ws and result.stations_used > avail_ws:
        recs.append(Recommendation(
            "CRITIQUE", "effectif",
            f"Solution à {result.stations_used} postes mais seulement {avail_ws} "
            "postes physiques disponibles",
            "ajouter des machines/postes, ou re-équilibrer avec un cycle plus long "
            "(moins de postes).",
        ))
    if avail_workers and result.stations_used > avail_workers:
        recs.append(Recommendation(
            "CRITIQUE", "effectif",
            f"Solution à {result.stations_used} postes mais seulement {avail_workers} "
            "opérateurs disponibles",
            "recruter/polyvalencier l'effectif ou re-équilibrer avec moins de postes.",
        ))
    unassigned_ws = [sd["station"] for sd in result.station_details or []
                     if not sd.get("workstation")]
    if unassigned_ws:
        recs.append(Recommendation(
            "ATTENTION", "effectif",
            f"Stations sans poste physique affecté: {', '.join(map(str, unassigned_ws))}",
            "vérifier la disponibilité des machines requises.",
        ))
    return recs


def _check_workforce(result: BalancingResult) -> list[Recommendation]:
    recs = []
    assigned = set()
    for sd in result.station_details or []:
        assigned.update(sd.get("worker_ids") or [])
    free = [w for w in result.problem.workers if w.available and w.id not in assigned]
    if len(free) >= 2:
        recs.append(Recommendation(
            "INFO", "effectif",
            f"{len(free)} opérateurs disponibles non affectés "
            f"({', '.join(w.name for w in free[:3])}…)",
            "constituer une réserve polyvalente (absences) ou réduire l'effectif.",
        ))
    return recs


def _check_target(result: BalancingResult, target: Any) -> list[Recommendation]:
    recs = []
    if target is None or target.takt_time <= 0:
        return recs
    if result.actual_cycle_time > target.required_cycle_time and result.success:
        over = result.actual_cycle_time - target.required_cycle_time
        recs.append(Recommendation(
            "CRITIQUE", "faisabilité",
            f"Cycle réel {result.actual_cycle_time:.2f} min > cycle planifiable "
            f"{target.required_cycle_time:.2f} min (dépassement {over:.2f})",
            f"passer à un cycle ≤ {target.required_cycle_time:.2f} min "
            f"(≈ {result.stations_used + 1}+ postes) ou rallonger le délai.",
        ))
    return recs


def generate_recommendations(
    result: BalancingResult,
    target: Optional[Any] = None,
) -> list[Recommendation]:
    """
    Produit la liste des recommandations, triées par sévérité
    (CRITIQUE → ATTENTION → INFO).
    """
    recs: list[Recommendation] = []
    recs += _check_solve_status(result)
    recs += _check_oversize_ops(result)
    recs += _check_physical_resources(result)
    recs += _check_bottlenecks(result)
    recs += _check_underload(result)
    recs += _check_kpis(result)
    recs += _check_target(result, target)
    recs += _check_workforce(result)
    recs += _check_data_quality(result)
    # CRITIQUE d'abord, ordre stable ensuite
    recs.sort(key=lambda r: SEVERITY_ORDER.get(r.severity, 3))
    return [r for r in recs if isinstance(r, Recommendation)]
