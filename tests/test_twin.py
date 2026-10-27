"""Jumeau numérique : simulation de journée (engine), scénarios, Lean, routes (store en mémoire), exports."""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from engine.simulation import (LineDayConfig, apply_scenario, default_layout, lean_check,
                               simulate_line_day, station_workers)

PLAN = {"stations": [
    {"station": 1, "minutes": 0.6, "operators": 1, "worker_ids": ["W1"], "workers": ["Amira"],
     "operations": [{"id": "A", "minutes": 0.6, "skills": ["surjet"]}]},
    {"station": 2, "minutes": 0.5, "operators": 1, "worker_ids": ["W2"], "workers": ["Sami"],
     "operations": [{"id": "B", "minutes": 0.5, "skills": ["piqure"]}]},
    {"station": 3, "minutes": 0.9, "operators": 1, "worker_ids": ["W3"], "workers": ["Hana"],
     "operations": [{"id": "C", "minutes": 0.9, "skills": ["piqure"]}]}],
    "workers": {"W1": {"name": "Amira", "skills": ["surjet", "piqure"]},
                "W2": {"name": "Sami", "skills": ["piqure"]}, "W3": {"name": "Hana", "skills": ["piqure"]}}}


# ------------------------------------------------------------------ moteur
def test_deterministic_day_matches_bottleneck_rate():
    r = simulate_line_day(PLAN, config=LineDayConfig(variability=0, bundle_size=1))
    assert r["success"] and r["bottleneck"] == 3
    assert 480 / 0.9 - 3 <= r["pieces"] <= 480 / 0.9 + 1
    st = {s["station"]: s for s in r["stations"]}
    assert st[3]["utilization_pct"] > 98 and st[1]["utilization_pct"] < 75   # CONWIP : l'amont ne s'emballe pas
    assert sum(r["hourly"]) == r["pieces"] and len(r["hourly"]) == 8


def test_same_seed_same_result_and_efficiency_effect():
    a = simulate_line_day(PLAN)
    b = simulate_line_day(PLAN)
    assert a["pieces"] == b["pieces"]
    slow = simulate_line_day(PLAN, config=LineDayConfig(efficiency=0.7))
    assert slow["pieces"] < a["pieces"] * 0.8


def test_absence_reassigns_by_skills_and_shares():
    p, notes = apply_scenario(PLAN, {"absent": ["W3"]})
    sw = station_workers(p)
    assert sw[3] == ["W2"] and sw[2] == ["W2"]          # Sami (0,5) partagé plutôt qu'Amira (0,6)
    assert any("partagé" in n for n in notes)
    r = simulate_line_day(PLAN, scenario={"absent": ["W3"]})
    base = simulate_line_day(PLAN)
    assert 0 < r["pieces"] < base["pieces"] and r["walk_m"] > 0


def test_absence_without_reassignment_blocks_line():
    r = simulate_line_day(PLAN, scenario={"absent": ["W3"], "reassign": False})
    assert r["pieces"] == 0 and r["blocked_stations"] == [3]


def test_unqualified_worker_runs_at_half_speed():
    plan = {**PLAN, "workers": {**PLAN["workers"], "W2": {"name": "Sami", "skills": []},
                                "W1": {"name": "Amira", "skills": ["surjet"]}}}
    p, notes = apply_scenario(plan, {"absent": ["W3"]})
    assert p["unqualified"] and any("qualifiée" in n for n in notes)


def test_breakdown_and_staffing():
    base = simulate_line_day(PLAN)
    down = simulate_line_day(PLAN, scenario={"breakdowns": [{"station": 3, "start_min": 60, "duration_min": 60}]})
    assert down["pieces"] < base["pieces"] and down["stations"][2]["down_min"] >= 55
    more = simulate_line_day(PLAN, scenario={"operators": {"3": 2}})
    assert more["pieces"] > base["pieces"] * 1.3 and more["bottleneck"] != 3


def test_bundle_size_changes_wip_and_trace_is_consistent():
    small = simulate_line_day(PLAN, config=LineDayConfig(bundle_size=2))
    big = simulate_line_day(PLAN, config=LineDayConfig(bundle_size=30))
    assert big["wip_max"] > small["wip_max"]
    ev = small["trace"]["events"]
    assert ev and all(len(e) >= 4 for e in ev) and ev == sorted(ev, key=lambda e: e[0])


