"""
Modèles de données pour l'équilibrage de lignes textile.
Utilise dataclasses avec validation en __post_init__.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
from enum import Enum
import json


class SolverAlgorithm(str, Enum):
    RPW = "rpw"                    # Ranked Positional Weight (heuristique rapide)
    COMSOAL = "comsoal"            # COMSOAL (stochastique)
    CP_SAT = "cp_sat"              # OR-Tools CP-SAT (optimal, contraintes)
    MILP = "milp"                  # PuLP/Gurobi (si dispo)


class OptimizationObjective(str, Enum):
    MIN_STATIONS = "min_stations"          # SALBP-1
    MIN_CYCLE_TIME = "min_cycle_time"      # SALBP-2
    MAX_EFFICIENCY = "max_efficiency"      # SALBP-E
    BALANCE_WORKLOAD = "balance_workload"  # Minimiser écart charge


@dataclass
class Operation:
    """Une opération de la gamme de montage."""
    id: str
    name: str
    duration: float                    # Temps standard (minutes)
    predecessors: list[str] = field(default_factory=list)  # IDs opérations précédentes
    machine_type: str = ""             # Type machine requis (ex: "surjeteuse_5_fils")
    required_skills: list[str] = field(default_factory=list)  # Compétences requises
    section: str = ""                  # Section/atelier (Coupe, Montage, Finition...)
    optional: bool = False             # Opération optionnelle
    task_type: str = "VA"             # VA / NVA / ATTENTE (Yamazumi)
    
    # Calculés par le solveur
    assigned_station: int = -1
    earliest_station: int = -1
    latest_station: int = -1
    
    def __post_init__(self):
        if isinstance(self.predecessors, str):
            self.predecessors = [p.strip() for p in self.predecessors.split(";") if p.strip()]
        if isinstance(self.required_skills, str):
            self.required_skills = [s.strip() for s in self.required_skills.split(";") if s.strip()]


@dataclass
class Workstation:
    """Un poste de travail physique."""
    id: str
    name: str
    machine_type: str                  # Type machine installé
    available: bool = True
    max_workers: int = 1               # Nombre max d'ouvriers sur ce poste
    section: str = ""                  # Section associée
    
    # Calculés
    assigned_operations: list[str] = field(default_factory=list)
    assigned_workers: list[str] = field(default_factory=list)
    total_time: float = 0.0
    efficiency: float = 0.0


@dataclass
class Worker:
    """Un ouvrier avec ses compétences."""
    id: str
    name: str
    skills: list[str] = field(default_factory=list)
    efficiency: float = 1.0            # Coefficient performance (0.8 - 1.2)
    assigned_station: Optional[str] = None
    available: bool = True
    # Matrice de polyvalence : rendement par compétence (ex. {"piquer": 1.1, "surjeter": 0.8}).
    # Une compétence absente de `skills` reste interdite ; une compétence de `skills`
    # sans niveau prend `efficiency`.
    skill_levels: dict[str, float] = field(default_factory=dict)

    def __post_init__(self):
        if isinstance(self.skills, str):
            self.skills = [s.strip() for s in self.skills.split(";") if s.strip()]
        if not isinstance(self.skill_levels, dict):
            self.skill_levels = {}


@dataclass
class LineBalancingProblem:
    """Problème complet d'équilibrage."""
    name: str
    target_cycle_time: float           # Cadence cible (min/pièce)
    operations: list[Operation]
    workstations: list[Workstation]
    workers: list[Worker]
    max_stations: Optional[int] = None
    algorithm: SolverAlgorithm = SolverAlgorithm.CP_SAT
    objective: OptimizationObjective = OptimizationObjective.MIN_STATIONS
    time_limit_seconds: int = 60
    
    # Contraintes additionnelles
    forced_assignments: dict[str, int] = field(default_factory=dict)  # op_id -> station
    forbidden_assignments: dict[str, list[int]] = field(default_factory=dict)  # op_id -> [stations]
    same_station_groups: list[list[str]] = field(default_factory=list)  # ops qui doivent être ensemble

    # Organisation des postes (v2.2)
    max_machines_per_station: int = 3   # machines qu'un ouvrier peut tenir (1 = ancien comportement)
    machine_change_time: float = 0.0    # min/pièce ajoutées par machine supplémentaire (déplacement)
    section_policy: str = "prefer"      # "prefer" : regrouper par section si possible ; "strict" : jamais mélanger
    split_mode: str = "share"           # op > cadence : "share" (parts + reliquat combinable) | "parallel" (n postes égaux)
    
    def get_operation(self, op_id: str) -> Optional[Operation]:
        for op in self.operations:
            if op.id == op_id:
                return op
        return None
    
    def get_workstation(self, ws_id: str) -> Optional[Workstation]:
        for ws in self.workstations:
            if ws.id == ws_id:
                return ws
        return None
    
    def get_worker(self, worker_id: str) -> Optional[Worker]:
        for w in self.workers:
            if w.id == worker_id:
                return w
        return None
    
    def validate(self) -> list[str]:
        """Vérifie la cohérence du problème. Retourne liste d'erreurs."""
        errors = []
        op_ids = {op.id for op in self.operations}
        
        # Précédence: tous les prédécesseurs existent
        for op in self.operations:
            for pred in op.predecessors:
                if pred not in op_ids:
                    errors.append(f"Opération {op.id}: prédécesseur inconnu '{pred}'")
        
        # Pas de cycles dans la précédence (vérification simple)
        if self._has_cycles():
            errors.append("Cycle détecté dans les contraintes de précédence")
        
        # Machine types: au moins une station par type requis
        required_machines = {op.machine_type for op in self.operations if op.machine_type}
        available_machines = {ws.machine_type for ws in self.workstations if ws.available}
        for m in required_machines:
            if m not in available_machines:
                errors.append(f"Type machine requis '{m}' non disponible dans le parc")
        
        # Compétences: au moins un ouvrier par compétence requise
        required_skills = {s for op in self.operations for s in op.required_skills}
        available_skills = {s for w in self.workers if w.available for s in w.skills}
        for s in required_skills:
            if s not in available_skills:
                errors.append(f"Compétence requise '{s}' non disponible dans l'effectif")
        
        return errors
    
    def _has_cycles(self) -> bool:
        """Détection de cycles dans le graphe de précédence (DFS)."""
        visited = set()
        rec_stack = set()
        
        def dfs(op_id: str) -> bool:
            visited.add(op_id)
            rec_stack.add(op_id)
            op = self.get_operation(op_id)
            if op:
                for pred in op.predecessors:
                    if pred not in visited:
                        if dfs(pred):
                            return True
                    elif pred in rec_stack:
                        return True
            rec_stack.remove(op_id)
            return False
        
        for op in self.operations:
            if op.id not in visited:
                if dfs(op.id):
                    return True
        return False
    
    def to_json(self) -> str:
        return json.dumps(self, default=lambda o: o.__dict__, indent=2, ensure_ascii=False)
    
    @classmethod
    def from_json(cls, json_str: str) -> "LineBalancingProblem":
        data = json.loads(json_str)
        return cls(
            name=data["name"],
            target_cycle_time=data["target_cycle_time"],
            operations=[Operation(**op) for op in data["operations"]],
            workstations=[Workstation(**ws) for ws in data["workstations"]],
            workers=[Worker(**w) for w in data["workers"]],
            max_stations=data.get("max_stations"),
            algorithm=SolverAlgorithm(data.get("algorithm", "cp_sat")),
            objective=OptimizationObjective(data.get("objective", "min_stations")),
            time_limit_seconds=data.get("time_limit_seconds", 60),
            forced_assignments=data.get("forced_assignments", {}),
            forbidden_assignments=data.get("forbidden_assignments", {}),
            same_station_groups=data.get("same_station_groups", []),
            max_machines_per_station=data.get("max_machines_per_station", 3),
            machine_change_time=data.get("machine_change_time", 0.0),
            section_policy=data.get("section_policy", "prefer"),
            split_mode=data.get("split_mode", "share"),
        )


