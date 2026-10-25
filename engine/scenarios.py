"""
Comparaison de scénarios (analyse what-if) pour l'aide à la décision.

Exécute le même problème d'équilibrage sous plusieurs configurations
(temps de cycle, nombre de postes, solveur) et produit un tableau
comparatif : le décideur peut ainsi arbitrer entre effectif, cadence
et efficacité — le cœur de la décision en usine de confection.
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from typing import Callable, Optional

from engine.models import BalancingResult, LineBalancingProblem, SolverAlgorithm
from engine.capacity import (
    CapacityAnalysis, ProductionTarget, analyze_capacity,
)
from engine.recommendations import generate_recommendations


# ── Définition d'un scénario ────────────────────────────────────────

@dataclass
class Scenario:
    """Une configuration à tester."""
    name: str
    cycle_time: float                      # Temps de cycle cible (min)
    solver: str = "rpw"                    # "rpw" | "cp_sat" | "cp-sat"
    time_limit_seconds: int = 60
    max_stations: Optional[int] = None

    @staticmethod
    def from_cycle_times(
        cycle_times: list[float],
        solver: str = "rpw",
        time_limit_seconds: int = 60,
    ) -> list["Scenario"]:
        """Crée un scénario par temps de cycle (usage CLI/GUI)."""
        return [
            Scenario(name=f"cycle={ct:g}", cycle_time=ct,
                     solver=solver, time_limit_seconds=time_limit_seconds)
            for ct in cycle_times
        ]

    @staticmethod
    def workforce_sweep(
        total_sam: float,
        takt: float,
        operators: list[int],
        line_efficiency: float = 0.85,
        solver: str = "rpw",
        time_limit_seconds: int = 60,
    ) -> list["Scenario"]:
        """
        Un scénario par niveau d'effectif : cycle imposé = SAM / (N × eff),
        ce qui revient à demander « N opérateurs suffisent-ils ? ».
        """
        scenarios = []
        for n in operators:
            if n <= 0:
                continue
            cycle = total_sam / (n * max(0.1, line_efficiency))
            scenarios.append(Scenario(
                name=f"{n} opérateurs", cycle_time=round(cycle, 3),
                solver=solver, time_limit_seconds=time_limit_seconds,
                max_stations=n,
            ))
        return scenarios


# ── Résultats ───────────────────────────────────────────────────────

@dataclass
class ScenarioOutcome:
    """Résultat d'un scénario exécuté."""
    scenario: Scenario
    result: BalancingResult
    capacity: Optional[CapacityAnalysis] = None

    @property
    def ok(self) -> bool:
        return bool(self.result and self.result.success)

    @property
    def feasible_vs_target(self) -> bool:
        return bool(self.capacity and self.capacity.feasible)


