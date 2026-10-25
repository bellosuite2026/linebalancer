"""
Construction du LineBalancingProblem à partir d'un workflow de nœuds (Vue Logique).

Source unique de vérité pour la conversion graphe -> modèle de résolution.
(Anciennement dupliqué dans gui/shared.py et gui/main.py.)
"""
from __future__ import annotations

from typing import Optional

from engine.models import (
    Operation, Workstation, Worker, LineBalancingProblem,
    SolverAlgorithm, OptimizationObjective,
)


def _split(value: str | list, sep: str) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [v.strip() for v in value.split(sep) if v.strip()] if value else []


def build_problem_from_workflow(
    project_data: dict,
    cycle_time: float,
    max_stations: int,
    objective: str,
) -> Optional[LineBalancingProblem]:
    """Construit un LineBalancingProblem depuis le workflow de nœuds de la Vue Logique."""
    operations: list[Operation] = []
    workstations: list[Workstation] = []
    workers: list[Worker] = []

    for node in project_data.get("nodes", []):
        if not node.get("enabled", True):
            continue
        cfg = node.get("config", {})
        ntype = node["type"]

        if ntype == "operation":
            try:
                duration = float(cfg.get("duration", 0))
            except (TypeError, ValueError):
                duration = 0.0
            task_type = cfg.get("task_type", "VA")
            optional = str(cfg.get("optional", "False")).strip().lower() in ("1", "true", "oui", "yes", "x")
            operations.append(Operation(
                id=cfg.get("op_id", node["id"]),
                name=cfg.get("name", node["id"]),
                duration=duration,
                predecessors=_split(cfg.get("predecessors", ""), ";"),
                machine_type=cfg.get("machine_type", ""),
                required_skills=_split(cfg.get("skills", ""), ","),
                section=cfg.get("section", ""),
                task_type=task_type,
                optional=optional,
            ))

        elif ntype == "workstation":
            workstations.append(Workstation(
                id=cfg.get("ws_id", node["id"]),
                name=cfg.get("name", node["id"]),
                machine_type=cfg.get("machine_type", ""),
                available=cfg.get("available", True),
                max_workers=int(cfg.get("max_workers", 1)),
                section=cfg.get("section", ""),
            ))

        elif ntype == "worker":
            workers.append(Worker(
                id=cfg.get("worker_id", node["id"]),
                name=cfg.get("name", node["id"]),
                skills=_split(cfg.get("skills", ""), ","),
                efficiency=float(cfg.get("efficiency", 1.0)),
                available=cfg.get("available", True),
            ))

    if not operations:
        return None

    obj_map = {
        "min_stations": OptimizationObjective.MIN_STATIONS,
        "min_cycle_time": OptimizationObjective.MIN_CYCLE_TIME,
        "max_efficiency": OptimizationObjective.MAX_EFFICIENCY,
        "balance_workload": OptimizationObjective.BALANCE_WORKLOAD,
    }

    return LineBalancingProblem(
        name="Projet GUI",
        target_cycle_time=cycle_time,
        operations=operations,
        workstations=workstations,
        workers=workers,
        max_stations=max_stations if max_stations > 0 else None,
        algorithm=SolverAlgorithm.CP_SAT,
        objective=obj_map.get(objective, OptimizationObjective.MIN_STATIONS),
    )
