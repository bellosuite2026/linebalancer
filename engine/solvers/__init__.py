"""
Package solveurs pour équilibrage de ligne.

Expose un registre uniforme (SolverRegistry) permettant d'appeler n'importe
quel solveur par nom : `solve("cp_sat", problem, time_limit_seconds=30)`.

Ajouter un solveur = créer un module + l'enregistrer via
`register_solver("mon_solveur", solve_mon_solveur)`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from engine.models import LineBalancingProblem, BalancingResult


@dataclass
class SolverEntry:
    name: str
    callable: Callable[..., BalancingResult]
    description: str = ""
    requires_ortools: bool = False


class SolverRegistry:
    """Registre central des solveurs d'équilibrage."""

    def __init__(self) -> None:
        self._solvers: dict[str, SolverEntry] = {}

    def register(
        self,
        name: str,
        func: Callable[..., BalancingResult],
        description: str = "",
        requires_ortools: bool = False,
    ) -> None:
        self._solvers[name] = SolverEntry(
            name=name, callable=func, description=description,
            requires_ortools=requires_ortools,
        )

    def names(self) -> list[str]:
        return sorted(self._solvers.keys())

    def is_available(self, name: str) -> bool:
        entry = self._solvers.get(name)
        if entry is None:
            return False
        if entry.requires_ortools and not ORTOOLS_AVAILABLE:
            return False
        return True

    def get(self, name: str) -> Optional[SolverEntry]:
        return self._solvers.get(name)

    def solve(self, name: str, problem: LineBalancingProblem, **options) -> BalancingResult:
        entry = self._solvers.get(name)
        if entry is None:
            raise KeyError(f"Solveur inconnu: '{name}'. Disponibles: {self.names()}")
        if entry.requires_ortools and not ORTOOLS_AVAILABLE:
            raise RuntimeError(
                f"Le solveur '{name}' requiert OR-Tools (pip install ortools)"
            )
        return entry.callable(problem, **options)


# Instance globale du registre
registry = SolverRegistry()


# --- Enregistrement des solveurs existants -------------------------------
from engine.solvers.rpw_solver import solve_rpw  # noqa: E402

try:
    from engine.solvers.cpsat_solver import solve_cp_sat, ORTOOLS_AVAILABLE  # noqa: E402
except ImportError:  # pragma: no cover
    solve_cp_sat = None  # type: ignore
    ORTOOLS_AVAILABLE = False  # type: ignore

if solve_cp_sat is not None:
    registry.register(
        "cp_sat", solve_cp_sat,
        description="OR-Tools CP-SAT (optimal, contraintes complètes)",
        requires_ortools=True,
    )

registry.register(
    "rpw", solve_rpw,
    description="Ranked Positional Weight (heuristique rapide)",
)


def solve(name: str, problem: LineBalancingProblem, **options) -> BalancingResult:
    """Raccourci : résout via le registre global."""
    return registry.solve(name, problem, **options)


def find_min_cycle(problem: LineBalancingProblem, solver: str = "rpw",
                   precision: float = 0.05, **options):
    """Plus petit temps de cycle (min/pièce) pour lequel le solveur trouve une
    solution conforme. Recherche dichotomique ; renvoie (cycle, résultat) ou (None, None)."""
    import copy
    from collections import Counter
    ops = problem.operations
    total = sum(o.duration for o in ops)
    if not ops:
        return None, None
    lo = max(total / max(1, len([w for w in problem.workers if w.available]) or len(ops)), 1e-3)
    cnt = Counter(w.machine_type for w in problem.workstations if w.available)
    if cnt:
        load = Counter()
        for o in ops:
            if o.machine_type:
                load[o.machine_type] += o.duration
        for m, l in load.items():
            if cnt.get(m):
                lo = max(lo, l / cnt[m])
    hi = max(total, lo) * 1.01

    def run(c):
        p = copy.copy(problem)
        p.target_cycle_time = c
        r = solve(solver, p, **options)
        return r if r.success else None

    best = run(hi)
    if best is None:
        return None, None
    best_c = hi
    while hi - lo > precision:
        mid = (lo + hi) / 2
        r = run(mid)
        if r is not None:
            hi, best, best_c = mid, r, mid
        else:
            lo = mid
    return round(best_c, 3), best


__all__ = [
    "find_min_cycle",
    "SolverRegistry", "registry", "solve",
    "solve_rpw", "solve_cp_sat", "ORTOOLS_AVAILABLE",
]
