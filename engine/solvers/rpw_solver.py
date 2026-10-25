"""
Solveur RPW (Ranked Positional Weight) - Heuristique rapide pour équilibrage de ligne.
Basé sur: Helgeson & Birnie (1961) - "Assembly Line Balancing Using the Ranked Positional Weight Technique"

Complexité: O(n²) - Très rapide, donne une solution initiale feasible.
Utilisation: Solution de départ pour CP-SAT, ou résolution rapide interactive.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Set
from collections import defaultdict, Counter

from engine.diagnostics import precheck, parallel_replicas, line_kpis, validate_result

from engine.models import (
    LineBalancingProblem, Operation, Workstation, Worker,
    BalancingResult, SolverAlgorithm, OptimizationObjective
)


@dataclass
class RPWSolver:
    """Solveur RPW (Ranked Positional Weight)."""
    problem: LineBalancingProblem
    max_stations: Optional[int] = None
    
    def __post_init__(self):
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
                if op.machine_type:
                    has_machine = any(
                        ws.machine_type == op.machine_type and ws.available
                        for ws in self.problem.workstations
                    )
                    if not has_machine:
                        continue
                if op.required_skills:
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
        """Détermine le machine_type de la station à partir de ses opérations."""
        for oid in station_ops:
            mt = ops[oid].machine_type
            if mt:
                return mt
        return ""

    def solve(self) -> BalancingResult:
        start_time = time.time()

        rpw = self.compute_rpw()

        assigned = set()
        station_assignments: Dict[str, int] = {}
        station_details = []

        current_station = 1
        station_time = 0.0
        station_ops = []
        station_section = ""  # section verrouillée de la station courante
        # Postes physiques restants par type machine (si postes fournis)
        has_ws = any(ws.available for ws in self.problem.workstations)
        remaining = Counter(ws.machine_type for ws in self.problem.workstations if ws.available)

        worker_skill_sets = [set(w.skills) for w in self.problem.workers if w.available]

        def ws_ok(op_id: str) -> bool:
            mt = self.ops[op_id].machine_type
            if not has_ws or not mt:
                return True
            return remaining[mt] >= parallel_replicas(self.ops[op_id], self.cycle_time)

        def close_station():
            mt = self._station_machine_type(station_ops, self.ops)
            par = 1
            t = station_time
            if len(station_ops) == 1 and station_time > self.cycle_time + 1e-6:
                par = parallel_replicas(self.ops[station_ops[0]], self.cycle_time)
                t = station_time / par
            if has_ws and mt:
                remaining[mt] -= par
            station_details.append({
                "station": current_station,
                "total_time": round(t, 3),
                "load_pct": round(t / self.cycle_time * 100, 1) if self.cycle_time > 0 else 0,
                "operations": station_ops.copy(),
                "workers": [],
                "workstation": "",
                "parallel": par,
            })

        while len(assigned) < len(self.problem.operations) and current_station <= self.max_stations:
            available = self.get_available_operations(assigned, station_ops)

            if station_ops:
                station_mt = self._station_machine_type(station_ops, self.ops)
            else:
                station_mt = ""

            candidates = []
            for op_id in available:
                if station_time + self.ops[op_id].duration <= self.cycle_time + 1e-6:
                    # Règle stricte : 1 machine_type par station (sinon séparé)
                    if station_mt and self.ops[op_id].machine_type not in ("", station_mt):
                        continue
                    # Regroupement par section : on verrouille la section dès
                    # la 1re opération de la station
                    if station_section and self.ops[op_id].section and self.ops[op_id].section != station_section:
                        continue
                    if not station_ops and not ws_ok(op_id):
                        continue
                    # La station doit rester tenable par UN ouvrier qualifié
                    if station_ops and worker_skill_sets:
                        need = set(self.ops[op_id].required_skills)
                        for o in station_ops:
                            need.update(self.ops[o].required_skills)
                        if not any(need <= ws_ for ws_ in worker_skill_sets):
                            continue
                    candidates.append(op_id)

            if not candidates and station_mt and not station_ops:
                # Nouvelle station avec un type machine imposé
                for op_id in available:
                    if self.ops[op_id].machine_type:
                        candidates.append(op_id)
                        break

            if not candidates:
                if station_ops:
                    close_station()
                    current_station += 1
                    station_time = 0.0
                    station_ops = []
                    station_section = ""
                    continue
                else:
                    if available:
                        # Station vide : opération > cycle (dédoublée) ou, à défaut,
                        # meilleure candidate même sans poste restant (signalé ensuite)
                        pool = [o for o in available if ws_ok(o)] or available
                        candidates = [max(pool, key=lambda o: rpw.get(o, 0))]
                    else:
                        break

            # Choix : priorité à la section verrouillée, puis RPW décroissant
            if station_section:
                same_section = [o for o in candidates if self.ops[o].section == station_section]
                if same_section:
                    chosen = max(same_section, key=lambda o: rpw.get(o, 0))
                else:
                    chosen = max(candidates, key=lambda o: rpw.get(o, 0))
            else:
                chosen = max(candidates, key=lambda o: rpw.get(o, 0))
                # Verrouille la section sur la 1re opération de la station
                if self.ops[chosen].section:
                    station_section = self.ops[chosen].section

            station_assignments[chosen] = current_station
            assigned.add(chosen)
            station_time += self.ops[chosen].duration
            station_ops.append(chosen)

        if station_ops:
            close_station()

        stations_used = len(station_details)
        
        # Assigner postes physiques et ouvriers (greedy simple)
        warnings = ["Solution RPW (heuristique) - non garantie optimale"]
        self._assign_resources(station_details, station_assignments, warnings)
        
        # KPIs cohérents (cycle réel, opérateurs réels, postes parallèles)
        k = line_kpis(self.problem, station_details)
        issues = precheck(self.problem)
        warnings[1:1] = [str(i) for i in issues if i.severity == "warning"]
        violations = validate_result(self.problem, station_details)
        unassigned = [o.id for o in self.problem.operations if o.id not in station_assignments]
        ok = not violations and not unassigned
        err = ""
        if not ok:
            msgs = [str(v) for v in violations]
            if unassigned:
                msgs.insert(0, f"Opérations non affectées : {', '.join(unassigned)}")
            hints = [str(i) for i in issues if i.severity == "error"]
            err = "Solution non conforme : " + " | ".join(msgs + hints)

        return BalancingResult(
            problem=self.problem,
            success=ok,
            solver_used="RPW",
            solve_time_seconds=time.time() - start_time,
            status="FEASIBLE" if ok else "INFEASIBLE_CONSTRAINTS",
            stations_used=stations_used,
            actual_cycle_time=k["actual_cycle_time"],
            efficiency=k["efficiency"],
            balance_delay=k["balance_delay"],
            smoothness_index=k["smoothness_index"],
            station_details=station_details,
            operation_assignments=station_assignments,
            worker_assignments={wid: f"WS{sd['station']}" for sd in station_details for wid in sd.get("worker_ids", [])},
            warnings=warnings,
            error_message=err,
        )

    def _assign_resources(self, station_details: List[Dict], op_assignments: Dict[str, int], warnings: List[str]):
        """Assigne postes physiques et ouvriers aux stations en respectant
        STRICTEMENT les contraintes :
        - un poste doit posséder TOUTES les machines requises par la station
          (règle '1 machine_type par station' : une station ne mélange pas
          deux types de machines, elles sont séparées par le solveur) ;
        - un ouvrier n'est retenu que s'il maîtrise TOUTES les compétences
          requises par la station, sinon la station reste sans ouvrier
          (signalé par warning)."""
        # Machines requises par station
        station_machines: Dict[int, Set[str]] = {}
        station_skills: Dict[int, Set[str]] = {}
        station_sections: Dict[int, Set[str]] = {}
        for sd in station_details:
            machines_needed = set()
            skills_needed = set()
            sections = set()
            for op_id in sd["operations"]:
                op = self.ops[op_id]
                if op.machine_type:
                    machines_needed.add(op.machine_type)
                skills_needed.update(op.required_skills)
                if op.section:
                    sections.add(op.section)
            station_machines[sd["station"]] = machines_needed
            station_skills[sd["station"]] = skills_needed
            station_sections[sd["station"]] = sections

        # --- Postes physiques : capacité machine STRICTE ---
        used_workstations = set()
        for sd in station_details:
            st = sd["station"]
            needed = station_machines[st]
            sd["workstation"] = ""
            sd["machine_types"] = sorted(needed)
            sd["sections"] = sorted(station_sections[st])
            if not needed:
                # Station sans machine requise : tout poste dispo convient
                for ws in self.problem.workstations:
                    if ws.id in used_workstations or not ws.available:
                        continue
                    sd["workstation"] = ws.id
                    used_workstations.add(ws.id)
                    break
                continue
            # Le poste doit couvrir la machine de la station (x postes parallèles)
            par = int(sd.get("parallel", 1))
            picked = []
            for ws in self.problem.workstations:
                if len(picked) >= par:
                    break
                if ws.id in used_workstations or not ws.available:
                    continue
                if ws.machine_type in needed:
                    picked.append(ws.id)
            if len(picked) == par:
                used_workstations.update(picked)
                sd["workstation"] = picked[0]
                sd["workstations"] = picked
            if not sd["workstation"]:
                warnings.append(
                    f"⚠️ Station {st} : aucun poste disponible pour la/les machine(s) "
                    f"{', '.join(sorted(needed))}"
                )

        # --- Ouvriers : compétences STRICTES, affectation optimale (couplage biparti) ---
        # Chaque station demande `parallel` ouvriers qualifiés ; on résout un couplage
        # maximum (chemins augmentants) au lieu d'un premier-venu glouton.
        slots = []  # (station_detail, skills)
        for sd in station_details:
            sd["workers"] = []
            sd["worker_ids"] = []
            skills_needed = station_skills[sd["station"]]
            if not skills_needed:
                continue
            for _ in range(int(sd.get("parallel", 1))):
                slots.append((sd, skills_needed))
        workers = [w for w in self.problem.workers if w.available]
        # candidats triés : ouvriers les moins polyvalents d'abord (garder les polyvalents)
        cand = [sorted([i for i, w in enumerate(workers) if sk <= set(w.skills)],
                       key=lambda i: len(workers[i].skills)) for _, sk in slots]
        match_w: Dict[int, int] = {}  # worker idx -> slot idx

        def augment(si: int, seen: Set[int]) -> bool:
            for wi in cand[si]:
                if wi in seen:
                    continue
                seen.add(wi)
                if wi not in match_w or augment(match_w[wi], seen):
                    match_w[wi] = si
                    return True
            return False

        # stations les plus contraintes d'abord
        for si in sorted(range(len(slots)), key=lambda i: len(cand[i])):
            augment(si, set())
        for wi, si in sorted(match_w.items(), key=lambda t: t[1]):
            sd = slots[si][0]
            sd["workers"].append(workers[wi].name)
            sd["worker_ids"].append(workers[wi].id)
        for sd in station_details:
            sk = station_skills[sd["station"]]
            if sk and len(sd["worker_ids"]) < int(sd.get("parallel", 1)):
                warnings.append(
                    f"⚠️ Station {sd['station']} : aucun ouvrier ne maîtrise TOUTES les compétences "
                    f"requises ({', '.join(sorted(sk))})"
                )


def solve_rpw(problem: LineBalancingProblem, max_stations: Optional[int] = None) -> BalancingResult:
    """Point d'entrée simple pour RPW."""
    solver = RPWSolver(problem, max_stations)
    return solver.solve()