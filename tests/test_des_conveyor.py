"""Convoyeur suspendu (engine/des/conveyor.py + conveyor_sim.py) : géométrie, conservation, routage des
cintres, limite d'encours, réaffectation dynamique, reproductibilité, scénario chariots vs convoyeur."""
from __future__ import annotations

import math

import pytest

from engine.des import normalize_model, run_experiment, simulate
from engine.des.conveyor import cumulative, flatten, point_at, project
from tests.test_des import line


def ups(times, **cv):
    m = line(times, settings={"dist": {"kind": "constant"}, "handling_min": 0}, source={"bundle_size": 10, "start_wip_bundles": 1})
    m["conveyor"] = {"enabled": True, "carrier_capacity": 2, **cv}
    return m


def test_geometry_rounded_loop_and_projection():
    pts, segs = flatten([(0, 0), (10, 0), (10, 4), (0, 4)], 0.5)
    cum = cumulative(pts)
    # périmètre 28 m moins 4 coins arrondis (2r - quart de cercle ≈ 0,215 m chacun)
    assert 27.0 < cum[-1] < 28.0
    assert pts[0] == pts[-1]
    assert sum(1 for s in segs if s["kind"] == "arc") == 4 and sum(1 for s in segs if s["kind"] == "line") == 4
    s, q, d = project(pts, cum, (5, -1))
    assert d == pytest.approx(1.0, abs=1e-6) and q[0] == pytest.approx(5.0)
    assert math.dist(point_at(pts, cum, s), q) < 1e-6


def test_auto_loop_spurs_and_capacity():
    m = normalize_model(ups([0.5, 0.6, 0.7]))
    c = m["conveyor"]
    assert c["auto_loop"] and c["length_m"] > 5
    assert set(c["spurs"]) == {"1", "2", "3"}
    # les aiguillages se suivent dans l'ordre de la ligne
    assert c["spurs"]["1"]["s"] < c["spurs"]["2"]["s"] < c["spurs"]["3"]["s"]
    assert c["capacity"] == int(c["length_m"] / c["pitch_m"])
    assert m["source"]["bundle_size"] == 2 and all(s["queue_capacity"] == 4 for s in m["stations"])


def test_conservation_routing_and_wip_limit():
    m = ups([0.5, 0.9, 0.6, 0.7], station_wip=3)
    m["settings"]["defect_pct"] = 5
    m["shift"]["breaks"] = [{"start_min": 120, "minutes": 15}]
    r = simulate(m, seed=3)
    assert r["conservation"]["ok"]
    assert r["kpis"]["pieces"] > 300
    k = r["kpis"]
    assert k["rail_util_pct"] > 0 and k["carriers_in_circulation"] > 0 and k["rail_time_avg"] > 0
    assert 0 < k["rail_share_pct"] < 100
    for s in r["stations"]:
        assert s["queue_max"] <= 3 + 1            # dérivation (≤ 3 cintres) + retouche éventuelle forcée
    # chaque cintre neuf passe par les postes dans l'ordre de la gamme
    seq: dict[int, list[int]] = {}
    for ev in r["trace"]["events"]:
        if ev[1] == 1 and ev[3] == 1:              # paquet au poste
            seq.setdefault(ev[2], []).append(ev[4])
    bundles = r["trace"]["bundles"]
    full = [v for b, v in seq.items() if bundles[b][2] == 0 and len(v) == 4]
    assert full and all(v == [0, 1, 2, 3] for v in full)


def test_carriers_are_addressable_and_reused():
    r = simulate(ups([0.4, 0.5], carriers=6), seed=1)
    cv = r["conveyor"]
    assert cv["carriers"] == 6 and cv["carriers_ids"][0] == "C001"
    assert cv["trips"] >= r["kpis"]["pieces"] // 2 - 1   # 2 pièces par cintre
    used = {ev[2] for ev in r["trace"]["events"] if ev[1] in (4, 5)}
    assert used == set(range(6))
    assert r["conservation"]["ok"]


def test_dynamic_reassignment_to_least_loaded_qualified_station():
    times = [0.4, 1.0, 1.0, 0.4]
    m = ups(times)
    # postes 2 et 3 : même opération (partagée par l'équilibrage) → interchangeables
    m["stations"][1]["operations"] = ["Piquer dos"]
    m["stations"][2]["operations"] = ["Piquer dos"]
    m["operators"] = [{"id": "W2", "name": "Lente", "efficiency": 0.5, "stations": ["2"]}]
    dyn = simulate(m, seed=5)
    m["conveyor"]["dynamic_routing"] = False
    fixed = simulate(m, seed=5)
    assert dyn["kpis"]["reassigned"] > 0 and fixed["kpis"]["reassigned"] == 0
    assert dyn["conservation"]["ok"] and fixed["conservation"]["ok"]
    # poste 2 lent (rendement 50 %) : le poste 3 reprend une partie de ses cintres
    assert fixed["kpis"]["pieces"] < 260 and dyn["kpis"]["pieces"] > 320


