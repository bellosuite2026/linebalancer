"""Moteur v2.2 : postes multi-machines, opérations partagées, ouvriers par
compétences + rendement, correction de l'affectation des postes CP-SAT."""
from __future__ import annotations

import copy

import pytest

from engine.diagnostics import precheck, validate_result
from engine.models import LineBalancingProblem, Operation, Worker, Workstation
from engine.resources import assign_workstations, op_efficiency, split_durations
from engine.solvers import ORTOOLS_AVAILABLE, solve

SOLVERS = ["rpw"] + (["cp_sat"] if ORTOOLS_AVAILABLE else [])
OPTS = {"rpw": {}, "cp_sat": {"time_limit_seconds": 5}}

# Gamme « dos de pantalon » (7 opérations, 7 postes de types différents) : cas réel
# où l'ancien moteur faisait 7 stations à 1 opération (charges 18-84 %).
OPS = [
    ("OP010", "Thermofixer ceintures / renforts dos", 2.1, [], "Thermo-presse", "oper_tissu", "Finissage"),
    ("OP020", "Marquer pinces dos", 1.8, ["OP010"], "Marqueur auto", "oper_precis", "Traçage"),
    ("OP030", "Piquer pinces dos", 3.5, ["OP020"], "Piqueuse plate", "piquer", "Couture"),
    ("OP040", "Assemblage milieu dos (fourche)", 4.2, ["OP030"], "Surjeteuse 4-fils", "surjeter", "Couture"),
    ("OP050", "Surpiquer milieu dos", 2.7, ["OP040"], "Piqueuse double aiguille", "piquer_surpiquer", "Couture"),
    ("OP060", "Poser et plaquer poches dos", 3.1, ["OP050"], "Piqueuse plate", "piquer", "Couture"),
    ("OP070", "Fixer passants ceintures dos", 0.9, ["OP060"], "Machine à passants", "machine_passant", "Montage"),
]
WS = [("WS01", "Thermo-presse", "Finissage"), ("WS02", "Marqueur auto", "Traçage"),
      ("WS03", "Piqueuse plate", "Couture"), ("WS04", "Surjeteuse 4-fils", "Couture"),
      ("WS05", "Piqueuse double aiguille", "Couture"), ("WS06", "Piqueuse plate", "Couture"),
      ("WS07", "Machine à passants", "Montage")]
REAL_WORKERS = [("W001", "Operateur Thermo", ["oper_tissu"]), ("W002", "Operateur Tracage", ["oper_precis"]),
                ("W003", "Piqueuse 01", ["piquer", "surjeter"]), ("W004", "Surjeteuse 01", ["surjeter", "piquer"]),
                ("W005", "Piqueuse Double", ["piquer_surpiquer"]), ("W006", "Operateur Passants", ["machine_passant"])]


def dos_pantalon(workers="none", **kw) -> LineBalancingProblem:
    ops = [Operation(id=i, name=n, duration=d, predecessors=list(p), machine_type=m,
                     required_skills=[s], section=sec) for i, n, d, p, m, s, sec in OPS]
    wss = [Workstation(id=i, name=i, machine_type=m, section=sec) for i, m, sec in WS]
    if workers == "real":
        wk = [Worker(id=i, name=n, skills=list(s)) for i, n, s in REAL_WORKERS]
    elif workers == "poly":
        allsk = sorted({o.required_skills[0] for o in ops})
        wk = [Worker(id=f"P{i}", name=f"Poly {i}", skills=allsk, efficiency=e)
              for i, e in enumerate([1.0, 0.9, 1.15, 0.95, 1.05, 1.0])]
    else:
        wk = []
    p = LineBalancingProblem(name="dos pantalon", target_cycle_time=5.0, operations=ops,
                             workstations=wss, workers=wk)
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def station_of(r, op):
    return r.operation_assignments[op]


