"""Schémas Pydantic de l'API (miroir des dataclasses de engine.models)."""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


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


# ---------------------------------------------------------------- Suivi de production (tablette)
DowntimeReason = Literal["panne", "manque_fourniture", "absence", "changement_modele", "autre"]


class SessionCreate(BaseModel):
    """Ouvre une session de production à partir d'un calcul d'équilibrage terminé."""
    run_id: str
    line_id: Optional[str] = None
    model: str = Field(default="", max_length=120)
    session_date: Optional[date] = None
    shift_start: str = Field(default="08:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    shift_hours: float = Field(default=8, gt=0, le=24)
    target_per_hour: Optional[float] = Field(default=None, gt=0, le=100000,
                                             description="Par défaut : 60 / cycle réel du calcul")
    timezone: str = Field(default="Africa/Tunis", max_length=64)


class SessionUpdate(BaseModel):
    status: Optional[Literal["open", "closed"]] = None
    target_per_hour: Optional[float] = Field(default=None, gt=0, le=100000)
    shift_start: Optional[str] = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    shift_hours: Optional[float] = Field(default=None, gt=0, le=24)
    model: Optional[str] = Field(default=None, max_length=120)


class EntryIn(BaseModel):
    client_id: Optional[UUID] = Field(default=None, description="Identifiant généré par la tablette (idempotence)")
    station: int = Field(ge=1)
    slot_hour: Optional[int] = Field(default=None, ge=0, le=23, description="Heure locale ; déduite de entered_at sinon")
    worker_id: Optional[str] = Field(default=None, max_length=64)
    pieces: int = Field(default=0, ge=0, le=10000)
    defects: int = Field(default=0, ge=0, le=10000)
    rework: int = Field(default=0, ge=0, le=10000)
    downtime_reason: Optional[DowntimeReason] = None
    downtime_start: Optional[datetime] = None
    downtime_minutes: Optional[float] = Field(default=None, ge=0, le=1440)
    comment: str = Field(default="", max_length=500)
    voided: bool = False
    entered_at: Optional[datetime] = None


class EntriesBatch(BaseModel):
    entries: list[EntryIn] = Field(min_length=1, max_length=500)


class EntryPatch(BaseModel):
    pieces: Optional[int] = Field(default=None, ge=0, le=10000)
    defects: Optional[int] = Field(default=None, ge=0, le=10000)
    rework: Optional[int] = Field(default=None, ge=0, le=10000)
    downtime_reason: Optional[DowntimeReason] = None
    downtime_minutes: Optional[float] = Field(default=None, ge=0, le=1440)
    comment: Optional[str] = Field(default=None, max_length=500)
    voided: Optional[bool] = None
    station: Optional[int] = Field(default=None, ge=1)
    slot_hour: Optional[int] = Field(default=None, ge=0, le=23)


# ------------------------------------------------------------------ jumeau numérique
class Point(BaseModel):
    x: float = Field(ge=-500, le=500, description="mètres")
    y: float = Field(ge=-500, le=500, description="mètres")


class LayoutIn(BaseModel):
    """Implantation 2D : positions des stations (mètres), ligne droite, cellule en U ou libre."""
    kind: Literal["line", "u", "free"] = "line"
    positions: dict[str, Point] = Field(default_factory=dict, max_length=300)
    plan_id: Optional[str] = Field(default=None, description="Plan d'atelier : stations placées sur ses machines")
    assignment: dict[str, list[str]] = Field(default_factory=dict, max_length=300,
                                             description="Station -> identifiants des machines du plan")


class Breakdown(BaseModel):
    station: int = Field(ge=1)
    start_min: float = Field(default=60, ge=0, le=1440, description="minutes après le début du poste")
    duration_min: float = Field(default=30, gt=0, le=1440)


class TwinScenario(BaseModel):
    """Scénario « et si » d'une journée simulée."""
    name: str = Field(default="Scénario", max_length=60)
    run_id: Optional[str] = Field(default=None, description="Autre calcul (nouveau modèle / gamme)")
    absent: list[str] = Field(default_factory=list, max_length=100, description="Identifiants d'ouvrières absentes")
    reassign: bool = Field(default=True, description="Réaffecter selon les compétences si un poste se vide")
    operators: dict[str, int] = Field(default_factory=dict, description="Effectif imposé par station")
    breakdowns: list[Breakdown] = Field(default_factory=list, max_length=20)
    bundle_size: int = Field(default=10, ge=1, le=100, description="Pièces par paquet")
    efficiency_pct: float = Field(default=100, ge=10, le=200, description="Efficience de la ligne (%)")
    variability_pct: float = Field(default=10, ge=0, le=60, description="Variabilité des temps (CV, %)")
    shift_minutes: float = Field(default=480, ge=30, le=600, description="Durée simulée (max 10 h)")
    seed: int = Field(default=42, ge=0, le=10**6)


class SimulateRequest(BaseModel):
    name: str = Field(default="", max_length=120)
    scenarios: list[TwinScenario] = Field(min_length=1, max_length=3)
    layout: Optional[LayoutIn] = Field(default=None, description="Par défaut : implantation enregistrée")


# ------------------------------------------------------------------ plan d'atelier (cartographie)
PLAN_ELEMENT_KINDS = {"wall", "pillar", "door", "aisle", "zone", "machine", "text", "dim", "rail"}


class WorkshopPlanIn(BaseModel):
    """Plan d'atelier : salle (m), fond importé et calibré, éléments dessinés (coordonnées en mètres)."""
    name: str = Field(default="Plan de l'atelier", min_length=1, max_length=120)
    version: Literal["actuel", "projet", "archive"] = "actuel"
    width_m: float = Field(default=30, ge=2, le=400)
    length_m: float = Field(default=20, ge=2, le=400)
    background: Optional[dict[str, Any]] = None
    elements: list[dict[str, Any]] = Field(default_factory=list, max_length=4000)
    settings: dict[str, Any] = Field(default_factory=dict)

    @field_validator("elements")
    @classmethod
    def _elements(cls, v: list[dict]) -> list[dict]:
        ids = set()
        for e in v:
            if e.get("kind") not in PLAN_ELEMENT_KINDS:
                raise ValueError(f"Élément de plan inconnu : {e.get('kind')!r}")
            eid = str(e.get("id") or "")
            if not eid or len(eid) > 64 or eid in ids:
                raise ValueError("Chaque élément du plan doit avoir un identifiant unique.")
            ids.add(eid)
        return v

    @field_validator("background")
    @classmethod
    def _background(cls, v: Optional[dict]) -> Optional[dict]:
        if v and v.get("path") and (".." in str(v["path"]) or len(str(v["path"])) > 300):
            raise ValueError("Chemin de fond de plan invalide.")
        return v


class WorkshopPlanPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    version: Optional[Literal["actuel", "projet", "archive"]] = None
    width_m: Optional[float] = Field(default=None, ge=2, le=400)
    length_m: Optional[float] = Field(default=None, ge=2, le=400)
    background: Optional[dict[str, Any]] = None
    elements: Optional[list[dict[str, Any]]] = Field(default=None, max_length=4000)
    settings: Optional[dict[str, Any]] = None
    clear_background: bool = False

    _elements = field_validator("elements")(WorkshopPlanIn._elements.__func__)
    _background = field_validator("background")(WorkshopPlanIn._background.__func__)


class PlanPlacementIn(BaseModel):
    """Placer les stations d'un calcul sur les machines d'un plan (association auto + manuelle)."""
    plan_id: str
    assignment: dict[str, list[str]] = Field(default_factory=dict, max_length=300)


# ------------------------------------------------------------------ simulation à événements discrets (v3.0)
class DesScenario(BaseModel):
    """Scénario : surcharges du modèle (settings / source / shift / transporters / stations / breakdowns)."""
    name: str = Field(default="Scénario", max_length=60)
    overrides: dict[str, Any] = Field(default_factory=dict)
    absent: list[str] = Field(default_factory=list, max_length=100, description="Opérateurs absents")


class DesRequest(BaseModel):
    name: str = Field(default="", max_length=120)
    model: Optional[dict[str, Any]] = Field(default=None, description="Modèle édité ; par défaut : modèle généré")
    scenarios: list[DesScenario] = Field(default_factory=lambda: [DesScenario(name="Référence")],
                                         min_length=1, max_length=3)
    replications: int = Field(default=5, ge=1, le=20)
    plan_id: Optional[str] = Field(default=None, description="Plan d'atelier pour les chemins à pied")


# ------------------------------------------------------------------ logique par blocs (Process Flow)
class FlowIn(BaseModel):
    name: str = Field(default="Flux", min_length=1, max_length=120)
    run_id: Optional[str] = None
    graph: dict[str, Any] = Field(default_factory=dict)


class FlowPatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    graph: Optional[dict[str, Any]] = None


class FlowValidateIn(BaseModel):
    graph: dict[str, Any]


class FlowSimulateIn(BaseModel):
    graph: dict[str, Any]
    name: str = Field(default="", max_length=120)
    replications: int = Field(default=3, ge=1, le=20)
    flow_id: Optional[str] = None
    plan_id: Optional[str] = None
