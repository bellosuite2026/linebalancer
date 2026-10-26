"""Conversion schémas API <-> modèles moteur, et appels au moteur.

Toute la logique métier reste dans `engine/` ; ce module ne fait qu'adapter.
"""
from __future__ import annotations

import math
import tempfile
from pathlib import Path
from typing import Any

from engine.diagnostics import line_kpis, precheck, validate_result
from engine.models import LineBalancingProblem, Operation, Worker, Workstation, BalancingResult
from engine.parsers import parse_sam_file, parse_workers_file, parse_workstations_file
from engine.solvers import find_min_cycle, registry

from api.schemas import (
    BalanceRequest, IssueOut, MinCycleOut, MinCycleRequest, OperationIn, PrecheckOut,
    ProblemIn, ResultOut, WorkerIn, WorkstationIn,
)

SUPPORTED_SUFFIXES = {".csv", ".xlsx", ".json"}


# --- Problème ---------------------------------------------------------------

def to_engine_problem(p: ProblemIn) -> LineBalancingProblem:
    """Construit un LineBalancingProblem neuf (jamais partagé entre requêtes)."""
    return LineBalancingProblem(
        name=p.name,
        target_cycle_time=p.target_cycle_time,
        operations=[Operation(**o.model_dump()) for o in p.operations],
        workstations=[Workstation(**w.model_dump()) for w in p.workstations],
        workers=[Worker(**w.model_dump()) for w in p.workers],
        max_stations=p.max_stations,
        forced_assignments=dict(p.forced_assignments),
        forbidden_assignments={k: list(v) for k, v in p.forbidden_assignments.items()},
        same_station_groups=[list(g) for g in p.same_station_groups],
        max_machines_per_station=p.max_machines_per_station,
        machine_change_time=p.machine_change_time,
        section_policy=p.section_policy,
        split_mode=p.split_mode,
    )


def operations_out(ops: list[Operation]) -> list[OperationIn]:
    return [OperationIn(id=o.id, name=o.name, duration=o.duration, predecessors=o.predecessors,
                        machine_type=o.machine_type, required_skills=o.required_skills,
                        section=o.section, optional=o.optional, task_type=o.task_type) for o in ops]


def workstations_out(wss: list[Workstation]) -> list[WorkstationIn]:
    return [WorkstationIn(id=w.id, name=w.name, machine_type=w.machine_type, available=w.available,
                          max_workers=w.max_workers, section=w.section) for w in wss]


def workers_out(ws: list[Worker]) -> list[WorkerIn]:
    return [WorkerIn(id=w.id, name=w.name, skills=w.skills, efficiency=w.efficiency,
                     assigned_station=w.assigned_station, available=w.available,
                     skill_levels=dict(w.skill_levels or {})) for w in ws]


# --- Import de fichiers -----------------------------------------------------

def parse_upload(kind: str, filename: str, content: bytes) -> list:
    """Écrit l'upload dans un fichier temporaire puis délègue aux parseurs moteur."""
    suffix = Path(filename or "").suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(f"Format non supporté « {suffix or '?'} ». Utilisez .csv, .xlsx ou .json")
    parser = {"sam": parse_sam_file, "workstations": parse_workstations_file,
              "workers": parse_workers_file}[kind]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / f"upload{suffix}"
        path.write_bytes(content)
        items = parser(path)
    if kind == "sam" and not items:
        raise ValueError("Aucune opération lue dans le fichier SAM.")
    return items


# --- Diagnostic -------------------------------------------------------------

def issue_out(i) -> IssueOut:
    return IssueOut(**i.to_dict())


def run_precheck(p: ProblemIn) -> PrecheckOut:
    prob = to_engine_problem(p)
    issues = precheck(prob)
    errors = prob.validate()
    feasible = not any(i.severity == "error" for i in issues) and not any(
        "prédécesseur inconnu" in e or "Cycle détecté" in e for e in errors)
    return PrecheckOut(feasible=feasible, issues=[issue_out(i) for i in issues], validation_errors=errors)


# --- Résultats --------------------------------------------------------------

def _clean(v: Any) -> Any:
    """Rend une valeur sérialisable JSON (nan/inf -> None, objets -> str)."""
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, (str, int, bool)) or v is None:
        return v
    if isinstance(v, dict):
        return {str(k): _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [_clean(x) for x in v]
    return str(v)


def result_out(prob: LineBalancingProblem, r: BalancingResult) -> ResultOut:
    details = _clean(r.station_details)
    kpis = line_kpis(prob, r.station_details) if r.station_details else {"operators": 0}
    violations = validate_result(prob, r.station_details) if r.station_details else []
    return ResultOut(
        success=r.success,
        compliant=bool(r.success and not violations),
        status=r.status,
        solver=r.solver_used,
        solve_time_seconds=round(r.solve_time_seconds, 4),
        target_cycle_time=prob.target_cycle_time,
        stations_used=r.stations_used,
        actual_cycle_time=r.actual_cycle_time,
        efficiency=r.efficiency,
        balance_delay=r.balance_delay,
        smoothness_index=r.smoothness_index,
        operators=int(kpis.get("operators", 0)),
        station_details=details,
        operation_assignments={str(k): int(v) for k, v in r.operation_assignments.items()},
        worker_assignments={str(k): str(v) for k, v in r.worker_assignments.items()},
        warnings=[str(w) for w in r.warnings],
        error_message=r.error_message or "",
        violations=[issue_out(i) for i in violations],
    )


def _solver_options(solver: str, time_limit: int, max_stations) -> dict:
    if solver == "cp_sat":
        return {"time_limit_seconds": time_limit}
    return {"max_stations": max_stations} if max_stations else {}


def run_balance(req: BalanceRequest, time_cap: int) -> ResultOut:
    solver = req.solver.value
    if not registry.is_available(solver):
        raise RuntimeError(f"Solveur « {solver} » indisponible sur ce serveur.")
    prob = to_engine_problem(req.problem)
    opts = _solver_options(solver, min(req.time_limit_seconds, time_cap), req.problem.max_stations)
    r = registry.solve(solver, prob, **opts)
    return result_out(prob, r)


def run_min_cycle(req: MinCycleRequest, time_cap: int) -> MinCycleOut:
    solver = req.solver.value
    if not registry.is_available(solver):
        raise RuntimeError(f"Solveur « {solver} » indisponible sur ce serveur.")
    prob = to_engine_problem(req.problem)
    opts = _solver_options(solver, min(req.time_limit_seconds, time_cap), None)
    cycle, r = find_min_cycle(prob, solver=solver, precision=req.precision, **opts)
    if cycle is None or r is None:
        return MinCycleOut(found=False, min_cycle_time=None, result=None)
    return MinCycleOut(found=True, min_cycle_time=cycle, result=result_out(r.problem, r))
