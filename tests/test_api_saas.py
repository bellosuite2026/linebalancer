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
        self.admins: set[str] = set()
        self.payments: list[dict] = []
        self.rpc_calls: list[tuple[str, dict]] = []

    # --- super admin : la base refait le contrôle (comme private.require_super_admin)
    def is_super_admin(self, tok):
        return self._uid(tok) in self.admins

    def rpc(self, tok, name, args=None):
        args = args or {}
        if name == "admin_whoami":
            return self.is_super_admin(tok)
        if not self.is_super_admin(tok):
            raise StoreError(403, "Action non autorisée")
        self.rpc_calls.append((name, args))
        if name == "admin_revenue":
            return {"currency": "TND", "payments_count": len(self.payments),
                    "total_tnd": sum(float(p["amount_tnd"]) for p in self.payments)}
        if name == "admin_record_payment":
            row = {"id": str(uuid.uuid4()), "amount_tnd": args["p_amount"], "plan_code": args["p_plan"]}
            self.payments.append(row)
            return row
        if name == "admin_delete_user":
            if args["p_confirm_email"] != "victime@test.tn":
                raise StoreError(422, "Confirmation incorrecte")
            return {"email": "victime@test.tn", "deleted_orgs": 1}
        return {"ok": True}

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


# ------------------------------------------------------------------ super admin
def test_admin_routes_forbidden_for_normal_user(ctx):
    c, store, A, _B = ctx
    assert c.get("/v1/admin/overview").status_code == 401
    for method, path, body in [("get", "/v1/admin/overview", None), ("get", "/v1/admin/users", None),
                               ("get", "/v1/admin/orgs", None), ("get", "/v1/admin/payments", None),
                               ("post", f"/v1/admin/users/{uuid.uuid4()}/suspend", {"suspended": True})]:
        r = c.request(method.upper(), path, json=body, headers=A)
        assert r.status_code == 403, path
    assert store.rpc_calls == []
    assert c.get("/v1/me", headers=A).json()["is_super_admin"] is False


def _admin(ctx):
    c, store, A, B = ctx
    store.admins.add(jwt.decode(A["Authorization"][7:], options={"verify_signature": False})["sub"])
    return c, store, A, B


def test_admin_overview_payments_and_actions(ctx):
    c, store, A, _B = _admin(ctx)
    assert c.get("/v1/me", headers=A).json()["is_super_admin"] is True
    assert c.get("/v1/admin/overview", headers=A).json()["payments_count"] == 0
    org = str(uuid.uuid4())
    r = c.post("/v1/admin/payments", headers=A, json={"org_id": org, "plan_code": "atelier", "amount_tnd": "149",
                                                       "period_start": "2026-11-01", "period_end": "2026-11-30"})
    assert r.status_code == 201
    name, args = store.rpc_calls[-1]
    assert name == "admin_record_payment" and args["p_amount"] == "149" and args["p_activate"] is True
    assert c.get("/v1/admin/overview", headers=A).json()["total_tnd"] == 149
    bad = c.post("/v1/admin/payments", headers=A, json={"org_id": org, "plan_code": "atelier", "amount_tnd": -1})
    assert bad.status_code == 422
    bad = c.post("/v1/admin/payments", headers=A, json={"org_id": org, "plan_code": "inconnu", "amount_tnd": 1})
    assert bad.status_code == 422
    bad = c.post("/v1/admin/payments", headers=A, json={"org_id": org, "plan_code": "usine", "amount_tnd": 1,
                                                         "period_start": "2026-11-30", "period_end": "2026-11-01"})
    assert bad.status_code == 422
    assert c.put(f"/v1/admin/orgs/{org}/plan", headers=A,
                 json={"plan_code": "usine", "status": "active"}).status_code == 200
    assert c.put(f"/v1/admin/orgs/{org}/plan", headers=A,
                 json={"plan_code": "usine", "status": "gratuit"}).status_code == 422
    u = str(uuid.uuid4())
    assert c.post(f"/v1/admin/users/{u}/suspend", headers=A, json={"suspended": True}).status_code == 200
    assert c.request("DELETE", f"/v1/admin/users/{u}", headers=A,
                     json={"confirm_email": "autre@test.tn"}).status_code == 422
    r = c.request("DELETE", f"/v1/admin/users/{u}", headers=A, json={"confirm_email": "victime@test.tn"})
    assert r.status_code == 200 and r.json()["deleted_orgs"] == 1
    assert c.post("/v1/admin/users/pas-un-uuid/suspend", headers=A, json={"suspended": True}).status_code == 404


def test_super_admin_has_no_plan_cap(ctx):
    c, _s, A, _B = _admin(ctx)
    org = c.post("/v1/orgs", json={"name": "Atelier SA"}, headers=A).json()["id"]
    big = dict(PROBLEM, operations=PROBLEM["operations"] + [{"id": "D", "duration": 0.1}])
    assert c.post(f"/v1/orgs/{org}/runs", json={"problem": big}, headers=A).status_code == 202
