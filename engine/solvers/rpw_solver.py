"""
Solveur RPW (Ranked Positional Weight) - Heuristique rapide pour équilibrage de ligne.
Basé sur: Helgeson & Birnie (1961) - "Assembly Line Balancing Using the Ranked Positional Weight Technique"

Complexité: O(n²) - Très rapide, donne une solution initiale feasible.
Utilisation: Solution de départ pour CP-SAT, ou résolution rapide interactive.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Set
from collections import defaultdict, Counter

from engine.diagnostics import precheck, parallel_replicas, line_kpis, validate_result
from engine.resources import (
    expand_problem, collapse_details, station_machine_types, staffable,
    assign_workstations, assign_workers,
)

from engine.models import (
    LineBalancingProblem, Operation, Workstation, Worker,
    BalancingResult, SolverAlgorithm, OptimizationObjective
)


@dataclass
class RPWSolver:
    """Solveur RPW (Ranked Positional Weight)."""
    problem: LineBalancingProblem
    max_stations: Optional[int] = None
    reserve_slack: bool = True   # crédite la place restante de la station dans la réserve de postes
    reserve_margin: int = 0      # postes de réserve gardés en plus pour chaque type de machine
    
    def __post_init__(self):
        self.original = self.problem
        self.problem, self.origin = expand_problem(self.problem)
        if self.max_stations is None:
            self.max_stations = len(self.problem.operations)
        self.cycle_time = self.problem.target_cycle_time
        self.ops = {op.id: op for op in self.problem.operations}
    
    def compute_rpw(self) -> Dict[str, float]:
        """
        Calcule le poids positionnel classé (RPW) pour chaque opération.
        RPW = durée_op + somme RPW des successeurs immédiats.
        """
        rpw = {}
        # Calculer dans l'ordre topologique inverse (feuilles d'abord)
        # On construit le graphe des successeurs
        successors = defaultdict(list)
        for op in self.problem.operations:
            for pred in op.predecessors:
                successors[pred].append(op.id)
        
        # Mémoisation récursive
        def calc_rpw(op_id: str) -> float:
            if op_id in rpw:
                return rpw[op_id]
            op = self.ops[op_id]
            succ_rpw = sum(calc_rpw(succ) for succ in successors.get(op_id, []))
            rpw[op_id] = op.duration + succ_rpw
            return rpw[op_id]
        
        for op in self.problem.operations:
            calc_rpw(op.id)
        
        return rpw
    
    def get_available_operations(self, assigned: Set[str], station_ops: List[str]) -> List[str]:
        """Retourne les opérations candidates pour la station courante."""
        available = []
        for op in self.problem.operations:
            if op.id in assigned:
                continue
            if all(pred in assigned for pred in op.predecessors):
                if op.machine_type and any(ws.available for ws in self.problem.workstations):
                    has_machine = any(
                        ws.machine_type == op.machine_type and ws.available
                        for ws in self.problem.workstations
                    )
                    if not has_machine:
                        continue
                if op.required_skills and any(w.available for w in self.problem.workers):
                    has_skill = False
                    for w in self.problem.workers:
                        if w.available and all(s in w.skills for s in op.required_skills):
                            has_skill = True
                            break
                    if not has_skill:
                        continue
                available.append(op.id)
        return available

    @staticmethod
    def _station_machine_type(station_ops: list[str], ops: dict[str, Operation]) -> str:
        """Premier type machine de la station (compatibilité)."""
        for oid in station_ops:
            mt = ops[oid].machine_type
            if mt:
                return mt
        return ""

    def solve(self) -> BalancingResult:
        """RPW v2.2 : stations multi-machines (un ouvrier tient jusqu'à
        `max_machines_per_station` machines voisines), opérations longues
        fractionnées (parts + reliquat combinable), sections en préférence
        (ou strictes), et contrôle de pourvoi des stations par des ouvriers
        DISTINCTS (couplage) pendant la construction."""
        start_time = time.time()
        P = self.problem
        C = self.cycle_time
        mct = max(0.0, float(P.machine_change_time or 0.0))
        maxm = max(1, int(P.max_machines_per_station or 1))
        strict_sec = (P.section_policy or "prefer").lower() == "strict"
        legacy_parallel = (P.split_mode or "share").lower() == "parallel"
        ops = self.ops
        rpw = self.compute_rpw()

        has_ws = any(ws.available for ws in P.workstations)
        remaining = Counter(ws.machine_type for ws in P.workstations if ws.available)
        workers = [w for w in P.workers if w.available]
        closed_sets: list[set] = []   # compétences des stations déjà pourvues

        assigned: set = set()
        station_assignments: Dict[str, int] = {}
        station_details: list = []
        cur = {"ops": [], "types": [], "section": "", "par": 1}
        current_station = 1

        def t_of(op_list):
            n = len(station_machine_types(op_list, ops))
            return sum(ops[o].duration for o in op_list) + (mct * (n - 1) if n > 1 else 0.0)

        def need_of(op_list):
            s_ = set()
            for o in op_list:
                s_.update(ops[o].required_skills)
            return s_

        rem_work = Counter()
        for o_ in P.operations:
            if o_.machine_type:
                rem_work[o_.machine_type] += o_.duration

        def machine_reserve_ok(op_id: str, t_new: float, par: int = 1) -> bool:
            """Ouvrir le type m dans la station courante laisse-t-il assez de postes m
            pour le travail m restant ? (borne inférieure ceil(travail / cadence))"""
            m = ops[op_id].machine_type
            if not (has_ws and m):
                return True
            left = rem_work[m] - ops[op_id].duration - (max(0.0, C - t_new) if self.reserve_slack else 0.0)
            need = math.ceil(max(0.0, left) / C - 1e-6) if C > 0 else 0
            margin = self.reserve_margin if (cur["ops"] and rem_work[m] - ops[op_id].duration > 1e-6) else 0
            return remaining[m] - par >= need + margin

        def fits(op_id: str) -> bool:
            o = ops[op_id]
            st = cur["ops"]
            if not st:
                par = parallel_replicas(o, C) if legacy_parallel else 1
                if o.machine_type and has_ws and remaining[o.machine_type] < par:
                    return False
                if maxm > 1 and not machine_reserve_ok(op_id, o.duration / par, par):
                    return False
                if workers and o.required_skills and not staffable(closed_sets + [set(o.required_skills)] * par, workers):
                    return False
                return True
            if cur["par"] > 1:
                return False
            if t_of(st + [op_id]) > C + 1e-6:
                return False
            m = o.machine_type
            if m and m not in cur["types"]:
                if len(cur["types"]) + 1 > maxm:
                    return False
                if has_ws and remaining[m] < 1:
                    return False
                if not machine_reserve_ok(op_id, t_of(st + [op_id])):
                    return False
            if strict_sec and cur["section"] and o.section and o.section != cur["section"]:
                return False
            if workers:
                need = need_of(st + [op_id])
                if need and not staffable(closed_sets + [need], workers):
                    return False
            return True

        def add(op_id: str):
            o = ops[op_id]
            if not cur["ops"]:
                cur["par"] = parallel_replicas(o, C) if (legacy_parallel and o.duration > C + 1e-6) else 1
            if o.machine_type and o.machine_type not in cur["types"]:
                cur["types"].append(o.machine_type)
                if has_ws:
                    remaining[o.machine_type] -= cur["par"]
            if o.section and not cur["section"]:
                cur["section"] = o.section
            cur["ops"].append(op_id)
            if o.machine_type:
                rem_work[o.machine_type] -= o.duration
            station_assignments[op_id] = current_station
            assigned.add(op_id)

        def close():
            par = cur["par"]
            t = t_of(cur["ops"]) / par
            need = need_of(cur["ops"])
            if workers and need and staffable(closed_sets + [need] * par, workers):
                closed_sets.extend([need] * par)
            station_details.append({
                "station": current_station,
                "total_time": round(t, 3),
                "load_pct": round(t / C * 100, 1) if C > 0 else 0,
                "operations": cur["ops"].copy(),
                "workers": [],
                "workstation": "",
                "parallel": par,
            })
            cur.update({"ops": [], "types": [], "section": "", "par": 1})

        n_ops = len(P.operations)
        while len(assigned) < n_ops and current_station <= self.max_stations:
            available = self.get_available_operations(assigned, cur["ops"])
            candidates = [o for o in available if fits(o)]
            if not candidates:
                if cur["ops"]:
                    close()
                    current_station += 1
                    continue
                if not available:
                    break
                # Station vide et rien de « propre » : meilleure candidate quand même
                # (poste ou ouvrier manquant -> signalé ensuite)
                pool = [o for o in available if not (has_ws and ops[o].machine_type
                                                      and remaining[ops[o].machine_type] < 1)] or available
                candidates = [max(pool, key=lambda o: rpw.get(o, 0))]

            def key(o):
                op = ops[o]
                same_m = 1 if (not op.machine_type or op.machine_type in cur["types"]) else 0
                same_s = 1 if (cur["section"] and op.section == cur["section"]) else 0
                return (same_m, same_s, rpw.get(o, 0)) if cur["ops"] else (rpw.get(o, 0),)
            add(max(candidates, key=key))

        if cur["ops"]:
            close()

        # Retour aux opérations d'origine (parts d'opérations partagées)
        durations = {o.id: o.duration for o in P.operations}
        op_assign, split_msgs = collapse_details(station_details, self.origin, durations)

        warnings = ["Solution RPW (heuristique) - non garantie optimale"]
        self._assign_resources(station_details, op_assign, warnings)
        warnings.extend(split_msgs)

        prob = self.original
        k = line_kpis(prob, station_details)
        issues = precheck(prob)
        warnings[1:1] = [str(i) for i in issues if i.severity == "warning"]
        violations = validate_result(prob, station_details)
        unassigned = [o.id for o in prob.operations if o.id not in op_assign]
        ok = not violations and not unassigned
        err = ""
        if not ok:
            msgs = [str(v) for v in violations]
            if unassigned:
                msgs.insert(0, f"Opérations non affectées : {', '.join(unassigned)}")
            hints = [str(i) for i in issues if i.severity == "error"]
            err = "Solution non conforme : " + " | ".join(msgs + hints)

        return BalancingResult(
            problem=prob,
            success=ok,
            solver_used="RPW",
            solve_time_seconds=time.time() - start_time,
            status="FEASIBLE" if ok else "INFEASIBLE_CONSTRAINTS",
            stations_used=len(station_details),
            actual_cycle_time=k["actual_cycle_time"],
            efficiency=k["efficiency"],
            balance_delay=k["balance_delay"],
            smoothness_index=k["smoothness_index"],
            station_details=station_details,
            operation_assignments=op_assign,
            worker_assignments={wid: f"WS{sd['station']}" for sd in station_details for wid in sd.get("worker_ids", [])},
            warnings=warnings,
            error_message=err,
        )

    def _assign_resources(self, station_details: List[Dict], op_assignments: Dict[str, int], warnings: List[str]):
        """Postes physiques (un par type de machine de la station) puis ouvriers
        qualifiés (compétences strictes, rendement optimisé). Voir engine.resources."""
        ops = {o.id: o for o in self.original.operations}
        assign_workstations(self.original, station_details, ops, warnings)
        assign_workers(self.original, station_details, ops, warnings)


def solve_rpw(problem: LineBalancingProblem, max_stations: Optional[int] = None) -> BalancingResult:
    """Point d'entrée RPW. Multi-départ : la construction gloutonne est rejouée
    avec des variantes plus prudentes (réserve de postes stricte, sections
    strictes, puis 1 machine par station = ancien comportement) et la meilleure
    solution conforme est retenue (moins d'opérateurs, puis meilleure efficacité)."""
    import copy as _copy
    variants = [({}, True, 0)]
    if (problem.max_machines_per_station or 1) > 1:
        variants += [({}, False, 0), ({}, False, 1), ({"section_policy": "strict"}, False, 1),
                     ({"max_machines_per_station": 1, "section_policy": "strict"}, True, 0)]
    best = None
    first = None
    for attrs, slack, margin in variants:
        p = problem
        if attrs:
            p = _copy.copy(problem)
            for k, v in attrs.items():
                setattr(p, k, v)
        r = RPWSolver(p, max_stations, reserve_slack=slack, reserve_margin=margin).solve()
        r.problem = problem
        first = first or r
        if r.success:
            key = (sum(int(sd.get("parallel", 1)) for sd in r.station_details), -r.efficiency)
            if best is None or key < best[0]:
                best = (key, r)
    return best[1] if best else first
