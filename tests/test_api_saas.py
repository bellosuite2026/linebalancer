"""Tests hors-ligne des routes compte/ateliers (auth Supabase simulée, store en mémoire).

Le comportement réel (RLS, quotas SQL) est couvert par scripts/e2e_supabase.py.
"""
from __future__ import annotations

import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from api.auth import AuthError, SupabaseAuth  # noqa: E402
from api.main import create_app  # noqa: E402
from api.settings import Settings  # noqa: E402
from api.store import StoreError  # noqa: E402

URL = "https://exemple.supabase.co"
KEY = ec.generate_private_key(ec.SECP256R1())


class _Jwk:
    def __init__(self, key):
        self.key = key


class FakeJwks:
    def get_signing_key_from_jwt(self, _token):
        return _Jwk(KEY.public_key())


def token(sub: str, *, exp: int = 3600, aud: str = "authenticated", iss: str = URL + "/auth/v1",
          role: str = "authenticated") -> str:
    now = int(time.time())
    return jwt.encode({"sub": sub, "email": f"{sub[:4]}@test.tn", "aud": aud, "iss": iss, "role": role,
                       "iat": now, "exp": now + exp}, KEY, algorithm="ES256", headers={"kid": "k1"})


class FakeStore:
    """Reproduit le minimum : appartenance, quotas de lignes, calculs."""

    def __init__(self):
        self.orgs, self.members, self.lines, self.problems, self.runs = {}, {}, {}, {}, {}

    def _uid(self, tok):
        return jwt.decode(tok, options={"verify_signature": False})["sub"]

    def my_orgs(self, tok, uid):
        return [{**self.orgs[o], "role": r} for (o, u), r in self.members.items() if u == uid]

    def create_org(self, tok, name, country="TN"):
        oid = str(uuid.uuid4())
        self.orgs[oid] = {"id": oid, "name": name, "country": country}
        self.members[(oid, self._uid(tok))] = "owner"
        return self.orgs[oid]

    def member_role(self, tok, org, uid):
        return self.members.get((org, uid))

    def org_plan(self, tok, org):
        return {"plan_code": "essai", "status": "trialing",
                "plan": {"code": "essai", "max_lines": 2, "max_operations": 3, "cpsat": True}}

    def list_members(self, tok, org):
        return [{"user_id": u, "role": r} for (o, u), r in self.members.items() if o == org]

    def list_lines(self, tok, org):
        return [l for l in self.lines.values() if l["org_id"] == org]

    def create_line(self, tok, org, uid, data):
        if len(self.list_lines(tok, org)) >= 2:
            raise StoreError(409, "Quota de lignes atteint")
        lid = str(uuid.uuid4())
        self.lines[lid] = {"id": lid, "org_id": org, **data}
        return self.lines[lid]

    def delete_line(self, tok, org, lid):
        return self.lines.pop(lid, None) is not None

    def create_problem(self, tok, org, uid, problem, line_id=None):
        pid = str(uuid.uuid4())
        self.problems[pid] = {"id": pid, "org_id": org, "payload": problem, "name": problem["name"]}
        return self.problems[pid]

    def list_problems(self, tok, org, line_id=None, limit=50):
        return [{k: v for k, v in p.items() if k != "payload"} for p in self.problems.values()
                if p["org_id"] == org]

    def get_problem(self, tok, org, pid):
        p = self.problems.get(pid)
        if not p or p["org_id"] != org:
            raise StoreError(404, "Introuvable.")
        return p

    def create_run(self, tok, org, uid, *, kind, solver, params, problem_id):
        rid = str(uuid.uuid4())
        self.runs[rid] = {"id": rid, "org_id": org, "kind": kind, "solver": solver, "status": "queued",
                          "params": params, "problem_id": problem_id}
        return dict(self.runs[rid])

    def update_run(self, tok, rid, fields):
        self.runs[rid].update(fields)

    def list_runs(self, tok, org, problem_id=None, limit=50):
        return [{k: v for k, v in r.items() if k != "result"} for r in self.runs.values() if r["org_id"] == org]

    def get_run(self, tok, org, rid):
        r = self.runs.get(rid)
        if not r or r["org_id"] != org:
            raise StoreError(404, "Introuvable.")
        return r


PROBLEM = {"name": "t", "target_cycle_time": 1.0, "operations": [
    {"id": "A", "duration": 0.6}, {"id": "B", "duration": 0.5, "predecessors": ["A"]},
    {"id": "C", "duration": 0.7, "predecessors": ["A"]}]}


@pytest.fixture()
def ctx():
    s = Settings(supabase_url=URL, supabase_anon_key="sb_publishable_test")
    store = FakeStore()
    app = create_app(s, auth=SupabaseAuth(URL, jwk_client=FakeJwks()), store=store)
    with TestClient(app) as c:
        a, b = str(uuid.uuid4()), str(uuid.uuid4())
        yield c, store, {"Authorization": f"Bearer {token(a)}"}, {"Authorization": f"Bearer {token(b)}"}


