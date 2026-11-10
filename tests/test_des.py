"""Moteur de simulation à événements discrets (engine/des, v3.0)."""
from __future__ import annotations

import pytest

from engine.des import ModelError, build_model, normalize_model, run_experiment, simulate
from engine.des.distributions import normalize as ndist, sample_total
from engine.des.experiment import ci


def line(times, **kw):
    sts = [{"id": str(i + 1), "x": i * 1.6, "y": 0, "minutes": t, "operators": [f"W{i + 1}"]} for i, t in enumerate(times)]
    m = {"stations": sts, "shift": {"minutes": 480, "breaks": []},
         "source": {"bundle_size": 10, "start_wip_bundles": 0},
         "settings": {"dist": {"kind": "constant"}, "handling_min": 0}}
    for k, v in kw.items():
        if isinstance(v, dict):
            m.setdefault(k, {}).update(v)
        else:
            m[k] = v
    return m


def test_single_station_analytical():
    r = simulate(line([1.0]))
    # 1 min/pièce, paquets de 10 : un paquet toutes les 10 min ; le 48e finit pile à 480 (non compté)
    assert r["kpis"]["pieces"] == 470
    assert r["stations"][0]["states"]["work"] == pytest.approx(100.0, abs=0.1)
    assert r["conservation"]["ok"]


def test_serial_line_bottleneck_rate():
    r = simulate(line([0.5, 1.0, 0.8]))
    assert r["kpis"]["bottleneck"] == "2"
    # débit plafonné par le goulot (1 min/pièce) moins le remplissage de la ligne
    assert 440 <= r["kpis"]["pieces"] <= 470
    s1 = r["stations"][0]["states"]
    assert s1["blocked"] > 30          # le poste rapide amont est bloqué par la file pleine
    assert r["stations"][2]["states"]["starved"] > 15
    assert r["conservation"]["ok"]


def test_breaks_stop_the_line():
    base = simulate(line([1.0]))["kpis"]["pieces"]
    r = simulate(line([1.0], shift={"minutes": 480, "breaks": [{"start_min": 100, "minutes": 60}]}))
    assert r["kpis"]["pieces"] == base - 60
    assert r["stations"][0]["states"]["break"] == pytest.approx(12.5, abs=0.2)


def test_reproducible_with_seed_and_varies_otherwise():
    m = line([0.6, 0.9, 0.7], settings={"dist": {"kind": "lognormal", "cv": 0.25}, "mtbf_min": 120, "mttr_min": 10})
    a, b, c = simulate(m, seed=7), simulate(m, seed=7), simulate(m, seed=8)
    assert a["kpis"] == b["kpis"] and a["trace"]["events"] == b["trace"]["events"]
    assert a["kpis"] != c["kpis"]


def test_conservation_with_defects_transporters_and_setup():
    m = line([0.4, 0.5, 0.45, 0.5], settings={"defect_pct": 8, "setup_min": 3, "transfer": "transporter",
                                              "dist": {"kind": "triangular", "low_pct": 70, "high_pct": 160}},
             source={"bundle_size": 12, "start_wip_bundles": 1,
                     "lots": [{"style": "A", "size": "S", "qty": 120}, {"style": "A", "size": "M", "qty": 0}]},
             transporters=[{"capacity": 3, "speed_m_per_min": 50}])
    r = simulate(m)
    assert r["conservation"]["ok"]
    assert r["kpis"]["defects"] > 0
    assert r["transporters"][0]["loads"] > 0
    assert any(s["states"]["setup"] > 0 for s in r["stations"])
    kinds = {e[1] for e in r["trace"]["events"]}
    assert kinds == {0, 1, 2, 3}


def test_shared_operator_walks_between_stations():
    m = line([0.5, 0.5, 0.5])
    m["stations"][2]["operators"] = ["W1"]       # W1 tient les postes 1 et 3 (4,8 m à pied aller-retour)
    m["settings"]["walk_speed_m_per_min"] = 60
    r = simulate(m)
    w1 = next(o for o in r["operators"] if o["id"] == "W1")
    assert w1["walk_m"] > 100 and w1["states"]["walk"] > 0
    assert r["conservation"]["ok"]