def test_layouts_and_lean_rules():
    u = default_layout([1, 2, 3, 4, 5, 6], "u")
    assert u["kind"] == "u" and u["positions"]["1"]["y"] == 0 and u["positions"]["6"]["y"] > 0
    assert abs(u["positions"]["6"]["x"] - u["positions"]["1"]["x"]) < 1   # sortie face à l'entrée
    bad = lean_check(PLAN, {"kind": "free", "positions": {"1": {"x": 0, "y": 0}, "2": {"x": 5, "y": 0},
                                                         "3": {"x": 1, "y": 0}}})
    kinds = {w["kind"] for w in bad["warnings"]}
    assert {"long_transfer", "backtrack"} <= kinds
    shared, _ = apply_scenario(PLAN, {"absent": ["W3"]})
    far = lean_check(shared, {"kind": "free", "positions": {"1": {"x": 0, "y": 0}, "2": {"x": 0, "y": 5},
                                                           "3": {"x": 1.5, "y": 5}}})
    assert not any(w["kind"] == "far_second_station" for w in far["warnings"])
    far = lean_check(shared, {"kind": "free", "positions": {"1": {"x": 0, "y": 0}, "2": {"x": 1, "y": 0},
                                                           "3": {"x": 6, "y": 0}}})
    assert any(w["kind"] == "far_second_station" for w in far["warnings"])


def test_forecast_style_initial_wip_and_feed_limit():
    r = simulate_line_day(PLAN, config=LineDayConfig(shift_minutes=60, initial_wip={2: 20, 3: 40}, feed_limit=30))
    assert r["pieces"] <= 90 and r["pieces"] > 0


def test_big_line_runs_fast():
    plan = {"stations": [{"station": i, "minutes": 0.5 + (i % 4) * 0.1, "operators": 1 + (i % 3 == 0)}
                         for i in range(1, 31)]}
    t = time.time()
    r = simulate_line_day(plan, config=LineDayConfig(bundle_size=1, shift_minutes=600))
    assert r["pieces"] > 500 and time.time() - t < 20


# ------------------------------------------------------------------ API
pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from api import twin  # noqa: E402
from api.auth import SupabaseAuth  # noqa: E402
from api.main import create_app  # noqa: E402
from api.settings import Settings  # noqa: E402
from api.store import StoreError  # noqa: E402
from tests.test_api_saas import URL, FakeJwks, token  # noqa: E402
from tests.test_production import PROBLEM, RUN, ProdStore, entry  # noqa: E402

TUNIS = timezone(timedelta(hours=1))


class TwinStore(ProdStore):
    def __init__(self):
        super().__init__()
        self.layouts, self.sims = {}, {}

    def get_layout(self, tok, org, rid):
        return self.layouts.get((org, rid))

    def save_layout(self, tok, org, rid, kind, positions):
        self.layouts[(org, rid)] = {"org_id": org, "run_id": rid, "kind": kind, "positions": positions}
        return self.layouts[(org, rid)]

    def create_simulation(self, tok, org, uid, data):
        sid = str(uuid.uuid4())
        self.sims[sid] = {"id": sid, "org_id": org, "created_by": uid, "status": "queued", **data}
        return dict(self.sims[sid])

    def update_simulation(self, tok, sid, fields):
        self.sims[sid].update(fields)

    def get_simulation(self, tok, org, sid):
        s = self.sims.get(sid)
        if not s or s["org_id"] != org:
            raise StoreError(404, "Introuvable.")
        return s

    def list_simulations(self, tok, org, rid, limit=20):
        return [{k: v for k, v in s.items() if k != "results"} for s in self.sims.values()
                if s["org_id"] == org and s["run_id"] == rid]


PROBLEM_SK = {**PROBLEM, "operations": [{**o, "required_skills": ["piqure"] if o["id"] != "A" else ["surjet"]}
                                         for o in PROBLEM["operations"]],
              "workers": [{"id": "W1", "name": "Amira", "skills": ["surjet", "piqure"]},
                          {"id": "W2", "name": "Sami", "skills": ["piqure"]},
                          {"id": "W3", "name": "Hana", "skills": ["piqure"]}]}
RUN_SK = {**RUN, "result": {**RUN["result"], "station_details": [
    {**sd, "worker_ids": [f"W{sd['station']}"]} for sd in RUN["result"]["station_details"]]}}


@pytest.fixture()
def tw():
    store = TwinStore()
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


def _wait(c, url, h, timeout=20):
    t = time.time()
    while time.time() - t < timeout:
        s = c.get(url, headers=h).json()
        if s["status"] in ("done", "failed"):
            return s
        time.sleep(0.1)
    raise AssertionError("simulation trop longue")


