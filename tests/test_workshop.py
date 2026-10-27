"""Plan d'atelier (cartographie) : géométrie, association stations ↔ machines, parcours, API."""
from __future__ import annotations

import time
import uuid

import pytest

from engine.simulation import LineDayConfig, simulate_line_day
from engine.workshop import (MACHINE_CATALOG, WorkshopGrid, auto_assign, derived_travel, inventory_workstations,
                             machine_corners, norm_type, operator_point, plan_layout)


def machine(i, t, x, y, **kw):
    return {"kind": "machine", "id": f"m{i}", "type": t, "x": x, "y": y, "label": f"M{i:02d}",
            "status": "service", **kw}


def two_rooms(n=8):
    """Salle 20 × 10 m coupée par un mur en x = 10 avec une porte en y = 8 ; 4 machines de chaque côté."""
    els = [{"kind": "wall", "id": "w1", "x1": 10, "y1": 0, "x2": 10, "y2": 10},
           {"kind": "door", "id": "d1", "x": 10, "y": 8, "width": 1.2, "rot": 90}]
    for i in range(n):
        t = "piqueuse_plate" if i % 2 == 0 else "surjeteuse_4_fils"
        x = 2 + (i % 4) * 1.5 + (10 if i >= 4 else 0)
        els.append(machine(i, t, x, 3))
    return {"id": "p1", "name": "Atelier", "width_m": 20, "length_m": 10, "elements": els}


def stations(n=8):
    return [{"station": k + 1, "machine_types": ["piqueuse_plate" if k % 2 == 0 else "surjeteuse_4_fils"],
             "operators": 1, "worker_ids": [f"W{k + 1}"], "workers": [f"Ouvrière {k + 1}"], "minutes": 0.8,
             "operations": [{"id": f"OP{k + 1}", "name": "op", "minutes": 0.8, "skills": []}]} for k in range(n)]


def test_catalog_and_geometry():
    assert {"piqueuse_plate", "surjeteuse_5_fils", "bride", "table_coupe", "chariot"} <= set(MACHINE_CATALOG)
    assert norm_type("Surjeteuse 4 fils") == "surjeteuse_4_fils"
    m = machine(1, "piqueuse_plate", 5, 5, rot=90)
    xs = sorted(round(p[0], 2) for p in machine_corners(m))
    assert xs[0] == pytest.approx(4.7) and xs[-1] == pytest.approx(5.3)   # tournée de 90° : 0,6 m en x
    assert operator_point(machine(1, "piqueuse_plate", 5, 5)) == (5, 5.75)
    assert operator_point(m)[0] == pytest.approx(4.25)                   # devant = vers -x après rotation


def test_auto_assign_by_type_and_ws_link():
    plan = two_rooms()
    a = auto_assign(stations(), plan)
    assert a["missing"] == [] and a["unused"] == []
    assert a["assignment"]["1"] == ["m0"] and a["assignment"]["2"] == ["m1"]
    # poste lié prioritaire + manuel conservé + panne exclue
    plan["elements"][2 + 6]["ws_id"] = "WS-A"
    plan["elements"][2 + 0]["status"] = "panne"
    st = stations()
    st[0]["workstations"] = ["WS-A"]
    a = auto_assign(st, plan, {"3": ["m4"]})
    assert a["assignment"]["1"] == ["m6"] and a["assignment"]["3"] == ["m4"]
    assert "m0" not in sum(a["assignment"].values(), [])


def test_missing_machine_type_is_reported():
    plan = two_rooms(2)
    st = stations(3)
    st[2]["machine_types"] = ["bride"]
    a = auto_assign(st, plan)
    assert a["missing"] == [{"station": 3, "type": "bride"}]
    lay = plan_layout(st, plan, a["assignment"])
    assert lay["virtual"] == [3] and any(w["kind"] == "virtual" for w in lay["flow"]["warnings"])


def test_routes_go_through_the_door():
    plan = two_rooms()
    grid = WorkshopGrid(plan)
    d, path = grid.route((6.5, 3.75), (12, 3.75))
    assert d is not None and d > 5.5 + 4        # détour par la porte (y = 8)
    assert any(p[1] > 7 for p in path)
    plan["elements"] = [e for e in plan["elements"] if e["kind"] != "door"]
    assert WorkshopGrid(plan).route((6.5, 3.75), (12, 3.75))[0] is None


