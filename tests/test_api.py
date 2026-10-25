"""Tests de l'API FastAPI (moteur réel, échantillon chemise homme)."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from api.main import create_app  # noqa: E402
from api.settings import Settings  # noqa: E402

SAMPLES = Path(__file__).resolve().parent.parent / "data" / "samples"
SAM = SAMPLES / "sam_chemise_homme.csv"
WS = SAMPLES / "workstations_chemise.csv"
WK = SAMPLES / "workers_chemise.csv"


@pytest.fixture(scope="module")
def client():
    with TestClient(create_app(Settings())) as c:
        yield c


@pytest.fixture(scope="module")
def chemise(client):
    files = {
        "sam": (SAM.name, SAM.read_bytes(), "text/csv"),
        "workstations": (WS.name, WS.read_bytes(), "text/csv"),
        "workers": (WK.name, WK.read_bytes(), "text/csv"),
    }
    r = client.post("/v1/import/problem", files=files, data={"target_cycle_time": "4.5", "name": "chemise"})
    assert r.status_code == 200, r.text
    return r.json()


def simple_problem(cycle=1.0):
    return {
        "name": "mini",
        "target_cycle_time": cycle,
        "operations": [
            {"id": "A", "duration": 0.6},
            {"id": "B", "duration": 0.5, "predecessors": ["A"]},
            {"id": "C", "duration": 0.4, "predecessors": ["A"]},
            {"id": "D", "duration": 0.3, "predecessors": ["B", "C"]},
        ],
    }


def wait_job(client, job_id, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/v1/jobs/{job_id}").json()
        if j["status"] in ("done", "failed"):
            return j
        time.sleep(0.05)
    raise AssertionError("job timeout")


# --- Santé / import ---------------------------------------------------------

def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert "rpw" in r.json()["solvers"]


def test_solvers(client):
    names = {s["name"] for s in client.get("/v1/solvers").json()}
    assert {"rpw", "cp_sat"} <= names


def test_import_sam(client):
    r = client.post("/v1/import/sam", files={"file": (SAM.name, SAM.read_bytes(), "text/csv")})
    assert r.status_code == 200
    ops = r.json()["operations"]
    assert len(ops) == 21 and ops[0]["id"] == "OP010"


def test_import_workers_and_workstations(client):
    r = client.post("/v1/import/workers", files={"file": (WK.name, WK.read_bytes(), "text/csv")})
    assert r.status_code == 200 and r.json()["workers"]
    r = client.post("/v1/import/workstations", files={"file": (WS.name, WS.read_bytes(), "text/csv")})
    assert r.status_code == 200 and r.json()["workstations"]


def test_import_bad_format(client):
    r = client.post("/v1/import/sam", files={"file": ("x.txt", b"hello", "text/plain")})
    assert r.status_code == 422


def test_import_missing_columns(client):
    r = client.post("/v1/import/sam", files={"file": ("x.csv", b"foo;bar\n1;2\n", "text/csv")})
    assert r.status_code == 422


def test_import_problem_precheck_ok(chemise):
    assert chemise["precheck"]["feasible"] is True
    assert len(chemise["problem"]["operations"]) == 21


# --- Diagnostic -------------------------------------------------------------

def test_precheck_detects_capacity(chemise, client):
    p = dict(chemise["problem"], target_cycle_time=1.0)
    r = client.post("/v1/precheck", json=p)
    assert r.status_code == 200
    body = r.json()
    assert body["feasible"] is False
    assert any(i["code"] in ("MACHINE_CAPACITY", "WORKERS_SHORT") for i in body["issues"])


def test_precheck_unknown_predecessor(client):
    p = simple_problem()
    p["operations"][1]["predecessors"] = ["ZZZ"]
    body = client.post("/v1/precheck", json=p).json()
    assert body["feasible"] is False
    assert any(i["code"] == "PRED_UNKNOWN" for i in body["issues"])


def test_validation_rejects_bad_input(client):
    assert client.post("/v1/precheck", json={"target_cycle_time": 0, "operations": []}).status_code == 422


# --- Équilibrage ------------------------------------------------------------

CPSAT_WS_BUG = pytest.mark.xfail(
    strict=False,
    reason="Bug moteur connu (CPSatSolver._assign_workstations) : une station sans type machine "
           "prend une piqueuse_plate, une autre station peut rester sans poste (selon la solution CP-SAT, non déterministe). L'API le signale via violations.")


@pytest.mark.parametrize("solver", ["rpw", pytest.param("cp_sat", marks=CPSAT_WS_BUG)])
def test_balance_chemise(chemise, client, solver):
    r = client.post("/v1/balance", json={"problem": chemise["problem"], "solver": solver,
                                         "time_limit_seconds": 10})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["success"] is True
    assert res["stations_used"] == 12
    assert res["actual_cycle_time"] <= 4.5 + 1e-6
    assert res["violations"] == [] and res["compliant"] is True
    assert set(res["operation_assignments"]) == {o["id"] for o in chemise["problem"]["operations"]}


def test_cp_sat_violation_is_surfaced(chemise, client):
    """Tant que le bug moteur existe, l'API ne doit pas le masquer."""
    res = client.post("/v1/balance", json={"problem": chemise["problem"], "solver": "cp_sat"}).json()
    if res["violations"]:
        assert res["compliant"] is False


