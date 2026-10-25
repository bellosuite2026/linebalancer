"""
Adaptateurs entre les deux couches de modèles :
  - v1 (engine.models)  : LineBalancingProblem / BalancingResult  -> solveurs
  - v2 (engine.models_v2): UnifiedProject (logique + implantation) -> GUI

Ces fonctions constituent le PONT unique entre la couche de résolution
(engine, sans GUI) et la couche projet unifiée (utilisée par les vues GUI).
"""
from __future__ import annotations

from typing import Optional

from engine.models import (
    LineBalancingProblem, BalancingResult,
    SolverAlgorithm, OptimizationObjective,
)
from engine.models_v2 import UnifiedProject, BuildingLayout


def unified_to_problem(
    project: UnifiedProject,
    cycle_time: float,
    max_stations: int,
    objective: str,
) -> Optional[LineBalancingProblem]:
    """Construit un LineBalancingProblem v1 à partir de la partie logique d'un UnifiedProject v2.

    Le UnifiedProject stocke le graphe logique sous forme de dictionnaires
    (logical_nodes / logical_edges). On le reformate en structure de workflow
    compatible avec engine.builders.build_problem_from_workflow.
    """
    from engine.builders import build_problem_from_workflow

    errors = project.validate()
    if errors:
        raise ValueError("Projet invalide: " + "; ".join(errors))

    workflow = {
        "nodes": project.logical_nodes,
        "edges": project.logical_edges,
    }
    return build_problem_from_workflow(workflow, cycle_time, max_stations, objective)


def problem_to_unified(
    problem: LineBalancingProblem,
    base: Optional[UnifiedProject] = None,
    name: str = "Projet depuis résolution",
) -> UnifiedProject:
    """Emballe un LineBalancingProblem (éventuellement résolu) dans un UnifiedProject.

    La partie implantation (building_layout) est préservée si `base` est fourni,
    sinon un BuildingLayout vide est créé.
    """
    if base is not None:
        project = base
        project.name = name or base.name
    else:
        project = UnifiedProject(name=name)

    # Reconstruit les nœuds logiques à partir du problème (opérations, postes, ouvriers)
    nodes = []
    for op in problem.operations:
        nodes.append({
            "id": f"op_{op.id}", "type": "operation", "enabled": True,
            "title": op.name, "subtitle": "Tâche de la gamme",
            "x": 100, "y": 100,
            "config": {
                "op_id": op.id, "name": op.name, "duration": op.duration,
                "predecessors": ";".join(op.predecessors),
                "machine_type": op.machine_type,
                "skills": ",".join(op.required_skills),
                "section": op.section,
                "task_type": getattr(op, "task_type", "VA"),
                "optional": getattr(op, "optional", False),
            },
        })
    for ws in problem.workstations:
        nodes.append({
            "id": f"ws_{ws.id}", "type": "workstation", "enabled": True,
            "title": ws.name, "subtitle": "Station physique",
            "x": 400, "y": 100,
            "config": {
                "ws_id": ws.id, "name": ws.name,
                "machine_type": ws.machine_type, "available": ws.available,
                "max_workers": ws.max_workers, "section": ws.section,
            },
        })
    for w in problem.workers:
        nodes.append({
            "id": f"worker_{w.id}", "type": "worker", "enabled": True,
            "title": w.name, "subtitle": "Ressource humaine",
            "x": 700, "y": 100,
            "config": {
                "worker_id": w.id, "name": w.name,
                "skills": ",".join(w.skills), "efficiency": w.efficiency,
                "available": w.available,
            },
        })

    edges = [[f"op_{pred}", f"op_{op.id}"] for op in problem.operations for pred in op.predecessors]

    project.logical_nodes = nodes
    project.logical_edges = edges
    return project


def building_layout_from_problem(
    problem: LineBalancingProblem,
    base: Optional[BuildingLayout] = None,
) -> BuildingLayout:
    """(Helper) Retourne un BuildingLayout, en préservant `base` si fourni."""
    return base if base is not None else BuildingLayout()