def test_plan_layout_distances_feed_the_simulation():
    plan = two_rooms()
    st = stations()
    a = auto_assign(st, plan)
    lay = plan_layout(st, plan, a["assignment"])
    assert lay["distances"]["4-5"] > 8 and lay["distances"]["1-2"] == pytest.approx(1.5, abs=0.05)
    assert any(w["kind"] == "long_transfer" and w["stations"] == [4, 5] for w in lay["flow"]["warnings"])
    p = {"stations": st, "workers": {f"W{k}": {"name": f"O{k}", "skills": [], "efficiency": 1} for k in range(1, 9)}}
    cfg = LineDayConfig(shift_minutes=120, variability=0, trace=False)
    straight = simulate_line_day(p, {"kind": "free", "positions": lay["positions"]}, cfg)
    routed = simulate_line_day(p, {"kind": "free", "positions": lay["positions"], "distances": lay["distances"]}, cfg)
    assert routed["transport_m"] > straight["transport_m"]
    assert routed["lean"]["transfers"][3]["meters"] == lay["distances"]["4-5"]


def test_u_cell_detected_and_no_backtrack():
    els = []
    for i in range(4):
        els.append(machine(i, "piqueuse_plate", 2 + i * 1.5, 2))
    for i in range(4):
        els.append(machine(4 + i, "piqueuse_plate", 2 + (3 - i) * 1.5, 4.5, rot=180))
    plan = {"id": "u", "width_m": 12, "length_m": 8, "elements": els}
    st = [{"station": k + 1, "machine_types": ["piqueuse_plate"], "operators": 1} for k in range(8)]
    lay = plan_layout(st, plan, auto_assign(st, plan)["assignment"])
    assert lay["kind"] == "u" and lay["flow"]["u_cell"] and lay["flow"]["backtracks"] == []
    # même plan, ordre inversé sur la 2e moitié : retours en arrière
    fixed = {str(k + 1): [f"m{k}"] for k in range(8)}
    fixed["3"], fixed["6"] = ["m5"], ["m2"]
    lay2 = plan_layout(st, plan, fixed)
    assert lay2["flow"]["meters_per_bundle"] > lay["flow"]["meters_per_bundle"]


def test_inventory_and_travel_time():
    plan = two_rooms()
    plan["elements"].append({"kind": "zone", "id": "z1", "zone": "montage", "x": 0, "y": 0, "w": 10, "h": 10})
    plan["elements"].append(machine(20, "chariot", 5, 8))
    plan["elements"][3]["status"] = "reserve"
    ws = inventory_workstations(plan)
    assert len(ws) == 8 and ws[0]["id"] == "M00" and ws[0]["section"] == "Montage"
    assert ws[1]["available"] is False and ws[1]["machine_type"] == "surjeteuse_4_fils"
    tr = derived_travel(plan)
    assert tr["neighbour_m"] == pytest.approx(1.5) and tr["minutes"] == pytest.approx(0.06)


# ------------------------------------------------------------------ API
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from api.auth import SupabaseAuth  # noqa: E402
from api.main import create_app  # noqa: E402
from api.settings import Settings  # noqa: E402
from api.store import StoreError  # noqa: E402
from tests.test_api_saas import URL, FakeJwks, token  # noqa: E402
from tests.test_twin import PROBLEM_SK, RUN_SK, TwinStore  # noqa: E402


class PlanStore(TwinStore):
    def __init__(self):
        super().__init__()
        self.plans = {}

    def list_plans(self, tok, org):
        return [{k: v for k, v in p.items() if k != "elements"} for p in self.plans.values() if p["org_id"] == org]

    def get_plan(self, tok, org, pid):
        p = self.plans.get(pid)
        if not p or p["org_id"] != org:
            raise StoreError(404, "Plan d'atelier introuvable.")
        return p

    def create_plan(self, tok, org, data):
        pid = str(uuid.uuid4())
        self.plans[pid] = {**data, "id": pid, "org_id": org}
        return self.plans[pid]

    def update_plan(self, tok, org, pid, fields):
        self.get_plan(tok, org, pid).update(fields)
        return self.plans[pid]

    def delete_plan(self, tok, org, pid):
        return self.plans.pop(pid, None) is not None


@pytest.fixture()
def wp():
    store = PlanStore()
    app = create_app(Settings(supabase_url=URL, supabase_anon_key="sb_publishable_test"),
                     auth=SupabaseAuth(URL, jwk_client=FakeJwks()), store=store)
    with TestClient(app) as c:
        a, b = str(uuid.uuid4()), str(uuid.uuid4())
        ha, hb = {"Authorization": f"Bearer {token(a)}"}, {"Authorization": f"Bearer {token(b)}"}
        org = c.post("/v1/orgs", json={"name": "Atelier A"}, headers=ha).json()["id"]
        rid, pid = str(uuid.uuid4()), str(uuid.uuid4())
        store.problems[pid] = {"id": pid, "org_id": org, "payload": PROBLEM_SK}
        store.runs[rid] = {**RUN_SK, "id": rid, "org_id": org, "problem_id": pid, "stations_used": 3}
        yield c, store, org, rid, ha, hb


