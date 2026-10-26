"""Schémas Pydantic de l'API (miroir des dataclasses de engine.models)."""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class OperationIn(BaseModel):
    id: str
    name: str = ""
    duration: float = Field(ge=0, description="Temps standard SAM (min)")
    predecessors: list[str] = []
    machine_type: str = ""
    required_skills: list[str] = []
    section: str = ""
    optional: bool = False
    task_type: str = "VA"


class WorkstationIn(BaseModel):
    id: str
    name: str = ""
    machine_type: str = ""
    available: bool = True
    max_workers: int = Field(default=1, ge=1)
    section: str = ""


class WorkerIn(BaseModel):
    id: str
    name: str = ""
    skills: list[str] = []
    efficiency: float = Field(default=1.0, gt=0)
    assigned_station: Optional[str] = None
    available: bool = True
    skill_levels: dict[str, float] = Field(default_factory=dict,
                                           description="Matrice de polyvalence : rendement par compétence (ex. 0.85)")


class ProblemIn(BaseModel):
    name: str = "ligne"
    target_cycle_time: float = Field(gt=0, description="Cadence cible (min/pièce)")
    operations: list[OperationIn] = Field(min_length=1)
    workstations: list[WorkstationIn] = []
    workers: list[WorkerIn] = []
    max_stations: Optional[int] = Field(default=None, ge=1)
    forced_assignments: dict[str, int] = {}
    forbidden_assignments: dict[str, list[int]] = {}
    same_station_groups: list[list[str]] = []
    max_machines_per_station: int = Field(default=3, ge=1, le=10,
                                          description="Machines voisines qu'un ouvrier peut tenir (1 = une machine par poste)")
    machine_change_time: float = Field(default=0.0, ge=0, description="Min/pièce ajoutées par machine supplémentaire (déplacement)")
    section_policy: str = Field(default="prefer", pattern="^(prefer|strict)$")
    split_mode: str = Field(default="share", pattern="^(share|parallel)$",
                            description="Opération > cadence : share = parts + reliquat combinable ; parallel = postes égaux")


class SolverName(str, Enum):
    rpw = "rpw"
    cp_sat = "cp_sat"


class BalanceRequest(BaseModel):
    problem: ProblemIn
    solver: SolverName = SolverName.rpw
    time_limit_seconds: int = Field(default=10, ge=1, description="CP-SAT uniquement")


class MinCycleRequest(BaseModel):
    problem: ProblemIn
    solver: SolverName = SolverName.rpw
    precision: float = Field(default=0.05, gt=0, le=1)
    time_limit_seconds: int = Field(default=5, ge=1, description="CP-SAT, par itération")


class IssueOut(BaseModel):
    code: str
    severity: str
    message: str
    suggestion: str = ""


class PrecheckOut(BaseModel):
    feasible: bool = Field(description="Aucune erreur bloquante détectée")
    issues: list[IssueOut]
    validation_errors: list[str] = Field(description="Contrôles de cohérence de LineBalancingProblem.validate()")


class ResultOut(BaseModel):
    success: bool
    compliant: bool = Field(description="success ET aucune violation détectée par validate_result")
    status: str
    solver: str
    solve_time_seconds: float
    target_cycle_time: float
    stations_used: int
    actual_cycle_time: float
    efficiency: float
    balance_delay: float
    smoothness_index: float
    operators: int
    station_details: list[dict[str, Any]]
    operation_assignments: dict[str, int]
    worker_assignments: dict[str, str]
    warnings: list[str]
    error_message: str = ""
    violations: list[IssueOut] = []


class MinCycleOut(BaseModel):
    found: bool
    min_cycle_time: Optional[float]
    result: Optional[ResultOut]


class ImportOut(BaseModel):
    problem: ProblemIn
    precheck: PrecheckOut


class JobKind(str, Enum):
    balance = "balance"
    min_cycle = "min_cycle"


class JobRequest(BaseModel):
    kind: JobKind
    balance: Optional[BalanceRequest] = None
    min_cycle: Optional[MinCycleRequest] = None


class JobOut(BaseModel):
    id: str
    kind: JobKind
    status: str  # queued | running | done | failed
    created_at: float
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    result: Optional[dict[str, Any]] = None
    error: str = ""


# ---------------------------------------------------------------- Comptes / ateliers (Supabase)
class OrgCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    country: str = Field(default="TN", min_length=2, max_length=2)


class LineCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    product: str = ""
    target_cycle_time: Optional[float] = Field(default=None, gt=0)


class ProblemSave(BaseModel):
    problem: ProblemIn
    line_id: Optional[str] = None


class RunCreate(BaseModel):
    """Lance un calcul enregistré dans l'historique de l'atelier.

    Fournir soit `problem_id` (gamme déjà enregistrée), soit `problem` (gamme
    complète, enregistrée automatiquement si `save_problem`)."""
    kind: JobKind = JobKind.balance
    solver: SolverName = SolverName.rpw
    problem_id: Optional[str] = None
    problem: Optional[ProblemIn] = None
    line_id: Optional[str] = None
    save_problem: bool = True
    time_limit_seconds: int = Field(default=10, ge=1)
    precision: float = Field(default=0.05, gt=0, le=1, description="min_cycle uniquement")
