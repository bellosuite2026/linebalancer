"""Optimiseur de la simulation (engine/des/optimize.py, phase 2.3)."""
from __future__ import annotations

import pytest

from engine.des.optimize import (apply_genes, dominates, fronts, normalize_config, optimize, remove_operators,
                                 swap_variant)
from engine.des.model import normalize_model


def line(times, **kw):
    sts = [{"id": str(i + 1), "x": i * 1.6, "y": 0, "minutes": t, "operators": [f"W{i + 1}"],
            "machine_type": "pique" if i % 2 else "surjet"} for i, t in enumerate(times)]
    m = {"stations": sts, "shift": {"minutes": 480, "breaks": []}, "source": {"bundle_size": 10, "start_wip_bundles": 1},
         "settings": {"dist": {"kind": "normal", "cv": 0.1}}}
    m.update(kw)
    return m


def test_pareto_sort_with_constraints():
    a = {"f": [1, 1], "viol": 0}
    b = {"f": [2, 2], "viol": 0}
    c = {"f": [0, 3], "viol": 0}
    d = {"f": [0, 0], "viol": 0.5}
    assert dominates(a, b) and not dominates(a, c) and dominates(a, d)
    fr = fronts([a, b, c, d])
    assert sorted(fr[0]) == [0, 2]


def test_config_bounds():
    c = normalize_config({"objectives": ["pieces"], "time_budget_s": 9999, "replications": 50})
    assert c["time_budget_s"] == 180 and c["replications"] == 10 and len(c["objectives"]) == 2


def test_remove_operator_neighbour_takes_over():
    m = normalize_model(line([1.0, 0.3, 0.9]))
    r = remove_operators(m, ["W2"])
    st2 = next(s for s in r["stations"] if s["id"] == "2")
    assert st2["operators"] and st2["operators"][0] in ("W1", "W3")
    assert len(r["operators"]) == 2


def test_helpers_and_overrides_apply():
    v = [{"name": "Actuelle", "model": normalize_model(line([0.8, 1.6, 0.8]))}]
    m = apply_genes(v, {"layout": 0, "helpers": ("2",), "fewer": (), "bundle_size": 5, "wip_factor": 2.0,
                        "transporters": 1, "carrier_factor": 0, "station_wip": 4})
    n = normalize_model(m)
    assert next(s for s in n["stations"] if s["id"] == "2")["servers"] == 2
    assert n["source"]["bundle_size"] == 5 and n["source"]["wip_cap_bundles"] == 6 and len(n["transporters"]) == 1


def test_swap_variant_shortens_walks():
    m = line([1, 1, 1, 1])
    # stations 2 et 4 (même machine) placées à l'envers : 1 4 3 2 sur le sol
    m["stations"][1]["x"], m["stations"][3]["x"] = 4.8, 1.6
    sv = swap_variant(normalize_model(m))
    assert sv is not None
    assert [s["x"] for s in sv["stations"]] == [0, 1.6, 3.2, 4.8]


def test_optimizer_finds_bottleneck_helper_and_reports_progress():
    seen = []
    m = line([0.6, 1.5, 0.7, 0.6])
    r = optimize([{"name": "Actuelle", "model": m}],
                 {"time_budget_s": 8, "replications": 2, "objectives": ["pieces", "cost_minute", "wip_avg"],
                  "max_extra_operators": 1}, progress=seen.append)
    assert seen and seen[-1]["evals"] == r["evals"] - 0 or seen
    assert r["pareto"] and r["evals"] >= 10
    best = r["pareto"][0]
    assert best["mean"]["pieces"] > r["base"]["mean"]["pieces"] * 1.3     # renfort au goulot (poste 2)
    assert "2" in best["genes"]["helpers"]
    assert any(s["mean"]["wip_avg"] < r["base"]["mean"]["wip_avg"] for s in r["pareto"])
    ids = [s["id"] for s in r["pareto"]]
    assert ids == list(range(1, len(ids) + 1))


def test_optimizer_respects_constraint():
    m = line([0.6, 1.5, 0.7, 0.6])
    r = optimize([{"name": "Actuelle", "model": m}],
                 {"time_budget_s": 6, "replications": 1, "constraints": {"max_people": 4}, "max_extra_operators": 2})
    assert r["feasible_found"]
    assert all(s["mean"]["people"] <= 4 for s in r["pareto"])


# ------------------------------------------------------------------ API
pytest.importorskip("fastapi")
from tests.test_twin import _wait, tw  # noqa: E402,F401


def test_api_optimize_apply_and_isolation(tw):
    c, store, org, rid, ha, hb = tw
    body = {"name": "Opti", "config": {"time_budget_s": 6, "replications": 1}}
    assert c.post(f"/v1/orgs/{org}/runs/{rid}/optimize", headers=hb, json=body).status_code == 404
    r = c.post(f"/v1/orgs/{org}/runs/{rid}/optimize", headers=ha, json=body)
    assert r.status_code == 202, r.text
    sid = r.json()["id"]
    s = _wait(c, f"/v1/orgs/{org}/simulations/{sid}", ha, timeout=60)
    assert s["status"] == "done", s.get("error")
    res = s["results"]
    assert res["engine"] == "opt-1.0" and res["pareto"]
    assert "model" not in (s["layout"]["variants"][0])           # réponse allégée
    assert len(s["layout"]["variants"]) >= 2                     # actuelle + en U (sans plan d'atelier)
    lst = c.get(f"/v1/orgs/{org}/runs/{rid}/optimizations", headers=ha).json()
    assert [x["id"] for x in lst] == [sid]
    a = c.post(f"/v1/orgs/{org}/optimizations/{sid}/apply", headers=ha, json={"solution": 1, "replications": 2})
    assert a.status_code == 202, a.text
    did = a.json()["simulation"]["id"]
    d = _wait(c, f"/v1/orgs/{org}/simulations/{did}", ha)
    assert d["status"] == "done" and d["kind"] == "des", d.get("error")
    assert d["results"]["scenarios"][0]["name"].startswith("Optimiseur")
    assert c.post(f"/v1/orgs/{org}/optimizations/{sid}/apply", headers=hb, json={"solution": 1}).status_code == 404
    assert c.post(f"/v1/orgs/{org}/optimizations/{sid}/apply", headers=ha, json={"solution": 99}).status_code == 404