@pytest.mark.parametrize("solver", SOLVERS)
@pytest.mark.parametrize("workers", ["none", "poly"])
def test_light_operations_are_grouped(solver, workers):
    r = solve(solver, dos_pantalon(workers), **OPTS[solver])
    assert r.success, r.error_message
    assert r.stations_used == 5            # au lieu de 7
    assert station_of(r, "OP010") == station_of(r, "OP020")
    assert station_of(r, "OP060") == station_of(r, "OP070")
    assert r.efficiency == pytest.approx(73.2, abs=0.2)
    st1 = r.station_details[station_of(r, "OP010") - 1]
    assert st1["workstations"] == ["WS01", "WS02"]   # un ouvrier tient 2 machines voisines
    assert not validate_result(r.problem, r.station_details)


@pytest.mark.parametrize("solver", SOLVERS)
def test_efficient_workers_on_heaviest_stations(solver):
    r = solve(solver, dos_pantalon("poly"), **OPTS[solver])
    heavy = r.station_details[station_of(r, "OP040") - 1]      # 4.2 min
    assert heavy["worker_ids"] == ["P2"]                      # rendement 1.15
    assert heavy["worker_time"] == pytest.approx(4.2 / 1.15, abs=0.01)


@pytest.mark.parametrize("solver", SOLVERS)
def test_one_machine_per_station_legacy(solver):
    r = solve(solver, dos_pantalon("none", max_machines_per_station=1), **OPTS[solver])
    assert r.success and r.stations_used == 7


@pytest.mark.parametrize("solver", SOLVERS)
def test_machine_change_time_counts(solver):
    # 1.2 min de déplacement : OP010+OP020 = 3.9 + 1.2 > 5 -> plus regroupés
    r = solve(solver, dos_pantalon("none", machine_change_time=1.2), **OPTS[solver])
    assert r.success
    assert station_of(r, "OP010") != station_of(r, "OP020")
    for sd in r.station_details:
        assert sd["total_time"] <= 5.0 + 1e-6


def test_real_workers_skill_capacity_is_diagnosed():
    """Avec l'effectif réel, piquer/surjeter (10,8 min) n'ont que 2 ouvriers : la
    cadence 5 est intenable, le diagnostic le dit avant tout calcul."""
    issues = precheck(dos_pantalon("real"))
    cap = [i for i in issues if i.code == "SKILL_CAPACITY"]
    assert cap and "OP030" in cap[0].message and "OP060" in cap[0].message
    r = solve("rpw", dos_pantalon("real"))
    assert not r.success and "SKILL_CAPACITY" in r.error_message


@pytest.mark.parametrize("solver", SOLVERS)
def test_real_workers_with_two_trainings(solver):
    p = dos_pantalon("real")
    p.workers[0].skills.append("oper_precis")    # thermo -> + marquage
    p.workers[5].skills.append("piquer")         # passants -> + piqûre plate
    r = solve(solver, p, **OPTS[solver])
    assert r.success, r.error_message
    assert r.stations_used == 5
    assert r.station_details[station_of(r, "OP010") - 1]["worker_ids"] == ["W001"]
    assert r.station_details[station_of(r, "OP070") - 1]["worker_ids"] == ["W006"]


def _long_op_problem(mode):
    ops = [Operation(id="A", name="A", duration=2.0, machine_type="plate", required_skills=["c"]),
           Operation(id="B", name="B", duration=7.0, predecessors=["A"], machine_type="surj", required_skills=["s"]),
           Operation(id="C", name="C", duration=2.5, predecessors=["B"], machine_type="plate", required_skills=["c"])]
    ws = [Workstation(id=f"P{i}", name="", machine_type="plate") for i in range(2)] + \
         [Workstation(id=f"S{i}", name="", machine_type="surj") for i in range(2)]
    wk = [Worker(id="W1", name="Ali", skills=["c", "s"]), Worker(id="W2", name="Bob", skills=["s"]),
          Worker(id="W3", name="Cy", skills=["c", "s"])]
    return LineBalancingProblem(name="t", target_cycle_time=5.0, operations=ops, workstations=ws,
                                workers=wk, split_mode=mode)