# ------------------------------------------------------------------ auth
def test_verify_ok():
    p = SupabaseAuth(URL, jwk_client=FakeJwks()).verify(token("u1"))
    assert p.user_id == "u1"


@pytest.mark.parametrize("bad", [
    dict(exp=-120), dict(aud="autre"), dict(iss="https://pirate/auth/v1"), dict(role="anon")])
def test_verify_rejects(bad):
    with pytest.raises(AuthError):
        SupabaseAuth(URL, jwk_client=FakeJwks()).verify(token("u1", **bad))


def test_verify_rejects_other_key():
    other = ec.generate_private_key(ec.SECP256R1())
    t = jwt.encode({"sub": "x", "aud": "authenticated", "iss": URL + "/auth/v1", "role": "authenticated",
                    "exp": int(time.time()) + 60}, other, algorithm="ES256")
    with pytest.raises(AuthError):
        SupabaseAuth(URL, jwk_client=FakeJwks()).verify(t)


def test_hs256_refused_without_secret():
    t = jwt.encode({"sub": "x", "aud": "authenticated", "role": "authenticated",
                    "exp": int(time.time()) + 60}, "s" * 32, algorithm="HS256")
    with pytest.raises(AuthError):
        SupabaseAuth(URL, jwk_client=FakeJwks()).verify(t)


# ------------------------------------------------------------------ routes
def test_requires_bearer(ctx):
    c, *_ = ctx
    assert c.get("/v1/me").status_code == 401
    assert c.post("/v1/precheck", json=PROBLEM).status_code == 401  # plus de mode « dev » ouvert


def test_org_isolation_and_lines(ctx):
    c, _store, A, B = ctx
    org = c.post("/v1/orgs", json={"name": "Atelier A"}, headers=A).json()["id"]
    assert c.get("/v1/me", headers=A).json()["orgs"][0]["role"] == "owner"
    assert c.get(f"/v1/orgs/{org}", headers=B).status_code == 404
    assert c.get("/v1/orgs/pas-un-uuid", headers=A).status_code == 404
    assert c.post(f"/v1/orgs/{org}/lines", json={"name": "L1"}, headers=A).status_code == 201
    assert c.post(f"/v1/orgs/{org}/lines", json={"name": "L2"}, headers=A).status_code == 201
    assert c.post(f"/v1/orgs/{org}/lines", json={"name": "L3"}, headers=A).status_code == 409


def test_run_lifecycle(ctx):
    c, store, A, B = ctx
    org = c.post("/v1/orgs", json={"name": "Atelier A"}, headers=A).json()["id"]
    r = c.post(f"/v1/orgs/{org}/runs", json={"problem": PROBLEM}, headers=A)
    assert r.status_code == 202 and r.json()["problem_id"]
    rid = r.json()["id"]
    for _ in range(50):
        d = c.get(f"/v1/orgs/{org}/runs/{rid}", headers=A).json()
        if d["status"] in ("done", "failed"):
            break
        time.sleep(0.05)
    assert d["status"] == "done" and d["stations_used"] >= 2 and d["result"]["success"]
    assert c.get(f"/v1/orgs/{org}/runs/{rid}", headers=B).status_code == 404
    assert c.get(f"/v1/orgs/{org}/runs/{rid}/export.json", headers=A).status_code == 200
    x = c.get(f"/v1/orgs/{org}/runs/{rid}/export.xlsx", headers=A)
    assert x.status_code == 200 and x.content[:2] == b"PK"
    import io as _io
    from openpyxl import load_workbook
    wb = load_workbook(_io.BytesIO(x.content))
    assert {"Synthèse", "Répartition", "Graphique", "Gamme"} <= set(wb.sheetnames)
    pdf = c.get(f"/v1/orgs/{org}/runs/{rid}/export.pdf", headers=A)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    assert c.get(f"/v1/orgs/{org}/runs/{rid}/export.pdf", headers=B).status_code == 404
    # gamme réutilisée pour la cadence minimale
    r2 = c.post(f"/v1/orgs/{org}/runs", json={"kind": "min_cycle", "problem_id": r.json()["problem_id"]},
                headers=A)
    assert r2.status_code == 202


def test_plan_operation_cap(ctx):
    c, _s, A, _B = ctx
    org = c.post("/v1/orgs", json={"name": "Atelier A"}, headers=A).json()["id"]
    big = dict(PROBLEM, operations=PROBLEM["operations"] + [{"id": "D", "duration": 0.1}])
    assert c.post(f"/v1/orgs/{org}/runs", json={"problem": big}, headers=A).status_code == 413


def test_run_requires_problem(ctx):
    c, _s, A, _B = ctx
    org = c.post("/v1/orgs", json={"name": "Atelier A"}, headers=A).json()["id"]
    assert c.post(f"/v1/orgs/{org}/runs", json={"kind": "balance"}, headers=A).status_code == 422