def test_operator_carries_far_bundles():
    m = line([0.5, 0.5])
    m["stations"][1]["x"] = 12.0
    r = simulate(m)
    assert r["operators"][0]["carry_m"] > 0
    assert r["stations"][0]["states"]["transfer"] > 0


def test_distributions_mean():
    import random
    rng = random.Random(1)
    for kind in ("normal", "triangular", "lognormal"):
        d = ndist({"kind": kind, "cv": 0.2, "low_pct": 70, "high_pct": 150})
        vals = [sample_total(rng, d, 1.0, 10) for _ in range(3000)]
        assert sum(vals) / len(vals) == pytest.approx(10.0, rel=0.03)


def test_experiment_replications_ci():
    m = line([0.6, 0.9, 0.7], settings={"dist": {"kind": "normal", "cv": 0.2}},
             source={"bundle_size": 10, "start_wip_bundles": 1})
    e = run_experiment(m, [{"name": "Réf"}, {"name": "Paquets de 5", "overrides": {"source": {"bundle_size": 5}}}],
                       replications=5)
    assert len(e["scenarios"]) == 2
    k = e["scenarios"][0]["result"]["replications"]["kpis"]["pieces"]
    assert k["n"] == 5 and k["lo"] <= k["mean"] <= k["hi"]
    lead = [s["result"]["replications"]["kpis"]["lead_time_avg"]["mean"] for s in e["scenarios"]]
    assert lead[1] < lead[0]                        # petits paquets = traversée plus courte
    assert "trace" in e["scenarios"][0]["result"]
    assert ci([1, 2, 3])["mean"] == 2


def test_build_model_from_twin_plan():
    plan = {"stations": [{"station": 1, "minutes": 0.8, "operators": 1, "worker_ids": ["A"], "workers": ["Amel"],
                          "operations": [{"id": "o1", "name": "Col"}]},
                         {"station": 2, "minutes": 1.0, "operators": 2, "worker_ids": ["B", "C"], "workers": ["B", "C"]},
                         {"station": 3, "minutes": 0.5, "operators": 1, "worker_ids": ["A"], "workers": ["Amel"]}],
            "workers": {"A": {"name": "Amel", "efficiency": 1.1}}, "cycle_time": 0.5}
    m = build_model(plan, {"kind": "u"})
    n = normalize_model(m)
    assert [s["servers"] for s in n["stations"]] == [1, 2, 1]
    amel = next(o for o in n["operators"] if o["id"] == "A")
    assert amel["stations"] == ["1", "3"] and amel["efficiency"] == pytest.approx(1.1)
    assert n["settings"]["target_per_hour"] == 120
    assert "1|3" in m["paths"]
    r = simulate(m)
    assert r["conservation"]["ok"] and r["kpis"]["pieces"] > 0


def test_paths_avoid_walls_on_workshop_plan():
    wp = {"width_m": 12, "length_m": 8, "elements": [
        {"id": "w", "kind": "wall", "x1": 6, "y1": 0, "x2": 6, "y2": 6, "thickness": 0.2},
        {"id": "m1", "kind": "machine", "type": "piqueuse_plate", "x": 3, "y": 3, "w": 1.2, "d": 0.6, "rot": 0},
        {"id": "m2", "kind": "machine", "type": "piqueuse_plate", "x": 9, "y": 3, "w": 1.2, "d": 0.6, "rot": 0}]}
    plan = {"stations": [{"station": 1, "minutes": 1, "worker_ids": ["A"]}, {"station": 2, "minutes": 1, "worker_ids": ["B"]}]}
    lay = {"positions": {"1": {"x": 3, "y": 3.75}, "2": {"x": 9, "y": 3.75}}, "assignment": {"1": ["m1"], "2": ["m2"]}}
    m = build_model(plan, lay, wp)
    p = m["paths"]["1|2"]
    assert p["m"] > 8.0                              # contourne le mur (ouvert en bas) : bien plus que 6 m
    assert any(pt[1] > 6 for pt in p["pts"])


def test_model_errors_and_limits():
    with pytest.raises(ModelError):
        normalize_model({"stations": []})
    n = normalize_model({"stations": [{"id": "1", "minutes": 1}], "shift": {"minutes": 99999}})
    assert n["shift"]["minutes"] == 960


