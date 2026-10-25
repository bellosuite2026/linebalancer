"""
Worker d'équilibrage (thread) pour exécuter les solveurs hors UI.

Extrait de gui/main.py (Phase 2 - découpage GUI). BalanceRunner hérite de
QObject et tourne dans un QThread ; il émet les signaux log/progress/
finished/error consommés par MainWindow.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, Signal

from engine.models import (
    Operation, Workstation, Worker, LineBalancingProblem,
    BalancingResult, OptimizationObjective, SolverAlgorithm,
)
from engine.solvers import solve_rpw, solve_cp_sat, ORTOOLS_AVAILABLE
from engine.simulation import SimulationEngine, SimulationConfig, SimulationResult



# ============================================================
# BALANCE RUNNER (Thread worker)
# ============================================================

class BalanceRunner(QObject):
    log = Signal(str)
    progress = Signal(int)
    finished = Signal(BalancingResult)
    error = Signal(str)

    def __init__(self):
        super().__init__()
        self._stop = False

    def stop(self):
        self._stop = True

    def run_balance(self, project_data: dict, solver_name: str, cycle_time: float,
                        max_stations: int, objective: str, time_limit: int):
            self._stop = False
            try:
                self.log.emit("🔄 Parsing projet...")
                self.progress.emit(10)

                # Parse operations
                operations = []
                workstations = []
                workers = []

                import re as _re
                def _split_multi(val: str, sep: str = "[;,]+") -> list[str]:
                    return [x.strip() for x in _re.split(sep, val) if x.strip()] if val else []

                for node in project_data.get("nodes", []):
                    if not node.get("enabled", True):
                        continue
                    cfg = node.get("config", {})
                    if node["type"] == "operation":
                        operations.append(Operation(
                            id=cfg.get("op_id", node["id"]),
                            name=cfg.get("name", node["title"]),
                            duration=cfg.get("duration", 0),
                            predecessors=_split_multi(cfg.get("predecessors", "")),
                            machine_type=cfg.get("machine_type", ""),
                            required_skills=_split_multi(cfg.get("skills", "")),
                            section=cfg.get("section", ""),
                            task_type=cfg.get("task_type", "VA"),
                        ))
                    elif node["type"] == "workstation":
                        workstations.append(Workstation(
                            id=cfg.get("ws_id", node["id"]),
                            name=cfg.get("name", node["title"]),
                            machine_type=cfg.get("machine_type", ""),
                            available=cfg.get("available", True),
                            max_workers=cfg.get("max_workers", 1),
                            section=cfg.get("section", ""),
                        ))
                    elif node["type"] == "worker":
                        workers.append(Worker(
                            id=cfg.get("worker_id", node["id"]),
                            name=cfg.get("name", node["title"]),
                            skills=_split_multi(cfg.get("skills", "")),
                            efficiency=cfg.get("efficiency", 1.0),
                            available=cfg.get("available", True),
                        ))

                self.log.emit(f"   Operations: {len(operations)}, Postes: {len(workstations)}, Ouvriers: {len(workers)}")
                self.progress.emit(30)

                if not operations:
                    raise ValueError("Aucune operation definie dans le projet")

                # Map objective string to enum
                obj_map = {
                    "min_stations": OptimizationObjective.MIN_STATIONS,
                    "min_cycle_time": OptimizationObjective.MIN_CYCLE_TIME,
                    "max_efficiency": OptimizationObjective.MAX_EFFICIENCY,
                    "balance_workload": OptimizationObjective.BALANCE_WORKLOAD,
                }
                alg_map = {
                    "rpw": SolverAlgorithm.RPW,
                    "cp-sat": SolverAlgorithm.CP_SAT,
                }

                problem = LineBalancingProblem(
                    name="Projet GUI",
                    target_cycle_time=cycle_time,
                    operations=operations,
                    workstations=workstations,
                    workers=workers,
                    max_stations=max_stations if max_stations > 0 else None,
                    algorithm=alg_map.get(solver_name, SolverAlgorithm.RPW),
                    objective=obj_map.get(objective, OptimizationObjective.MIN_STATIONS),
                    time_limit_seconds=time_limit,
                )

                self.log.emit(f"🚀 Resolution avec {solver_name.upper()}...")
                self.progress.emit(50)
                if solver_name == "cp-sat":
                    if not ORTOOLS_AVAILABLE:
                        raise RuntimeError("OR-Tools non installe. Utilisez RPW ou installez ortools.")
                    result = solve_cp_sat(problem, time_limit_seconds=time_limit)
                else:
                    result = solve_rpw(problem)

                self.progress.emit(90)
                self.log.emit(f"✅ Termine: {result.summary()}")
                self.finished.emit(result)

            except Exception as e:
                self.log.emit(f"❌ Erreur: {e}")
                self.error.emit(str(e))


# ============================================================
# SIMULATION RUNNER (Thread worker)
# ============================================================

class SimulationRunner(QObject):
    log = Signal(str)
    progress = Signal(int)
    finished = Signal(SimulationResult)
    error = Signal(str)

    def __init__(self):
        super().__init__()
        self._stop = False

    def stop(self):
        self._stop = True

    def run_simulation(self, result: BalancingResult, num_parts: int = 100):
        self._stop = False
        try:
            self.log.emit("🔄 Simulation SimPy...")
            self.progress.emit(10)

            config = SimulationConfig(
                num_parts=num_parts,
                variability=0.1,
                transport_time_min=0.3,
            )
            engine = SimulationEngine(result, config)
            self.progress.emit(30)
            self.log.emit(f"   {len(result.problem.operations)} operations, {result.stations_used} postes")

            sim_result = engine.run()
            self.progress.emit(90)

            if sim_result.success:
                self.log.emit(f"✅ {sim_result.summary()}")
            else:
                self.log.emit(f"❌ Simulation echouee: {sim_result.error_message}")

            self.finished.emit(sim_result)

        except Exception as e:
            self.log.emit(f"❌ Erreur simulation: {e}")
            self.error.emit(str(e))


# ============================================================
