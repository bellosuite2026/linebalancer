"""Suivi de production : plan figé, indicateurs temps réel, routes (store en mémoire), exports."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from api import production  # noqa: E402
from api.auth import SupabaseAuth  # noqa: E402
from api.main import create_app  # noqa: E402
from api.settings import Settings  # noqa: E402
from api.store import StoreError  # noqa: E402
from tests.test_api_saas import URL, FakeJwks, FakeStore, token  # noqa: E402

PROBLEM = {"name": "Polo", "target_cycle_time": 1.0, "operations": [
    {"id": "A", "name": "Épaules", "duration": 0.6}, {"id": "B", "name": "Col", "duration": 0.5},
    {"id": "C", "name": "Ourlet", "duration": 0.9}]}
RUN = {"id": "r1", "kind": "balance", "status": "done", "problem_id": "p1", "result": {
    "solver": "rpw", "target_cycle_time": 1.0, "actual_cycle_time": 0.9, "station_details": [
        {"station": 1, "operations": ["A"], "total_time": 0.6, "load_pct": 60, "workers": ["Amira"],
         "worker_ids": ["W1"], "parallel": 1},
        {"station": 2, "operations": ["B"], "total_time": 0.5, "load_pct": 50, "workers": ["Sami"], "parallel": 1},
        {"station": 3, "operations": ["C"], "total_time": 0.9, "load_pct": 90, "workers": ["Hana"], "parallel": 1}]}}

TUNIS = timezone(timedelta(hours=1))  # Africa/Tunis : UTC+1 toute l'année


def make_session(**kw):
    plan = production.build_plan(RUN, PROBLEM)
    s = {"id": "s1", "status": "open", "session_date": "2026-10-27", "shift_start": "08:00:00",
         "shift_hours": 8, "timezone": "Africa/Tunis", "target_per_hour": 60, "plan": plan}
    s.update(kw)
    return s


def entry(station, hour, pieces=0, **kw):
    return {"id": str(uuid.uuid4()), "client_id": str(uuid.uuid4()), "station": station, "slot_hour": hour,
            "pieces": pieces, "defects": kw.pop("defects", 0), "rework": 0, "voided": False, **kw}


# ------------------------------------------------------------------ calculs
def test_build_plan():
    plan = production.build_plan(RUN, PROBLEM)
    assert [s["station"] for s in plan["stations"]] == [1, 2, 3]
    assert plan["bottleneck_station"] == 3
    assert plan["stations"][0]["operations"][0] == {"id": "A", "name": "Épaules", "minutes": 0.6, "shared": False}
    assert plan["sam_total"] == 2.0 and plan["operators"] == 3
    assert production.default_target_per_hour(plan) == pytest.approx(66.7)


def test_dashboard_kpis():
    s = make_session()
    now = datetime(2026, 10, 27, 10, 0, tzinfo=TUNIS)  # 2 h écoulées
    entries = [entry(1, 8, 60), entry(1, 9, 55), entry(2, 8, 58), entry(2, 9, 50),
               entry(3, 8, 50), entry(3, 9, 40, defects=3),
               entry(2, 9, downtime_reason="panne", downtime_minutes=20),
               entry(3, 9, 99, voided=True)]
    d = production.dashboard(s, entries, now)
    assert d["elapsed_minutes"] == 120
    assert d["output"] == 90 and d["expected_to_date"] == 120 and d["pct_target"] == 75
    assert d["bottleneck_planned"] == 3 and d["bottleneck_observed"] == 3
    assert d["wip_total"] == (115 - 108) + (108 - 90)
    # minutes produites = 115×0,6 + 108×0,5 + 90×0,9 = 204 ; présence = 3 × 120
    assert d["efficiency"] == pytest.approx(204 / 360 * 100, abs=0.1)
    assert {x["reason"]: x["minutes"] for x in d["downtime_by_reason"]}["panne"] == 20
    assert d["hourly"][0] == {"hour": 8, "target": 60, "output": 50, "downtime_minutes": 0}
    assert d["hourly"][2]["target"] == 0  # 10 h pas encore commencée
    kinds = {(a["kind"], a.get("station")) for a in d["alerts"]}
    assert ("under_target", 3) in kinds and ("long_stop", 2) in kinds
    assert ("under_target", 1) not in kinds  # 115/120 = 96 %
    assert d["defects"] == 3


def test_ongoing_stop_and_absence():
    s = make_session()
    now = datetime(2026, 10, 27, 9, 0, tzinfo=TUNIS)
    start = (now - timedelta(minutes=18)).astimezone(timezone.utc).isoformat()
    entries = [entry(1, 8, downtime_reason="absence", downtime_start=start, downtime_minutes=None)]
    d = production.dashboard(s, entries, now)
    st1 = d["stations"][0]
    assert st1["ongoing_stop"]["ongoing"] and st1["downtime_minutes"] == 18
    assert st1["presence_minutes"] == 60 - 18
    assert d["alerts"][0]["level"] == "danger" and "en cours" in d["alerts"][0]["message"]


def test_closed_session_stops_clock():
    closed = datetime(2026, 10, 27, 9, 30, tzinfo=TUNIS).astimezone(timezone.utc).isoformat()
    s = make_session(status="closed", closed_at=closed)
    d = production.dashboard(s, [], datetime(2026, 10, 27, 15, 0, tzinfo=TUNIS))
    assert d["elapsed_minutes"] == 90 and not d["alerts"]


def test_before_shift_no_division_errors():
    d = production.dashboard(make_session(), [], datetime(2026, 10, 27, 6, 0, tzinfo=TUNIS))
    assert d["elapsed_minutes"] == 0 and d["efficiency"] is None and d["pct_target"] is None


def test_exports_render():
    s = make_session()
    entries = [entry(1, 8, 10), entry(3, 8, 8), entry(2, 8, downtime_reason="manque_fourniture",
                                                           downtime_minutes=5, comment="bobines")]
    d = production.dashboard(s, entries, datetime(2026, 10, 27, 9, 0, tzinfo=TUNIS))
    assert production.build_xlsx(s, d, entries, "Atelier test")[:2] == b"PK"
    assert production.build_pdf(s, d, "Atelier test")[:4] == b"%PDF"


# ------------------------------------------------------------------ routes
class ProdStore(FakeStore):
    def __init__(self):
        super().__init__()
        self.sessions, self.entries = {}, {}

    def get_run(self, tok, org, rid):
        if rid in self.runs:
            return super().get_run(tok, org, rid)
        raise StoreError(404, "Introuvable.")

    def list_sessions(self, tok, org, limit=50):
        return [s for s in self.sessions.values() if s["org_id"] == org]

    def create_session(self, tok, org, uid, data):
        s = {"id": str(uuid.uuid4()), "org_id": org, "opened_by": uid, "status": "open",
             "session_date": data.get("session_date", "2026-10-27"), **data}
        self.sessions[s["id"]] = s
        return s

    def get_session(self, tok, org, sid):
        s = self.sessions.get(sid)
        if not s or s["org_id"] != org:
            raise StoreError(404, "Introuvable.")
        return s

    def update_session(self, tok, org, sid, fields):
        s = self.get_session(tok, org, sid)
        s.update(fields)
        return s

    def list_entries(self, tok, org, sid):
        return [e for e in self.entries.values() if e["session_id"] == sid]

    def upsert_entries(self, tok, sid, rows):
        out = []
        for r in rows:
            cid = r.get("client_id") or str(uuid.uuid4())
            e = self.entries.get(cid, {"id": str(uuid.uuid4()), "client_id": cid, "session_id": sid,
                                       "pieces": 0, "defects": 0, "rework": 0, "voided": False})
            e.update(r)
            self.entries[cid] = e
            out.append(e)
        return out

    def update_entry(self, tok, org, sid, eid, fields):
        for e in self.entries.values():
            if e["id"] == eid:
                e.update(fields)
                return e
        raise StoreError(404, "Saisie introuvable.")


@pytest.fixture()
def prod():
    store = ProdStore()
    app = create_app(Settings(supabase_url=URL, supabase_anon_key="sb_publishable_test"),
                     auth=SupabaseAuth(URL, jwk_client=FakeJwks()), store=store)
    with TestClient(app) as c:
        a, b = str(uuid.uuid4()), str(uuid.uuid4())
        ha, hb = {"Authorization": f"Bearer {token(a)}"}, {"Authorization": f"Bearer {token(b)}"}
        org = c.post("/v1/orgs", json={"name": "Atelier A"}, headers=ha).json()["id"]
        store.problems["p1"] = {"id": "p1", "org_id": org, "payload": PROBLEM}
        store.runs["r1"] = {**RUN, "org_id": org}
        yield c, store, org, ha, hb


def test_session_flow(prod):
    c, store, org, ha, hb = prod
    base = f"/v1/orgs/{org}/production/sessions"
    r = c.post(base, json={"run_id": "r1"}, headers=ha)
    assert r.status_code == 404  # identifiant non UUID
    rid = str(uuid.uuid4())
    store.runs[rid] = {**RUN, "id": rid, "org_id": org}
    r = c.post(base, json={"run_id": rid, "model": "Polo M", "shift_start": "07:30"}, headers=ha)
    assert r.status_code == 201, r.text
    sess = r.json()
    assert sess["target_per_hour"] == pytest.approx(66.7) and sess["plan"]["bottleneck_station"] == 3
    sid = sess["id"]

    # autre atelier : invisible
    assert c.get(f"{base}/{sid}", headers=hb).status_code == 404

    cid = str(uuid.uuid4())
    r = c.post(f"{base}/{sid}/entries", headers=ha, json={"entries": [
        {"client_id": cid, "station": 1, "pieces": 10, "slot_hour": 8},
        {"station": 3, "pieces": 7, "slot_hour": 8}]})
    assert r.status_code == 200 and r.json()["saved"] == 2
    # renvoi du même client_id (file hors ligne) = mise à jour, pas de doublon
    c.post(f"{base}/{sid}/entries", headers=ha, json={"entries": [{"client_id": cid, "station": 1,
                                                                   "pieces": 12, "slot_hour": 8}]})
    assert len(store.entries) == 2
    assert c.post(f"{base}/{sid}/entries", headers=ha,
                  json={"entries": [{"station": 9, "pieces": 1}]}).status_code == 422
    r = c.post(f"{base}/{sid}/entries", headers=ha, json={"entries": [{"station": 2}]})
    assert 0 <= r.json()["entries"][0]["slot_hour"] <= 23  # heure déduite

    d = c.get(f"{base}/{sid}/dashboard", headers=ha).json()
    assert d["stations"][0]["pieces"] == 12 and d["output"] == 7

    eid = store.entries[cid]["id"]
    assert c.patch(f"{base}/{sid}/entries/{eid}", json={"voided": True}, headers=ha).status_code == 200
    assert c.get(f"{base}/{sid}/dashboard", headers=ha).json()["stations"][0]["pieces"] == 0

    assert c.get(f"{base}/{sid}/export.xlsx", headers=ha).content[:2] == b"PK"
    assert c.get(f"{base}/{sid}/export.pdf", headers=ha).content[:4] == b"%PDF"

    assert c.patch(f"{base}/{sid}", json={"status": "closed"}, headers=ha).json()["status"] == "closed"
    assert c.post(f"{base}/{sid}/entries", headers=ha,
                  json={"entries": [{"station": 1, "pieces": 1}]}).status_code == 409
    assert len(c.get(base, headers=ha).json()) == 1


def test_reader_cannot_enter(prod):
    c, store, org, ha, hb = prod
    rid = str(uuid.uuid4())
    store.runs[rid] = {**RUN, "id": rid, "org_id": org}
    sid = c.post(f"/v1/orgs/{org}/production/sessions", json={"run_id": rid}, headers=ha).json()["id"]
    b_uid = [k for k in [hb["Authorization"].split()[1]]][0]
    store.members[(org, store._uid(b_uid))] = "lecteur"
    r = c.post(f"/v1/orgs/{org}/production/sessions/{sid}/entries", headers=hb,
               json={"entries": [{"station": 1, "pieces": 1}]})
    assert r.status_code == 403
    assert c.get(f"/v1/orgs/{org}/production/sessions/{sid}/dashboard", headers=hb).status_code == 200


def test_open_requires_done_run(prod):
    c, store, org, ha, _ = prod
    rid = str(uuid.uuid4())
    store.runs[rid] = {**RUN, "id": rid, "org_id": org, "status": "running"}
    assert c.post(f"/v1/orgs/{org}/production/sessions", json={"run_id": rid}, headers=ha).status_code == 409