def test_balance_simple_respects_precedence(client):
    res = client.post("/v1/balance", json={"problem": simple_problem(), "solver": "rpw"}).json()
    a = res["operation_assignments"]
    assert a["A"] <= a["B"] <= a["D"] and a["A"] <= a["C"] <= a["D"]


def test_balance_infeasible_reports(chemise, client):
    p = dict(chemise["problem"], target_cycle_time=1.0)
    res = client.post("/v1/balance", json={"problem": p, "solver": "rpw"}).json()
    assert res["success"] is False
    assert res["error_message"]


def test_too_many_operations():
    app = create_app(Settings(max_operations=2))
    with TestClient(app) as c:
        r = c.post("/v1/balance", json={"problem": simple_problem()})
        assert r.status_code == 413


def test_min_cycle_chemise(chemise, client):
    r = client.post("/v1/min-cycle", json={"problem": chemise["problem"], "solver": "rpw"})
    assert r.status_code == 200
    body = r.json()
    assert body["found"] is True
    assert body["min_cycle_time"] == pytest.approx(4.41, abs=0.05)
    assert body["result"]["stations_used"] == 12


# --- Export -----------------------------------------------------------------

def test_export_json(client):
    r = client.post("/v1/export/json", json={"problem": simple_problem(), "solver": "rpw"})
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    body = r.json()
    assert body["result"]["success"] is True and body["problem"]["name"] == "mini"


# --- File de calculs --------------------------------------------------------

def test_job_cp_sat(chemise, client):
    r = client.post("/v1/jobs", json={"kind": "balance", "balance": {
        "problem": chemise["problem"], "solver": "cp_sat", "time_limit_seconds": 10}})
    assert r.status_code == 202
    j = wait_job(client, r.json()["id"])
    assert j["status"] == "done", j["error"]
    assert j["result"]["stations_used"] == 12
    e = client.get(f"/v1/jobs/{j['id']}/export.json")
    assert e.status_code == 200 and e.json()["result"]["success"] is True


def test_job_min_cycle(client):
    r = client.post("/v1/jobs", json={"kind": "min_cycle", "min_cycle": {"problem": simple_problem()}})
    j = wait_job(client, r.json()["id"])
    assert j["status"] == "done" and j["result"]["found"] is True


def test_job_missing_payload(client):
    assert client.post("/v1/jobs", json={"kind": "balance"}).status_code == 422


def test_job_not_found(client):
    assert client.get("/v1/jobs/inexistant").status_code == 404


# --- Clés API (isolation des ateliers) --------------------------------------

def test_api_key_and_tenant_isolation():
    app = create_app(Settings(api_keys={"atelier-a", "atelier-b"}))
    with TestClient(app) as c:
        assert c.get("/health").status_code == 200
        assert c.post("/v1/precheck", json=simple_problem()).status_code == 401
        a = {"X-API-Key": "atelier-a"}
        r = c.post("/v1/jobs", headers=a, json={"kind": "balance", "balance": {"problem": simple_problem()}})
        assert r.status_code == 202
        jid = r.json()["id"]
        assert c.get(f"/v1/jobs/{jid}", headers={"X-API-Key": "atelier-b"}).status_code == 404
        assert c.get(f"/v1/jobs/{jid}", headers=a).status_code == 200