def test_twin_plan_layout_and_isolation(tw):
    c, store, org, rid, ha, hb = tw
    r = c.get(f"/v1/orgs/{org}/runs/{rid}/twin", headers=ha)
    assert r.status_code == 200, r.text
    d = r.json()
    assert [s["station"] for s in d["plan"]["stations"]] == [1, 2, 3]
    assert d["plan"]["workers"]["W1"]["skills"] == ["surjet", "piqure"]
    assert d["plan"]["stations"][1]["operations"][0]["skills"] == ["piqure"]
    assert d["layout"]["kind"] == "line" and not d["layout_saved"]
    assert c.get(f"/v1/orgs/{org}/runs/{rid}/twin", headers=hb).status_code == 404
    r = c.put(f"/v1/orgs/{org}/runs/{rid}/layout", headers=ha,
              json={"kind": "u", "positions": {"1": {"x": 0, "y": 0}, "9": {"x": 3, "y": 3}}})
    assert r.status_code == 200 and "9" not in r.json()["positions"]
    d = c.get(f"/v1/orgs/{org}/runs/{rid}/twin", headers=ha).json()
    assert d["layout_saved"] and d["layout"]["kind"] == "u" and set(d["layout"]["positions"]) == {"1", "2", "3"}


def test_simulate_compare_and_export(tw):
    c, store, org, rid, ha, hb = tw
    body = {"scenarios": [{"name": "Référence"},
                          {"name": "Hana absente", "absent": ["W3"]},
                          {"name": "Panne + paquets de 20", "bundle_size": 20,
                           "breakdowns": [{"station": 3, "start_min": 60, "duration_min": 45}]}]}
    r = c.post(f"/v1/orgs/{org}/runs/{rid}/simulate", headers=ha, json=body)
    assert r.status_code == 202, r.text
    sim = _wait(c, f"/v1/orgs/{org}/simulations/{r.json()['id']}", ha)
    assert sim["status"] == "done", sim.get("error")
    comp = {row["key"]: row["values"] for row in sim["results"]["comparison"]}
    assert comp["pieces"][0] > comp["pieces"][1] and comp["pieces"][0] > comp["pieces"][2]
    assert comp["bottleneck"][0] == 3
    assert c.get(f"/v1/orgs/{org}/simulations/{sim['id']}", headers=hb).status_code == 404
    x = c.get(f"/v1/orgs/{org}/simulations/{sim['id']}/export.xlsx", headers=ha)
    assert x.status_code == 200 and x.content[:2] == b"PK"
    p = c.get(f"/v1/orgs/{org}/simulations/{sim['id']}/export.pdf", headers=ha)
    assert p.status_code == 200 and p.content[:4] == b"%PDF"
    assert len(c.get(f"/v1/orgs/{org}/runs/{rid}/simulations", headers=ha).json()) == 1


def test_simulate_validation(tw):
    c, store, org, rid, ha, hb = tw
    url = f"/v1/orgs/{org}/runs/{rid}/simulate"
    assert c.post(url, headers=ha, json={"scenarios": []}).status_code == 422
    assert c.post(url, headers=ha, json={"scenarios": [{}] * 4}).status_code == 422
    assert c.post(url, headers=ha, json={"scenarios": [{"shift_minutes": 900}]}).status_code == 422
    r = c.post(url, headers=ha, json={"scenarios": [{"breakdowns": [{"station": 7}]}]})
    assert r.status_code == 422 and "Station 7" in r.text
    assert c.post(url, headers=hb, json={"scenarios": [{}]}).status_code == 404


def test_sync_real_vs_simulated_and_forecast(tw):
    c, store, org, rid, ha, hb = tw
    sess = c.post(f"/v1/orgs/{org}/production/sessions", headers=ha, json={"run_id": rid}).json()
    plan = twin.twin_plan(store.runs[rid], PROBLEM_SK, sess["plan"])
    s = store.sessions[sess["id"]]
    entries = [entry(1, 8, 60), entry(2, 8, 58), entry(3, 8, 50), entry(1, 9, 55), entry(2, 9, 50), entry(3, 9, 40)]
    now = datetime(2026, 10, 27, 10, 0, tzinfo=TUNIS)
    s["session_date"] = "2026-10-27"
    res = twin.sync(s, entries, plan, twin.layout_for(plan, None), now=now, order_qty=2000, order_done=100)
    assert res["output"] == 90 and res["elapsed_minutes"] == 120
    assert res["planned_day"] > res["calibrated_day"] > 0
    assert res["forecast_end_of_day"] > 90
    assert res["hourly"][0]["real"] == 50 and res["hourly"][0]["simulated"] > 0
    o = res["order"]
    assert o["left_after_today"] == 2000 - 100 - res["forecast_end_of_day"] and o["extra_days"] >= 1
    # route
    r = c.get(f"/v1/orgs/{org}/runs/{rid}/twin/sync", headers=ha, params={"session_id": sess["id"]})
    assert r.status_code == 200, r.text
    assert c.get(f"/v1/orgs/{org}/runs/{rid}/twin/sync", headers=hb,
                 params={"session_id": sess["id"]}).status_code == 404
