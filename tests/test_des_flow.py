"""Logique par blocs (engine/des/flow.py) : validation, conservation des pièces, séparation /
assemblage, décisions, contrôle-retouche, groupage, ressources, génération depuis la gamme,
reproductibilité."""
from __future__ import annotations

import pytest

from engine.des.flow import FlowError, from_plan, run_flow_experiment, simulate_flow, validate


def G(blocks, edges, **kw):
    g = {"blocks": [{"id": b[0], "type": b[1], "params": b[2] if len(b) > 2 else {}} for b in blocks],
         "edges": [{"from": a, "port": p, "to": b} for a, p, b in edges],
         "shift": {"minutes": 480, "breaks": []}, "settings": {"dist": {"kind": "constant"}, "seed": 1}}
    g.update(kw)
    return g


def line(minutes=(1.0,), **src):
    blocks = [("s", "source", {"bundle_size": 10, "wip_cap": 50, **src})]
    edges, prev = [], "s"
    for i, m in enumerate(minutes):
        blocks.append((f"o{i}", "operation", {"minutes": m}))
        edges.append((prev, 0, f"o{i}"))
        prev = f"o{i}"
    blocks.append(("k", "sink"))
    edges.append((prev, 0, "k"))
    return G(blocks, edges)


def test_single_operation_analytical():
    r = simulate_flow(line([1.0]))
    assert r["kpis"]["pieces"] == 470          # 47 paquets de 10 finis avant 480
    assert r["conservation"]["ok"]
    op = next(b for b in r["blocks"] if b["id"] == "o0")
    assert op["utilization_pct"] == pytest.approx(100, abs=0.5)


def test_validation_errors_and_warnings():
    v = validate(G([("s", "source"), ("o", "operation"), ("x", "operation"), ("k", "sink")],
                   [("s", 0, "o"), ("o", 0, "k")]))
    assert not v["ok"] and any("orpheline" in e["msg"] for e in v["errors"])
    v = validate(G([("s", "source"), ("a", "operation"), ("b", "operation"), ("k", "sink"), ("d", "decision")],
                   [("s", 0, "a"), ("a", 0, "b"), ("b", 0, "a"), ("d", 0, "k"), ("d", 1, "k")]))
    assert any("Cycle" in e["msg"] for e in v["errors"])
    # boucle de retouche via un contrôle : simple avertissement
    v = validate(G([("s", "source"), ("c", "inspect", {"minutes": 0.5, "defect_pct": 5}), ("r", "operation", {"minutes": 1}),
                    ("k", "sink")], [("s", 0, "c"), ("c", 0, "k"), ("c", 1, "r"), ("r", 0, "c")]))
    assert v["ok"] and v["warnings"]
    v = validate(G([("s", "source"), ("j", "join"), ("k", "sink")], [("s", 0, "j"), ("j", 0, "k")]))
    assert any("au moins 2" in e["msg"] for e in v["errors"])
    with pytest.raises(FlowError):
        simulate_flow(G([("s", "source")], []))


def test_split_and_assembly_conserve_pieces():
    g = G([("s", "source", {"bundle_size": 10, "wip_cap": 6}),
           ("sp", "split", {"components": ["devant", "dos", "manches"]}),
           ("a", "operation", {"minutes": 0.6}), ("b", "operation", {"minutes": 0.9}), ("c", "operation", {"minutes": 0.5}),
           ("j", "join", {"match": "product"}), ("m", "operation", {"minutes": 0.7}), ("k", "sink")],
          [("s", 0, "sp"), ("sp", 0, "a"), ("sp", 1, "b"), ("sp", 2, "c"), ("a", 0, "j"), ("b", 0, "j"), ("c", 0, "j"),
           ("j", 0, "m"), ("m", 0, "k")])
    r = simulate_flow(g)
    assert r["conservation"]["ok"]
    # goulot = dos (0,9 min/pc) : ~ 480/0,9 pièces au plus
    assert 450 <= r["kpis"]["pieces"] <= 534
    assert r["kpis"]["pieces"] == int(r["kpis"]["pieces"])        # que des produits complets
    assert r["kpis"]["bottleneck"] == "b"
    sink = next(b for b in r["blocks"] if b["id"] == "k")
    assert sink["entered"] * 10 == r["kpis"]["pieces"]


def test_join_by_size_pairs_matching_sizes():
    lots = [{"style": "Pantalon", "size": "M", "qty": 100}, {"style": "Pantalon", "size": "L", "qty": 100}]
    g = G([("s", "source", {"bundle_size": 10, "lots": lots, "wip_cap": 0}), ("sp", "split", {"components": ["devant", "dos"]}),
           ("a", "operation", {"minutes": 0.2}), ("b", "delay", {"minutes": 7}), ("j", "join", {"match": "size"}),
           ("k", "sink")],
          [("s", 0, "sp"), ("sp", 0, "a"), ("sp", 1, "b"), ("a", 0, "j"), ("b", 0, "j"), ("j", 0, "k")])
    r = simulate_flow(g)
    assert r["conservation"]["ok"] and r["kpis"]["pieces"] == 200