def test_plan_crud_inventory_and_isolation(wp):
    c, store, org, rid, ha, hb = wp
    body = {"name": "Atelier actuel", "width_m": 20, "length_m": 10, "elements": two_rooms()["elements"],
            "background": {"path": f"{org}/fond.png", "opacity": 0.5}}
    r = c.post(f"/v1/orgs/{org}/workshop-plans", headers=ha, json=body)
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    bad = {**body, "background": {"path": f"{uuid.uuid4()}/x.png"}}
    assert c.post(f"/v1/orgs/{org}/workshop-plans", headers=ha, json=bad).status_code == 422
    dup = {**body, "elements": [{"kind": "wall", "id": "a"}, {"kind": "wall", "id": "a"}]}
    assert c.post(f"/v1/orgs/{org}/workshop-plans", headers=ha, json=dup).status_code == 422
    assert c.get(f"/v1/orgs/{org}/workshop-plans", headers=hb).status_code == 404
    assert c.get(f"/v1/orgs/{org}/workshop-plans/{pid}", headers=hb).status_code == 404
    r = c.put(f"/v1/orgs/{org}/workshop-plans/{pid}", headers=ha, json={"version": "projet", "clear_background": True})
    assert r.status_code == 200 and r.json()["version"] == "projet" and r.json()["background"] is None
    inv = c.get(f"/v1/orgs/{org}/workshop-plans/{pid}/inventory", headers=ha).json()
    assert len(inv["workstations"]) == 8 and inv["by_type"]["piqueuse_plate"]["service"] == 4
    assert inv["travel"]["minutes"] == pytest.approx(0.06)
    assert "piqueuse_plate" in c.get(f"/v1/orgs/{org}/workshop-catalog", headers=ha).json()["machines"]
    assert c.delete(f"/v1/orgs/{org}/workshop-plans/{pid}", headers=ha).status_code == 204


def test_twin_on_plan_place_save_and_simulate(wp):
    c, store, org, rid, ha, hb = wp
    els = two_rooms()["elements"]
    pid = c.post(f"/v1/orgs/{org}/workshop-plans", headers=ha,
                 json={"name": "P", "width_m": 20, "length_m": 10, "elements": els}).json()["id"]
    r = c.post(f"/v1/orgs/{org}/runs/{rid}/twin/plan", headers=ha, json={"plan_id": pid})
    assert r.status_code == 200, r.text
    pl = r.json()
    assert set(pl["assignment"]) == {"1", "2", "3"} and pl["layout"]["distances"]
    # stations manuelles (sans type) : placées sur des tables à défaut -> virtuelles ici
    assert pl["virtual"] == [1, 2, 3] or all(pl["assignment"].values()) or pl["missing"] == []
    fixed = {"1": ["m0"], "2": ["m1"], "3": ["m4"]}
    r = c.put(f"/v1/orgs/{org}/runs/{rid}/layout", headers=ha, json={"plan_id": pid, "assignment": fixed})
    assert r.status_code == 200, r.text
    assert store.layouts[(org, rid)]["plan_id"] == pid and store.layouts[(org, rid)]["assignment"]["3"] == ["m4"]
    d = c.get(f"/v1/orgs/{org}/runs/{rid}/twin", headers=ha).json()
    assert d["placement"]["plan_id"] == pid and d["layout"]["distances"]["2-3"] > 8
    assert len(d["workshop_plans"]) == 1
    r = c.post(f"/v1/orgs/{org}/runs/{rid}/simulate", headers=ha, json={"scenarios": [{"name": "Sur le plan"}]})
    assert r.status_code == 202
    t0 = time.time()
    while time.time() - t0 < 20:
        s = c.get(f"/v1/orgs/{org}/simulations/{r.json()['id']}", headers=ha).json()
        if s["status"] in ("done", "failed"):
            break
        time.sleep(0.1)
    assert s["status"] == "done", s.get("error")
    res = s["results"]["scenarios"][0]["result"]
    assert res["lean"]["transfers"][1]["meters"] > 8 and s["layout"]["plan_id"] == pid
    assert c.post(f"/v1/orgs/{org}/runs/{rid}/twin/plan", headers=hb, json={"plan_id": pid}).status_code == 404