@dataclass
class ScenarioComparison:
    """Tableau comparatif de plusieurs scénarios."""
    problem_name: str
    outcomes: list[ScenarioOutcome] = field(default_factory=list)
    target: Optional[ProductionTarget] = None

    def best(self) -> Optional[ScenarioOutcome]:
        """
        Meilleur scénario : faisable (vs commande si fournie) en priorité,
        puis efficacité max, puis moins de postes.
        """
        candidates = [o for o in self.outcomes if o.ok]
        if not candidates:
            return None
        if self.target is not None:
            feasible = [o for o in candidates if o.feasible_vs_target]
            if feasible:
                candidates = feasible
        return min(
            candidates,
            key=lambda o: (-o.result.efficiency, o.result.stations_used),
        )

    def table(self) -> tuple[list[str], list[list[str]]]:
        """(header, rows) pour affichage console / export."""
        header = ["Scénario", "Solveur", "Cycle cible", "Cycle réel", "Postes",
                  "Effic. %", "Delay %", "SI"]
        if self.target is not None:
            header += ["pcs/j projeté", "Verdict"]
        rows = []
        for o in self.outcomes:
            r = o.result
            if not o or not r:
                continue
            if not o.ok:
                row = [o.scenario.name, o.scenario.solver,
                       f"{o.scenario.cycle_time:.2f}", "—", "ÉCHEC", "", "", ""]
                if self.target is not None:
                    row += ["—", "INFAISABLE"]
                rows.append(row)
                continue
            row = [o.scenario.name, r.solver_used, f"{o.scenario.cycle_time:.2f}",
                   f"{r.actual_cycle_time:.2f}", str(r.stations_used),
                   f"{r.efficiency:.1f}", f"{r.balance_delay:.1f}",
                   f"{r.smoothness_index:.2f}"]
            if self.target is not None:
                cap = o.capacity
                row += [
                    f"{cap.projected_daily_output:.0f}" if cap else "—",
                    cap.verdict if cap else "—",
                ]
            rows.append(row)
        return header, rows

    def summary(self) -> str:
        lines = [f"🔀 COMPARAISON DE SCÉNARIOS — {self.problem_name}"]
        header, rows = self.table()
        widths = [max(len(header[i]), max((len(r[i]) for r in rows), default=0))
                  for i in range(len(header))]
        fmt = "  " + " | ".join(f"{{:<{w}}}" for w in widths)
        lines.append(fmt.format(*header))
        lines.append("  " + "-+-".join("-" * w for w in widths))
        for r in rows:
            lines.append(fmt.format(*r))
        best = self.best()
        if best:
            lines.append("")
            lines.append(
                f"🏆 Scénario recommandé : {best.scenario.name} "
                f"(cycle {best.result.actual_cycle_time:.2f} min, "
                f"{best.result.stations_used} postes, "
                f"efficacité {best.result.efficiency:.1f}%)"
            )
        return "\n".join(lines)


# ── Exécution ───────────────────────────────────────────────────────

def _normalize_solver_name(name: str) -> str:
    return {"cp-sat": "cp_sat", "cpsat": "cp_sat", "r.p.w": "rpw"}.get(
        name.lower().strip(), name.lower().strip())


def _solve_one(scenario: Scenario, problem: LineBalancingProblem) -> BalancingResult:
    """Exécute un scénario sur une copie du problème."""
    p = copy.deepcopy(problem)
    p.target_cycle_time = scenario.cycle_time
    if scenario.max_stations:
        p.max_stations = scenario.max_stations
    solver = _normalize_solver_name(scenario.solver)
    try:
        if solver == "rpw":
            from engine.solvers import solve_rpw
            return solve_rpw(p, max_stations=scenario.max_stations)
        if solver == "cp_sat":
            from engine.solvers import solve_cp_sat
            p.algorithm = SolverAlgorithm.CP_SAT
            return solve_cp_sat(p, time_limit_seconds=scenario.time_limit_seconds)
    except Exception as e:  # solveur indisponible, erreur interne...
        return BalancingResult(
            problem=p, success=False, solver_used=solver.upper(),
            solve_time_seconds=0.0, status="ERROR", error_message=str(e),
        )
    return BalancingResult(
        problem=p, success=False, solver_used=solver.upper(),
        solve_time_seconds=0.0, status="ERROR",
        error_message=f"Solveur inconnu: {solver}",
    )


def run_scenarios(
    problem: LineBalancingProblem,
    scenarios: list[Scenario],
    target: Optional[ProductionTarget] = None,
    labor_cost_per_minute: Optional[float] = None,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
    with_recommendations: bool = False,
) -> ScenarioComparison:
    """
    Exécute les scénarios et retourne le comparatif.

    progress_cb(i, n, name) appelé avant chaque scénario (GUI/CLI).
    """
    comp = ScenarioComparison(problem_name=problem.name, target=target)
    n = len(scenarios)
    for i, sc in enumerate(scenarios):
        if progress_cb:
            progress_cb(i, n, sc.name)
        result = _solve_one(sc, problem)
        capacity = None
        if target is not None:
            capacity = analyze_capacity(result, target, labor_cost_per_minute)
            result.capacity = capacity
        if with_recommendations and result.success:
            result.recommendations = generate_recommendations(result, target)
        comp.outcomes.append(ScenarioOutcome(scenario=sc, result=result, capacity=capacity))
    if progress_cb:
        progress_cb(n, n, "terminé")
    return comp