def test_decision_inspect_rework_and_scrap():
    g = G([("s", "source", {"bundle_size": 1, "wip_cap": 20}), ("o", "operation", {"minutes": 0.5}),
           ("c", "inspect", {"minutes": 0.2, "defect_pct": 10}), ("r", "operation", {"minutes": 1.0}),
           ("d", "decision", {"mode": "prob", "probs": [0.8, 0.2]}), ("k", "sink"), ("x", "sink")],
          [("s", 0, "o"), ("o", 0, "c"), ("c", 0, "k"), ("c", 1, "d"), ("d", 0, "r"), ("d", 1, "x"), ("r", 0, "c")])
    r = run_flow_experiment(g, replications=3)
    assert r["conservation"]["ok"]
    c = next(b for b in r["blocks"] if b["id"] == "c")
    x = next(b for b in r["blocks"] if b["id"] == "x")
    assert c["defects"] > 30 and 0 < x["entered"] < c["defects"]
    assert r["replications"]["n"] == 3


def test_attribute_decision_batch_and_resources():
    g = G([("s", "source", {"bundle_size": 5, "wip_cap": 0, "interval_min": 2}),
           ("at", "attribute", {"attr": "couleur", "values": [["bleu", 1], ["noir", 1]]}),
           ("d", "decision", {"mode": "attr", "attr": "couleur", "routes": [["bleu"], ["noir"]]}),
           ("q1", "queue", {"capacity": 0}), ("q2", "queue", {}),
           ("g", "batch", {"size": 4, "key": "couleur"}), ("ac", "acquire", {"resource": "Chariots", "qty": 1}),
           ("dl", "delay", {"minutes": 3}), ("rl", "release", {"resource": "Chariots", "qty": 1}),
           ("ub", "unbatch"), ("o", "operation", {"minutes": 0.1, "resource": "Opératrices"}), ("k", "sink")],
          [("s", 0, "at"), ("at", 0, "d"), ("d", 0, "q1"), ("d", 1, "q2"), ("q1", 0, "g"), ("q2", 0, "g"), ("g", 0, "ac"),
           ("ac", 0, "dl"), ("dl", 0, "rl"), ("rl", 0, "ub"), ("ub", 0, "o"), ("o", 0, "k")],
          resources=[{"name": "Chariots", "kind": "chariot", "capacity": 1}, {"name": "Opératrices", "kind": "operator", "capacity": 1}])
    r = simulate_flow(g)
    assert r["conservation"]["ok"]
    assert r["kpis"]["pieces"] > 900
    res = {p["name"]: p for p in r["resources"]}
    assert res["Chariots"]["utilization_pct"] > 10 and res["Opératrices"]["utilization_pct"] > 10


def test_reproducible():
    g = line([0.6, 0.9, 0.7])
    g["settings"]["dist"] = {"kind": "lognormal", "cv": 0.3}
    a, b, c = simulate_flow(g, 5), simulate_flow(g, 5), simulate_flow(g, 6)
    assert a["kpis"] == b["kpis"] and a["trace"]["events"] == b["trace"]["events"]
    assert a["kpis"] != c["kpis"]


def test_generate_from_routing_with_parallel_branches():
    plan = {"problem_name": "Chemise", "stations": [
        {"station": 1, "minutes": 0.8, "worker_ids": ["W1"], "operations": [{"id": "A", "name": "Préparer col"}]},
        {"station": 2, "minutes": 0.9, "worker_ids": ["W2"], "operations": [{"id": "B", "name": "Préparer manches"}]},
        {"station": 3, "minutes": 0.7, "worker_ids": ["W3"], "operations": [{"id": "C", "name": "Devant + dos"}]},
        {"station": 4, "minutes": 1.0, "worker_ids": ["W4"], "operations": [{"id": "D", "name": "Monter col"}]},
        {"station": 5, "minutes": 0.6, "worker_ids": ["W5"], "operations": [{"id": "E", "name": "Monter manches"}]},
    ]}
    problem = {"operations": [{"id": "A"}, {"id": "B"}, {"id": "C"}, {"id": "D", "predecessors": ["A", "C"]},
                              {"id": "E", "predecessors": ["B", "D"]}]}
    g = from_plan(plan, problem)
    v = validate(g)
    assert v["ok"], v
    types = [b["type"] for b in g["blocks"]]
    assert types.count("split") == 1 and types.count("join") == 2 and types.count("operation") == 5
    assert g["generated"]["branches"] == 3
    r = simulate_flow(g, station_ids=["1", "2", "3", "4", "5"])
    assert r["conservation"]["ok"] and r["kpis"]["pieces"] > 300
    # états des postes liés aux blocs (animation du plan)
    assert any(e[1] == 0 for e in r["trace"]["events"])


def test_generate_serial_without_precedence():
    plan = {"stations": [{"station": i, "minutes": 1, "operations": [{"id": f"O{i}"}]} for i in (1, 2, 3)]}
    g = from_plan(plan, None)
    assert validate(g)["ok"] and [b["type"] for b in g["blocks"]].count("join") == 0
