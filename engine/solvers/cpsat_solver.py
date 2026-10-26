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
from engine.resources import expand_problem, collapse_details, assign_workstations, assign_workers
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
        self.original = self.problem
        self.problem, self.origin = expand_problem(self.problem)

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
            station_cycle[s] = model.NewIntVar(0, int(self.target_cycle * scale * 2) + 1, f"cycle_s{s}")
        
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
        
        # 3a. Stations utilisées contiguës (1..k)
        for s in self.station_indices[1:]:
            model.Add(y[s] <= y[s - 1])

        # 3. Station utilisée si au moins une opération
        for s in self.station_indices:
            model.Add(sum(x[op_id, s] for op_id in self.op_ids) >= 1).OnlyEnforceIf(y[s])
            model.Add(sum(x[op_id, s] for op_id in self.op_ids) == 0).OnlyEnforceIf(y[s].Not())
        
        # 4b. Types de machine par station (z) : une station peut tenir jusqu'à
        #     `max_machines_per_station` machines (poste multi-machines) ; chaque
        #     type utilisé consomme un poste physique de ce type.
        maxm = max(1, int(self.problem.max_machines_per_station or 1))
        mct = int(round(max(0.0, float(self.problem.machine_change_time or 0.0)) * scale))
        z = {}
        for s in self.station_indices:
            for m in self.machine_types:
                z[m, s] = model.NewBoolVar(f"z_{m}_s{s}")
                ops_m = [o for o in self.op_ids if self.operations[o].machine_type == m]
                for o in ops_m:
                    model.AddImplication(x[o, s], z[m, s])
                model.Add(z[m, s] <= sum(x[o, s] for o in ops_m))
            if self.machine_types:
                model.Add(sum(z[m, s] for m in self.machine_types) <= maxm)
        if self.ws_ids:
            for m in self.machine_types:
                extra = [(self.replicas[o] - 1, o) for o in self.op_ids
                         if self.operations[o].machine_type == m and self.replicas[o] > 1]
                model.Add(
                    sum(z[m, s] for s in self.station_indices)
                    + sum(k * x[o, s] for k, o in extra for s in self.station_indices)
                    <= self.ws_count.get(m, 0)
                )

        # 4. Temps de cycle par station <= cadence (durée par poste si dédoublée,
        #    + déplacement entre machines)
        dur = {o: int(round(self.eff_dur[o] * scale)) for o in self.op_ids}
        cap = int(round(self.target_cycle * scale))
        for s in self.station_indices:
            load = sum(dur[o] * x[o, s] for o in self.op_ids)
            if mct and self.machine_types:
                load = load + mct * (sum(z[m, s] for m in self.machine_types) - y[s])
            model.Add(load <= cap)
            model.Add(station_cycle[s] == load)
            # Une opération dédoublée (mode parallel) est seule sur sa station
            for o in self.op_ids:
                if self.replicas[o] > 1:
                    model.Add(sum(x[q, s] for q in self.op_ids if q != o) == 0).OnlyEnforceIf(x[o, s])

        # 4c. Sections strictes (optionnel)
        if (self.problem.section_policy or "prefer").lower() == "strict":
            sections = sorted({self.operations[o].section for o in self.op_ids if self.operations[o].section})
            if len(sections) > 1:
                for s in self.station_indices:
                    zs = {}
                    for sec in sections:
                        zs[sec] = model.NewBoolVar(f"sec_{sec}_s{s}")
                        for o in self.op_ids:
                            if self.operations[o].section == sec:
                                model.AddImplication(x[o, s], zs[sec])
                    model.Add(sum(zs.values()) <= 1)

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

        # 6. Ouvriers : 1 ouvrier par station (x postes parallèles), chacun maîtrisant
        #    TOUTES les compétences des opérations de la station ; un ouvrier = 1 station.
        if self.worker_ids:
            for s in self.station_indices:
                n_s = sum(w_assign[w_id, s] for w_id in self.worker_ids)
                model.Add(n_s >= y[s])
                model.Add(n_s <= y[s] + sum((self.replicas[o] - 1) * x[o, s]
                                            for o in self.op_ids if self.replicas[o] > 1))
                for o in self.op_ids:
                    if self.replicas[o] > 1:
                        model.Add(n_s >= self.replicas[o]).OnlyEnforceIf(x[o, s])
            for w_id in self.worker_ids:
                model.Add(sum(w_assign[w_id, s] for s in self.station_indices) <= 1)

            # 7. Compétences strictes par ouvrier
            for o in self.op_ids:
                need = set(self.operations[o].required_skills)
                if not need:
                    continue
                unq = [w_id for w_id in self.worker_ids if not need <= set(self.workers[w_id].skills)]
                if len(unq) == len(self.worker_ids):
                    for s in self.station_indices:
                        model.Add(x[o, s] == 0)
                    continue
                for w_id in unq:
                    for s in self.station_indices:
                        model.AddBoolOr([w_assign[w_id, s].Not(), x[o, s].Not()])

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
            # À nombre de postes égal, préférer moins de machines par station
            n_z = len(self.machine_types) * len(self.station_indices)
            if n_z:
                model.Minimize(posts * (n_z + 1) + sum(z.values()))
            else:
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
                problem=self.original,
                success=False,
                solver_used="CP-SAT",
                solve_time_seconds=solve_time,
                status=status_str,
                error_message=self._explain_failure(status_str),
            )
        
        # ============ EXTRACTION ============

        raw_assign = {}
        for op_id in self.op_ids:
            for s in self.station_indices:
                if solver.Value(x[op_id, s]) == 1:
                    raw_assign[op_id] = s
                    break

        used = [s for s in self.station_indices if solver.Value(y[s]) == 1]
        renum = {s: i + 1 for i, s in enumerate(used)}
        station_details = []
        for s in used:
            ops_in_station = [op_id for op_id in self.op_ids if raw_assign.get(op_id) == s]
            st_time = solver.Value(station_cycle[s]) / scale
            par = max((self.replicas[o] for o in ops_in_station), default=1)
            station_details.append({
                "station": renum[s],
                "total_time": round(st_time, 3),
                "load_pct": round(st_time / self.target_cycle * 100, 1) if self.target_cycle > 0 else 0,
                "operations": ops_in_station,
                "workers": [],
                "workstation": "",
                "parallel": par,
            })

        durations = {o.id: o.duration for o in self.problem.operations}
        operation_assignments, split_msgs = collapse_details(station_details, self.origin, durations)
        prob = self.original
        ops = {o.id: o for o in prob.operations}
        warnings = [str(i) for i in precheck(prob) if i.severity == "warning"]
        assign_workstations(prob, station_details, ops, warnings)
        wa = assign_workers(prob, station_details, ops, warnings)
        worker_assignments = {wid: f"WS{st}" for wid, st in wa.items()}
        k = line_kpis(prob, station_details)
        violations = validate_result(prob, station_details)
        warnings += split_msgs
        if status != cp_model.OPTIMAL:
            warnings.append("Solution feasible mais non prouvée optimale (timeout)")

        return BalancingResult(
            problem=prob,
            success=not violations,
            solver_used="CP-SAT",
            solve_time_seconds=solve_time,
            status=status_str if not violations else "INFEASIBLE_CONSTRAINTS",
            stations_used=len(station_details),
            actual_cycle_time=k["actual_cycle_time"],
            efficiency=k["efficiency"],
            balance_delay=k["balance_delay"],
            smoothness_index=k["smoothness_index"],
            station_details=station_details,
            operation_assignments=operation_assignments,
            worker_assignments=worker_assignments,
            warnings=warnings,
            error_message=("Solution non conforme : " + " | ".join(str(v) for v in violations)) if violations else "",
        )

    def _explain_failure(self, status_str: str) -> str:
        issues = [i for i in precheck(self.original) if i.severity == "error"]
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