def test_explicit_alternates_respect_competence():
    m = ups([0.4, 1.2, 0.4, 0.4], alternates={"2": ["4"]})
    m["stations"][3]["operators"] = []            # poste 4 sans opératrice : jamais choisi
    m["stations"][3]["minutes"] = 0.4
    r = simulate(m, seed=2)
    assert r["kpis"]["reassigned"] == 0


def test_reproducible_with_seed():
    m = ups([0.5, 0.8, 0.6])
    m["settings"]["dist"] = {"kind": "lognormal", "cv": 0.3}
    a, b, c = simulate(m, seed=9), simulate(m, seed=9), simulate(m, seed=10)
    assert a["kpis"] == b["kpis"] and a["trace"]["events"] == b["trace"]["events"]
    assert a["kpis"] != c["kpis"]


def test_scenario_trolleys_vs_overhead_conveyor():
    m = line([0.5, 0.9, 0.7, 0.8], settings={"dist": {"kind": "normal", "cv": 0.1}},
             source={"bundle_size": 10, "start_wip_bundles": 2})
    exp = run_experiment(m, [{"name": "Paquets", "overrides": {}},
                             {"name": "UPS", "overrides": {"conveyor": {"enabled": True, "carrier_capacity": 1}}}],
                         replications=2, trace=False)
    rows = {r["key"]: r["values"] for r in exp["comparison"]}
    assert rows["rail_util_pct"][0]["mean"] is None and rows["rail_util_pct"][1]["mean"] > 0
    # le convoyeur (pièce à pièce) réduit fortement l'encours et le temps de traversée
    assert rows["wip_avg"][1]["mean"] < rows["wip_avg"][0]["mean"] / 2
    assert rows["lead_time_avg"][1]["mean"] < rows["lead_time_avg"][0]["mean"] / 2
    assert exp["scenarios"][1]["result"]["model"]["conveyor"]["enabled"]


def test_rail_saturation_does_not_deadlock():
    # beaucoup de cintres sur un rail court : accumulation, mais la ligne continue de produire
    m = ups([0.3, 1.5, 0.3], carriers=80, pitch_m=0.5, station_wip=2)
    r = simulate(m, seed=4)
    assert r["conservation"]["ok"]
    assert r["kpis"]["pieces"] > 250
    assert r["conveyor"]["rail_max"] <= r["conveyor"]["capacity"]


def test_rail_drawn_on_workshop_plan():
    from engine.des.builder import conveyor_from_plan
    plan = {"elements": [{"id": "r1", "kind": "rail", "pts": [[0, 3], [8, 3], [8, -2], [0, -2]], "height": 2.4,
                          "radius": 0.6, "label": "UPS ligne 1"}]}
    c = conveyor_from_plan(plan)
    assert c["enabled"] and c["height_m"] == 2.4 and c["corner_radius_m"] == 0.6
    m = line([0.5, 0.6, 0.7])
    m["conveyor"] = c
    n = normalize_model(m)["conveyor"]
    assert not n["auto_loop"] and n["loop"][0] == [0.0, 3.0] and 23 < n["length_m"] < 26
    assert conveyor_from_plan({"elements": []}) == {"enabled": False}


def test_competence_based_alternates():
    m = ups([0.4, 1.2, 0.4, 0.6])
    m["stations"][1].update(skills=["piquer"], machine_types=["Piqueuse plate"])
    m["stations"][3].update(skills=["piquer", "surjeter"], machine_types=["Piqueuse plate", "Surjeteuse"])
    m["stations"][2].update(skills=["repasser"], machine_types=["Table à repasser"])
    m["operators"] = [{"id": "W4", "stations": ["4"], "skills": ["piquer", "surjeter"]},
                      {"id": "W3", "stations": ["3"], "skills": ["piquer"]}]
    c = normalize_model(m)["conveyor"]
    # poste 4 : compétence + piqueuse → peut reprendre le poste 2 ; poste 3 : compétence mais pas la machine
    assert c["alternates"].get("2") == ["4"]
    assert "4" not in c["alternates"] and "3" not in c["alternates"]
    r = simulate(m, seed=1)
    assert r["kpis"]["reassigned"] > 0 and r["conservation"]["ok"]