def test_split_durations():
    assert split_durations(7.0, 5.0) == [5.0, pytest.approx(2.0)]
    assert split_durations(10.0, 5.0) == [5.0, 5.0]
    assert split_durations(4.0, 5.0) == [4.0]


@pytest.mark.parametrize("solver", SOLVERS)
def test_long_operation_shared_between_workers(solver):
    """B (7 min > cadence 5) : 5 min pour un ouvrier, le reliquat de 2 min est combiné
    avec une autre opération -> 3 ouvriers au lieu de 4 en dédoublement égal."""
    r = solve(solver, _long_op_problem("share"), **OPTS[solver])
    assert r.success, r.error_message
    assert sum(sd["parallel"] for sd in r.station_details) == 3
    shared = [sd for sd in r.station_details if "B" in sd["operations"]]
    assert len(shared) == 2
    assert sorted(sd["shares"]["B"] for sd in shared) == [pytest.approx(2.0), pytest.approx(5.0)]
    assert any("partagée" in w for w in r.warnings)
    assert set(r.operation_assignments) == {"A", "B", "C"}


def test_parallel_mode_needs_more_workers():
    r = solve("rpw", _long_op_problem("parallel"))
    assert not r.success  # 2 postes parallèles + A + C = 4 ouvriers, 3 disponibles


def test_skill_levels_matrix():
    w = Worker(id="W", name="W", skills=["piquer", "surjeter"], efficiency=1.0,
               skill_levels={"surjeter": 0.8})
    assert op_efficiency(w, Operation(id="a", name="", duration=1, required_skills=["surjeter"])) == 0.8
    assert op_efficiency(w, Operation(id="b", name="", duration=1, required_skills=["piquer"])) == 1.0


def test_manual_station_does_not_steal_a_machine():
    """Ancien bug CP-SAT (_assign_workstations glouton) : une station manuelle
    prenait une piqueuse dont une autre station avait besoin."""
    ops = {o.id: o for o in [
        Operation(id="M", name="manuel", duration=4.0),
        Operation(id="P1", name="", duration=4.0, machine_type="plate"),
        Operation(id="P2", name="", duration=4.0, machine_type="plate")]}
    prob = LineBalancingProblem(name="t", target_cycle_time=5.0, operations=list(ops.values()),
                                workstations=[Workstation(id="A", name="", machine_type="plate"),
                                              Workstation(id="B", name="", machine_type="plate")],
                                workers=[])
    sds = [{"station": i + 1, "total_time": 4.0, "operations": [o], "parallel": 1} for i, o in
           enumerate(["M", "P1", "P2"])]
    assign_workstations(prob, sds, ops)
    assert sds[1]["workstations"] == ["A"] and sds[2]["workstations"] == ["B"]
    assert not sds[0]["workstation"]
    assert not validate_result(prob, sds)   # station manuelle sans poste : pas une violation


@pytest.mark.skipif(not ORTOOLS_AVAILABLE, reason="OR-Tools non installé")
def test_cp_sat_chemise_always_has_workstations():
    from pathlib import Path
    from engine.parsers import parse_sam_file, parse_workers_file, parse_workstations_file
    d = Path(__file__).resolve().parent.parent / "data" / "samples"
    ops = parse_sam_file(d / "sam_chemise_homme.csv")
    ops = ops[0] if isinstance(ops, tuple) else ops
    p = LineBalancingProblem(name="c", target_cycle_time=4.5, operations=ops,
                             workstations=parse_workstations_file(d / "workstations_chemise.csv"),
                             workers=parse_workers_file(d / "workers_chemise.csv"))
    for seed_workers in (8, 4, 1):
        r = solve("cp_sat", copy.copy(p), time_limit_seconds=5, num_workers=seed_workers)
        assert r.success, r.error_message
        assert not validate_result(p, r.station_details)