@dataclass
class BalancingResult:
    """Résultat d'un équilibrage."""
    problem: LineBalancingProblem
    success: bool
    solver_used: str
    solve_time_seconds: float
    status: str  # "OPTIMAL", "FEASIBLE", "INFEASIBLE", "TIMEOUT", "ERROR"
    
    # KPIs
    stations_used: int = 0
    actual_cycle_time: float = 0.0
    efficiency: float = 0.0
    balance_delay: float = 0.0
    smoothness_index: float = 0.0
    
    # Détails par station
    station_details: list[dict] = field(default_factory=list)
    
    # Affectations
    operation_assignments: dict[str, int] = field(default_factory=dict)  # op_id -> station
    worker_assignments: dict[str, str] = field(default_factory=dict)     # worker_id -> station_id
    
    # Messages
    warnings: list[str] = field(default_factory=list)
    error_message: str = ""

    # Aide à la décision (attachés par engine.capacity.enrich_result)
    capacity: Optional[Any] = None                     # CapacityAnalysis
    recommendations: list[Any] = field(default_factory=list)  # list[Recommendation]
    realistic_station_times: dict[int, float] = field(default_factory=dict)  # SAM/efficacité
    
    def to_json(self) -> str:
        return json.dumps(self, default=lambda o: o.__dict__ if hasattr(o, '__dict__') else str(o), indent=2, ensure_ascii=False)
    
    def summary(self) -> str:
        if not self.success:
            return f"❌ ÉCHEC: {self.error_message or self.status}"
        
        lines = [
            f"✅ {self.solver_used} - {self.status} en {self.solve_time_seconds:.1f}s",
            f"📊 Stations utilisées: {self.stations_used}",
            f"⏱️  Cycle time réel: {self.actual_cycle_time:.2f} min (cible: {self.problem.target_cycle_time:.2f})",
            f"📈 Efficacité ligne: {self.efficiency:.1f}%",
            f"⚖️  Balance delay: {self.balance_delay:.1f}%",
            f"📐 Smoothness index: {self.smoothness_index:.2f}",
            "",
            "📋 Détail par poste:",
        ]
        # Efficacité ouvriers appliquée : temps réalistes par station
        for sd in self.station_details:
            rt = self.realistic_station_times.get(sd["station"])
            rt_str = f" | réel: {rt:.2f}" if rt else ""
            lines.append(
                f"  Station {sd['station']}: {sd['total_time']:.2f} min | "
                f"{len(sd['operations'])} ops | "
                f"Charge: {sd['load_pct']:.1f}% | "
                f"Ouvriers: {', '.join(sd['workers']) if sd['workers'] else '—'}"
                f"{rt_str}"
            )
        if self.capacity is not None:
            lines += ["", self.capacity.summary()]
        if self.recommendations:
            lines += ["", "💡 Recommandations:"]
            for r in self.recommendations[:8]:
                lines.append("  " + (r.short() if hasattr(r, "short") else str(r)))
            if len(self.recommendations) > 8:
                lines.append(f"  … et {len(self.recommendations) - 8} autres")
        return "\n".join(lines)