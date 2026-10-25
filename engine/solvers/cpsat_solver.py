"""
Solveur CP-SAT (OR-Tools) pour équilibrage de ligne optimal.
Gère: précédence, temps cycle, machines, compétences, affectation ouvriers, objectifs multiples.

Nécessite: pip install ortools
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

try:
    from ortools.sat.python import cp_model
    ORTOOLS_AVAILABLE = True
except ImportError:
    ORTOOLS_AVAILABLE = False
    cp_model = None

from collections import Counter

from engine.diagnostics import precheck, parallel_replicas, line_kpis, validate_result
from engine.models import (
    LineBalancingProblem, Operation, Workstation, Worker,
    BalancingResult, SolverAlgorithm, OptimizationObjective
)


@dataclass
class CPSatSolver:
    """Solveur basé sur OR-Tools CP-SAT."""
    problem: LineBalancingProblem
    time_limit_seconds: int = 60
    num_workers: int = 8
    log_search: bool = False
    
    def __post_init__(self):
        if not ORTOOLS_AVAILABLE:
            raise RuntimeError("OR-Tools non installé: pip install ortools")
        
        self.operations = {op.id: op for op in self.problem.operations}
        self.workstations = {ws.id: ws for ws in self.problem.workstations}
        self.workers = {w.id: w for w in self.problem.workers}
        
        # Stations max = min(ops, max_stations_config, postes_physiques_disponibles)
        # Si pas de postes physiques fournis, ne pas limiter par max_physical
        max_physical = len([ws for ws in self.problem.workstations if ws.available])
        if max_physical == 0:
            max_physical = len(self.problem.operations)
        self.max_stations = min(
            len(self.problem.operations),
            self.problem.max_stations or len(self.problem.operations),
            max_physical
        )
        
        self.target_cycle = self.problem.target_cycle_time
        
        self.op_ids = [op.id for op in self.problem.operations]
        self.ws_ids = [ws.id for ws in self.problem.workstations if ws.available]
        self.worker_ids = [w.id for w in self.problem.workers if w.available]
        self.station_indices = list(range(1, self.max_stations + 1))
        
        # Dédoublement : une opération > cycle occupe seule n postes parallèles
        self.replicas = {op.id: parallel_replicas(op, self.target_cycle) for op in self.problem.operations}
        self.eff_dur = {op.id: op.duration / self.replicas[op.id] for op in self.problem.operations}
        self.ws_count = Counter(ws.machine_type for ws in self.problem.workstations if ws.available)
        self.machine_types = set(op.machine_type for op in self.problem.operations if op.machine_type)
        self.all_skills = set(s for op in self.problem.operations for s in op.required_skills)
    
    def solve(self) -> BalancingResult:
        """Résout le problème avec CP-SAT."""
        start_time = time.time()
        
        model = cp_model.CpModel()
        
        # ============ VARIABLES ============
        
        # x[op_id][s] = 1 si opération op assignée à station s
        x = {}
        for op_id in self.op_ids:
            for s in self.station_indices:
                x[op_id, s] = model.NewBoolVar(f"x_{op_id}_s{s}")
        
        # y[s] = 1 si station s utilisée
        y = {s: model.NewBoolVar(f"y_s{s}") for s in self.station_indices}
        
        # w_assign[worker_id][s] = 1 si ouvrier assigné à station s
        w_assign = {}
        for w_id in self.worker_ids:
            for s in self.station_indices:
                w_assign[w_id, s] = model.NewBoolVar(f"w_{w_id}_s{s}")
        
        # station_cycle[s] = temps total station s (entier: minutes * 100 pour précision)
        scale = 100
        station_cycle = {}
        for s in self.station_indices:
            station_cycle[s] = model.NewIntVar(0, int(self.target_cycle * scale * 2), f"cycle_s{s}")
        
        # ============ CONTRAINTES DE BASE ============
        
        # 1. Chaque opération assignée exactement une fois
        for op_id in self.op_ids:
            model.Add(sum(x[op_id, s] for s in self.station_indices) == 1)
        
        # 2. Précédence: station(op) >= station(pred)
        for op_id in self.op_ids:
            op = self.operations[op_id]
            for pred_id in op.predecessors:
                if pred_id in self.operations:
                    for s in self.station_indices:
                        model.Add(x[op_id, s] <= sum(x[pred_id, sp] for sp in range(1, s + 1)))
        
        # 3. Station utilisée si au moins une opération
        for s in self.station_indices:
            model.Add(sum(x[op_id, s] for op_id in self.op_ids) >= 1).OnlyEnforceIf(y[s])
            model.Add(sum(x[op_id, s] for op_id in self.op_ids) == 0).OnlyEnforceIf(y[s].Not())
        
        # 4. Temps de cycle par station <= target (durée par poste si dédoublée)
        dur = {o: int(round(self.eff_dur[o] * scale)) for o in self.op_ids}
        for s in self.station_indices:
            model.Add(sum(dur[o] * x[o, s] for o in self.op_ids) <= int(round(self.target_cycle * scale)))
            model.Add(station_cycle[s] == sum(dur[o] * x[o, s] for o in self.op_ids))
            # Une opération dédoublée est seule sur sa station
            for o in self.op_ids:
                if self.replicas[o] > 1:
                    model.Add(sum(x[q, s] for q in self.op_ids if q != o) == 0).OnlyEnforceIf(x[o, s])

        # 4b. Un seul type machine par station + capacité en postes physiques par type
        z = {}
        for s in self.station_indices:
            for m in self.machine_types:
                z[m, s] = model.NewBoolVar(f"z_{m}_s{s}")
                for o in self.op_ids:
                    if self.operations[o].machine_type == m:
                        model.AddImplication(x[o, s], z[m, s])
            model.Add(sum(z[m, s] for m in self.machine_types) <= 1)
        if self.ws_ids:
            for m in self.machine_types:
                extra = [(self.replicas[o] - 1, o) for o in self.op_ids
                         if self.operations[o].machine_type == m and self.replicas[o] > 1]
                model.Add(
                    sum(z[m, s] for s in self.station_indices)
                    + sum(k * x[o, s] for k, o in extra for s in self.station_indices)
                    <= self.ws_count.get(m, 0)
                )
        
        # 5. Disponibilité machines: globale - vérifier que chaque type requis existe
        if self.ws_ids:
            required_machines = set(op.machine_type for op in self.problem.operations if op.machine_type)
            available_machines = set(ws.machine_type for ws in self.problem.workstations if ws.available)
            for m in required_machines:
                if m not in available_machines:
                    for op_id in self.op_ids:
                        if self.operations[op_id].machine_type == m:
                            for s in self.station_indices:
                                model.Add(x[op_id, s] == 0)
        
        # 6. Affectation ouvriers: chaque station utilisée a au moins 1 ouvrier
        if self.worker_ids:
            for s in self.station_indices:
                model.Add(sum(w_assign[w_id, s] for w_id in self.worker_ids) >= y[s])
                max_w = 2
                if self.ws_ids:
                    max_w = max((ws.max_workers for ws in self.problem.workstations if ws.available), default=2)
                max_w = max(max_w, max(self.replicas.values(), default=1))
                model.Add(sum(w_assign[w_id, s] for w_id in self.worker_ids) <= max_w)
                for o in self.op_ids:
                    if self.replicas[o] > 1:
                        model.Add(sum(w_assign[w_id, s] for w_id in self.worker_ids) >= self.replicas[o]).OnlyEnforceIf(x[o, s])
            
            # Un ouvrier max 1 station
            for w_id in self.worker_ids:
                model.Add(sum(w_assign[w_id, s] for s in self.station_indices) <= 1)
            
            # 7. Compétences: si station s a ops nécessitant skill S, au moins un ouvrier à s a skill S
            for s in self.station_indices:
                for skill in self.all_skills:
                    ops_needing = [op_id for op_id in self.op_ids if skill in self.operations[op_id].required_skills]
                    if ops_needing:
                        need_skill = model.NewBoolVar(f"need_{skill}_s{s}")
                        model.Add(sum(x[op_id, s] for op_id in ops_needing) >= 1).OnlyEnforceIf(need_skill)
                        model.Add(sum(x[op_id, s] for op_id in ops_needing) == 0).OnlyEnforceIf(need_skill.Not())
                        
                        workers_with_skill = [w_id for w_id in self.worker_ids if skill in self.workers[w_id].skills]
                        if workers_with_skill:
                            model.Add(need_skill <= sum(w_assign[w_id, s] for w_id in workers_with_skill))
                        else:
                            for op_id in ops_needing:
                                model.Add(x[op_id, s] == 0)
        
        # 8. Assignments forcés
        for op_id, station in self.problem.forced_assignments.items():
            if op_id in self.op_ids and 1 <= station <= self.max_stations:
                model.Add(x[op_id, station] == 1)
        
        # 9. Assignments interdits
        for op_id, forbidden in self.problem.forbidden_assignments.items():
            if op_id in self.op_ids:
                for s in forbidden:
                    if 1 <= s <= self.max_stations:
                        model.Add(x[op_id, s] == 0)
        
        # 10. Groupes même station
        for group in self.problem.same_station_groups:
            if len(group) >= 2:
                for s in self.station_indices:
                    first = group[0]
                    for op_id in group[1:]:
                        if op_id in self.op_ids and first in self.op_ids:
                            model.Add(x[first, s] == x[op_id, s])
        
        # ============ OBJECTIF ============
        
        posts = sum(y[s] for s in self.station_indices) + sum(
            (self.replicas[o] - 1) * x[o, s] for o in self.op_ids for s in self.station_indices if self.replicas[o] > 1)
        if self.problem.objective == OptimizationObjective.MIN_STATIONS:
            model.Minimize(posts)
        
        elif self.problem.objective == OptimizationObjective.MIN_CYCLE_TIME:
            model.Minimize(sum(y[s] for s in self.station_indices))
        
        elif self.problem.objective == OptimizationObjective.MAX_EFFICIENCY:
            model.Minimize(sum(y[s] for s in self.station_indices))
        
        elif self.problem.objective == OptimizationObjective.BALANCE_WORKLOAD:
            max_cycle = model.NewIntVar(0, int(self.target_cycle * scale * 2), "max_cycle")
            min_cycle = model.NewIntVar(0, int(self.target_cycle * scale * 2), "min_cycle")
            for s in self.station_indices:
                model.Add(max_cycle >= station_cycle[s]).OnlyEnforceIf(y[s])
                model.Add(min_cycle <= station_cycle[s]).OnlyEnforceIf(y[s])
                model.Add(max_cycle >= 0).OnlyEnforceIf(y[s].Not())
                model.Add(min_cycle <= int(self.target_cycle * scale * 2)).OnlyEnforceIf(y[s].Not())
            model.Minimize(max_cycle - min_cycle)
        
        # ============ SOLVE ============
        
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = self.time_limit_seconds
        solver.parameters.num_search_workers = self.num_workers
        solver.parameters.log_search_progress = self.log_search
        
        class LoggingCallback(cp_model.CpSolverSolutionCallback):
            def __init__(self):
                cp_model.CpSolverSolutionCallback.__init__(self)
                self.solution_count = 0
            def on_solution_callback(self):
                self.solution_count += 1
                if self.solution_count % 10 == 0:
                    obj = self.ObjectiveValue()
                    print(f"  Solution {self.solution_count}: objectif={obj}")
        
        callback = LoggingCallback() if self.log_search else None
        status = solver.Solve(model, callback)
        
        solve_time = time.time() - start_time
        
        status_names = {
            cp_model.OPTIMAL: "OPTIMAL",
            cp_model.FEASIBLE: "FEASIBLE",
            cp_model.INFEASIBLE: "INFEASIBLE",
            cp_model.MODEL_INVALID: "MODEL_INVALID",
            cp_model.UNKNOWN: "UNKNOWN",
        }
        status_str = status_names.get(status, f"STATUS_{status}")
        
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return BalancingResult(
                problem=self.problem,
                success=False,
                solver_used="CP-SAT",
                solve_time_seconds=solve_time,
                status=status_str,
                error_message=self._explain_failure(status_str),
            )
        
        # ============ EXTRACTION ============
        
        operation_assignments = {}
        for op_id in self.op_ids:
            for s in self.station_indices:
                if solver.Value(x[op_id, s]) == 1:
                    operation_assignments[op_id] = s
                    break
        
        stations_used = sum(1 for s in self.station_indices if solver.Value(y[s]) == 1)
        
        station_details = []
        total_time = 0.0
        max_station_time = 0.0
        
        for s in range(1, stations_used + 1):
            ops_in_station = [op_id for op_id in self.op_ids if operation_assignments.get(op_id) == s]
            st_time = sum(self.eff_dur[op_id] for op_id in ops_in_station)
            par = max((self.replicas[o] for o in ops_in_station), default=1)
            total_time += st_time
            max_station_time = max(max_station_time, st_time)
            load_pct = (st_time / self.target_cycle * 100) if self.target_cycle > 0 else 0
            
            workers_assigned = []
            if self.worker_ids:
                for w_id in self.worker_ids:
                    if solver.Value(w_assign[w_id, s]) == 1:
                        workers_assigned.append(self.workers[w_id].name)
            
            station_details.append({
                "station": s,
                "total_time": round(st_time, 3),
                "load_pct": round(load_pct, 1),
                "operations": ops_in_station,
                "workers": workers_assigned,
                "workstation": "",
                "parallel": par,
            })
        
        k = line_kpis(self.problem, station_details)
        self._assign_workstations(station_details)
        worker_assignments = {}
        if self.worker_ids:
            for w_id in self.worker_ids:
                for s in self.station_indices:
                    if solver.Value(w_assign[w_id, s]) == 1:
                        worker_assignments[w_id] = f"WS{s}"
                        break
        
        return BalancingResult(
            problem=self.problem,
            success=True,
            solver_used="CP-SAT",
            solve_time_seconds=solve_time,
            status=status_str,
            stations_used=stations_used,
            actual_cycle_time=k["actual_cycle_time"],
            efficiency=k["efficiency"],
            balance_delay=k["balance_delay"],
            smoothness_index=k["smoothness_index"],
            station_details=station_details,
            operation_assignments=operation_assignments,
            worker_assignments=worker_assignments,
            warnings=[str(i) for i in precheck(self.problem) if i.severity == "warning"]
            + ([] if status == cp_model.OPTIMAL else ["Solution feasible mais non prouvée optimale (timeout)"]),
        )

    def _assign_workstations(self, station_details: list[dict]) -> None:
        """Affecte les postes physiques (le modèle garantit la capacité par type)."""
        used: set[str] = set()
        for sd in station_details:
            mts = {self.operations[o].machine_type for o in sd["operations"] if self.operations[o].machine_type}
            par = int(sd.get("parallel", 1))
            pool = [ws for ws in self.problem.workstations if ws.available and ws.id not in used
                    and (not mts or ws.machine_type in mts)]
            picked = [ws.id for ws in pool[:par]]
            sd["machine_types"] = sorted(mts)
            if len(picked) == par:
                used.update(picked)
                sd["workstation"] = picked[0]
                sd["workstations"] = picked

    def _explain_failure(self, status_str: str) -> str:
        issues = [i for i in precheck(self.problem) if i.severity == "error"]
        if status_str == "UNKNOWN":
            head = f"Aucune solution trouvée dans la limite de {self.time_limit_seconds}s"
        else:
            head = f"Problème infaisable (status={status_str})"
        if issues:
            return head + " : " + " | ".join(str(i) for i in issues)
        return head + " : contraintes combinées trop serrées (précédence, sections, compétences). Essayer un cycle plus long."


def solve_cp_sat(
    problem: LineBalancingProblem,
    time_limit_seconds: int = 60,
    num_workers: int = 8,
    log_search: bool = False,
) -> BalancingResult:
    """Point d'entrée simple pour CP-SAT."""
    if not ORTOOLS_AVAILABLE:
        raise RuntimeError("OR-Tools non installé: pip install ortools")
    solver = CPSatSolver(problem, time_limit_seconds, num_workers, log_search)
    return solver.solve()