# ------------------------------------------------------------------ API
pytest.importorskip("fastapi")
from tests.test_twin import _wait, tw  # noqa: E402,F401


def test_api_des_model_run_exports_and_isolation(tw):
    c, store, org, rid, ha, hb = tw
    r = c.get(f"/v1/orgs/{org}/runs/{rid}/des/model", headers=ha)
    assert r.status_code == 200, r.text
    model = r.json()["model"]
    assert [s["id"] for s in model["stations"]] == ["1", "2", "3"]
    assert c.get(f"/v1/orgs/{org}/runs/{rid}/des/model", headers=hb).status_code == 404
    model["transporters"] = [{"capacity": 3}]
    body = {"name": "Essai", "model": model, "replications": 3,
            "scenarios": [{"name": "Référence"},
                          {"name": "Petits paquets", "overrides": {"source": {"bundle_size": 5},
                                                                   "settings": {"transfer": "transporter"}}},
                          {"name": "Absente", "absent": ["W2"]}]}
    r = c.post(f"/v1/orgs/{org}/runs/{rid}/des", headers=ha, json=body)
    assert r.status_code == 202, r.text
    sid = r.json()["id"]
    assert c.post(f"/v1/orgs/{org}/runs/{rid}/des", headers=hb, json=body).status_code == 404
    s = _wait(c, f"/v1/orgs/{org}/simulations/{sid}", ha)
    assert s["status"] == "done", s.get("error")
    res = s["results"]
    assert res["engine"] == "des-3.0" and len(res["scenarios"]) == 3
    assert res["scenarios"][0]["result"]["replications"]["n"] == 3
    assert res["scenarios"][1]["result"]["transporters"][0]["loads"] > 0
    assert any("reprend" in n for n in res["scenarios"][2]["result"]["notes"])
    assert all(it["result"]["conservation"]["ok"] for it in res["scenarios"])
    lst = c.get(f"/v1/orgs/{org}/runs/{rid}/des/simulations", headers=ha).json()
    assert [x["id"] for x in lst] == [sid]
    assert c.get(f"/v1/orgs/{org}/runs/{rid}/simulations", headers=ha).json() == []   # jumeau : séparé
    x = c.get(f"/v1/orgs/{org}/simulations/{sid}/des.xlsx", headers=ha)
    assert x.status_code == 200 and x.content[:2] == b"PK"
    pdf = c.get(f"/v1/orgs/{org}/simulations/{sid}/des.pdf", headers=ha)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    bad = c.post(f"/v1/orgs/{org}/runs/{rid}/des", headers=ha, json={"model": {"stations": []}})
    assert bad.status_code == 422


def test_machine_library_complete_and_web_copy_in_sync():
    from pathlib import Path

    from engine.machine_library import LIBRARY
    from engine.workshop import MACHINE_CATALOG
    from scripts.build_machine_library import render
    need = {"piqueuse_plate", "piqueuse_2_aiguilles", "piqueuse_triple_entrainement", "piqueuse_colonne", "piqueuse_bras",
            "surjeteuse_3_fils", "surjeteuse_4_fils", "surjeteuse_5_fils", "recouvreuse", "recouvreuse_bras", "chainette",
            "zigzag", "point_invisible", "piqueuse_boutonniere", "boutonniere_oeillet", "piqueuse_bouton", "bride",
            "pose_passants", "machine_poches_auto", "machine_pinces", "pose_elastique", "feed_off_arm", "table_coupe",
            "chariot_matelasseur", "coupe_automatique", "scie_ruban", "presse_thermocollage", "table_repassage",
            "mannequin_vapeur", "presse_finition", "table_controle", "detecteur_aiguilles", "etiqueteuse_emballage",
            "rack_encours", "chariot", "convoyeur_suspendu", "palette_carton"}
    assert need <= set(LIBRARY) and set(LIBRARY) == set(MACHINE_CATALOG)
    for v in LIBRARY.values():
        assert v["w"] > 0 and v["d"] > 0 and v["h"] > 0 and v["shape"] and v["source"]
    web = Path(__file__).resolve().parents[1] / "web" / "src" / "lib" / "machineLibrary.ts"
    assert web.read_text(encoding="utf-8") == render(), "relancer scripts/build_machine_library.py"
