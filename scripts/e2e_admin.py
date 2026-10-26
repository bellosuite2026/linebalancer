"""Test de bout en bout du super admin contre le vrai projet Supabase.

Pré-requis : TLB_SUPABASE_URL, TLB_SUPABASE_ANON_KEY, E2E_PASSWORD,
  E2E_ADMIN_EMAIL (présent dans private.platform_admins, confirmé),
  E2E_CLIENT_EMAIL (utilisateur ordinaire confirmé, sans atelier ; il est SUPPRIMÉ à la fin).
Usage : python scripts/e2e_admin.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from api.main import create_app  # noqa: E402
from api.settings import Settings  # noqa: E402

URL = os.environ["TLB_SUPABASE_URL"].rstrip("/")
ANON = os.environ["TLB_SUPABASE_ANON_KEY"]
PWD = os.environ["E2E_PASSWORD"]
failed = 0


def login(email: str) -> httpx.Response:
    return httpx.post(f"{URL}/auth/v1/token?grant_type=password", headers={"apikey": ANON},
                      json={"email": email, "password": PWD}, timeout=20)


def ok(cond: bool, label: str) -> None:
    global failed
    print(("OK   " if cond else "ÉCHEC"), label)
    failed += 0 if cond else 1


def main() -> int:
    s = Settings.from_env()
    s.api_keys = set()
    admin_email, client_email = os.environ["E2E_ADMIN_EMAIL"], os.environ["E2E_CLIENT_EMAIL"]
    with TestClient(create_app(s)) as c:
        ta, tc = login(admin_email).json()["access_token"], login(client_email).json()["access_token"]
        A, C = {"Authorization": f"Bearer {ta}"}, {"Authorization": f"Bearer {tc}"}
        rest = lambda t: {"apikey": ANON, "Authorization": f"Bearer {t}"}  # noqa: E731

        ok(c.get("/v1/me", headers=A).json().get("is_super_admin") is True, "admin : is_super_admin = true")
        ok(c.get("/v1/me", headers=C).json().get("is_super_admin") is False, "client : is_super_admin = false")
        org = c.post("/v1/orgs", json={"name": "Atelier QA client"}, headers=C).json()["id"]

        for path in ("/v1/admin/overview", "/v1/admin/users", "/v1/admin/orgs", "/v1/admin/payments"):
            ok(c.get(path, headers=C).status_code == 403, f"client refusé sur {path}")
        ok(c.get("/v1/admin/users").status_code == 401, "sans jeton -> 401")
        r = httpx.post(f"{URL}/rest/v1/rpc/admin_users", headers=rest(tc), json={}, timeout=20)
        ok(r.status_code in (401, 403), f"client : RPC admin_users directe refusée ({r.status_code})")
        r = httpx.post(f"{URL}/rest/v1/rpc/admin_set_plan", headers=rest(tc), timeout=20,
                       json={"p_org": org, "p_plan": "groupe", "p_status": "active"})
        ok(r.status_code in (401, 403), f"client : auto-upgrade via RPC refusé ({r.status_code})")
        r = httpx.get(f"{URL}/rest/v1/payments?select=*", headers=rest(tc), timeout=20)
        ok(r.status_code == 200 and r.json() == [], "client : table payments invisible (RLS)")
        r = httpx.post(f"{URL}/rest/v1/payments", headers=rest(tc), timeout=20,
                       json={"org_name": "x", "plan_code": "usine", "amount_tnd": 1})
        ok(r.status_code in (401, 403), f"client : insertion directe de paiement refusée ({r.status_code})")
        r = httpx.post(f"{URL}/rest/v1/rpc/admin_users", headers={"apikey": ANON}, json={}, timeout=20)
        ok(r.status_code in (401, 403, 404), f"anonyme : RPC refusée ({r.status_code})")

        ov = c.get("/v1/admin/overview", headers=A).json()
        ok("by_month" in ov and len(ov["by_month"]) == 12, "admin : tableau de bord des gains (12 mois)")
        base_total = float(ov["total_tnd"])
        users = c.get("/v1/admin/users", headers=A).json()
        cu = next((u for u in users if u["email"] == client_email), None)
        ok(cu is not None and cu["orgs"][0]["name"] == "Atelier QA client", "admin : liste des utilisateurs + ateliers")
        orgs = c.get("/v1/admin/orgs", headers=A).json()
        ok(any(o["id"] == org and o["plan_code"] == "essai" for o in orgs), "admin : liste des ateliers")

        r = c.post("/v1/admin/payments", headers=A, json={"org_id": org, "plan_code": "atelier", "amount_tnd": "149",
                                                            "period_start": "2026-10-26", "period_end": "2026-11-25",
                                                            "method": "virement", "reference": "QA-E2E"})
        ok(r.status_code == 201, f"admin : paiement saisi ({r.status_code} {r.text[:120]})")
        pay_id = r.json().get("id")
        sub = c.get(f"/v1/orgs/{org}", headers=C).json()["plan"]
        ok(sub["plan_code"] == "atelier" and sub["status"] == "active", "paiement -> offre Atelier active côté client")
        ov = c.get("/v1/admin/overview", headers=A).json()
        ok(abs(float(ov["total_tnd"]) - base_total - 149) < 1e-6, "gains : total +149 TND")
        r = c.put(f"/v1/admin/orgs/{org}/plan", headers=A, json={"plan_code": "usine", "status": "canceled"})
        ok(r.status_code == 200, "admin : changement d'offre")
        r = c.post(f"/v1/orgs/{org}/lines", json={"name": "L1"}, headers=C)
        ok(r.status_code == 402, f"client résilié : création de ligne refusée ({r.status_code})")
        c.put(f"/v1/admin/orgs/{org}/plan", headers=A, json={"plan_code": "atelier", "status": "active"})

        # Suspension
        cid = cu["id"]
        ok(c.post(f"/v1/admin/users/{cid}/suspend", headers=A, json={"suspended": True}).status_code == 200,
           "admin : suspension")
        ok(c.get(f"/v1/orgs/{org}", headers=C).status_code == 404, "suspendu : jeton encore valide mais données bloquées")
        ok(login(client_email).status_code >= 400, "suspendu : connexion refusée")
        ok(c.post(f"/v1/admin/users/{cid}/suspend", headers=A, json={"suspended": False}).status_code == 200,
           "admin : réactivation")
        ok(login(client_email).status_code == 200, "réactivé : connexion acceptée")
        me_id = c.get("/v1/me", headers=A).json()["user_id"]
        ok(c.post(f"/v1/admin/users/{me_id}/suspend", headers=A, json={"suspended": True}).status_code == 409,
           "admin ne peut pas se suspendre lui-même")

        # Aucune limite pour le super admin (3 lignes sur un essai limité à 2)
        aorg = c.post("/v1/orgs", json={"name": "Atelier QA admin"}, headers=A).json()["id"]
        codes = [c.post(f"/v1/orgs/{aorg}/lines", json={"name": f"L{i}"}, headers=A).status_code for i in range(3)]
        ok(codes == [201, 201, 201], f"super admin : 3 lignes sur l'essai sans quota ({codes})")
        ok(c.get(f"/v1/orgs/{org}", headers=A).status_code == 404, "super admin n'entre pas dans les données d'un client")

        ok(c.delete(f"/v1/admin/payments/{pay_id}", headers=A).status_code == 204, "admin : suppression du paiement")
        r = c.request("DELETE", f"/v1/admin/orgs/{aorg}", headers=A, json={"confirm_name": "mauvais"})
        ok(r.status_code == 422, "suppression d'atelier : mauvaise confirmation refusée")
        r = c.request("DELETE", f"/v1/admin/orgs/{aorg}", headers=A, json={"confirm_name": "Atelier QA admin"})
        ok(r.status_code == 200, "admin : suppression d'atelier")
        r = c.request("DELETE", f"/v1/admin/users/{cid}", headers=A, json={"confirm_email": "faux@example.com"})
        ok(r.status_code == 422, "suppression utilisateur : mauvaise confirmation refusée")
        r = c.request("DELETE", f"/v1/admin/users/{cid}", headers=A, json={"confirm_email": client_email})
        ok(r.status_code == 200 and r.json().get("deleted_orgs") == 1,
           f"admin : suppression utilisateur + son atelier ({r.text[:120]})")
        ok(all(o["id"] != org for o in c.get("/v1/admin/orgs", headers=A).json()), "atelier du client supprimé")
    print(f"\n{failed} échec(s)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
