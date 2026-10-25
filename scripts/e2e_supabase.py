"""Test de bout en bout API + Supabase réel (comptes, RLS, quotas, calculs historisés).

Pré-requis (variables d'environnement) :
  TLB_SUPABASE_URL, TLB_SUPABASE_ANON_KEY
  E2E_EMAIL_A / E2E_EMAIL_B / E2E_PASSWORD : deux utilisateurs de test confirmés
Usage : python scripts/e2e_supabase.py
Les ateliers créés sont supprimés à la fin (propriétaire = utilisateur A ou B).
"""
from __future__ import annotations

import os
import sys
import time
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


def login(email: str) -> str:
    r = httpx.post(f"{URL}/auth/v1/token?grant_type=password", headers={"apikey": ANON},
                   json={"email": email, "password": PWD}, timeout=20)
    r.raise_for_status()
    return r.json()["access_token"]


def ok(cond: bool, label: str) -> None:
    print(("OK   " if cond else "ÉCHEC"), label)
    if not cond:
        ok.failed += 1  # type: ignore[attr-defined]


ok.failed = 0  # type: ignore[attr-defined]

PROBLEM = {
    "name": "e2e-chemise", "target_cycle_time": 1.0,
    "operations": [
        {"id": "A", "name": "Col", "duration": 0.6},
        {"id": "B", "name": "Manches", "duration": 0.5, "predecessors": ["A"]},
        {"id": "C", "name": "Côtés", "duration": 0.7, "predecessors": ["A"]},
        {"id": "D", "name": "Ourlet", "duration": 0.4, "predecessors": ["B", "C"]},
    ],
}


def main() -> int:
    s = Settings.from_env()
    s.api_keys = set()
    app = create_app(s)
    created: list[tuple[str, str]] = []
    with TestClient(app) as c:
        ta, tb = login(os.environ["E2E_EMAIL_A"]), login(os.environ["E2E_EMAIL_B"])
        A, B = {"Authorization": f"Bearer {ta}"}, {"Authorization": f"Bearer {tb}"}

        ok(c.get("/v1/me").status_code == 401, "sans jeton -> 401")
        ok(c.get("/v1/me", headers={"Authorization": "Bearer abc"}).status_code == 401, "jeton bidon -> 401")
        me = c.get("/v1/me", headers=A)
        ok(me.status_code == 200, f"/v1/me utilisateur A ({me.status_code})")

        r = c.post("/v1/orgs", json={"name": "Atelier E2E A"}, headers=A)
        ok(r.status_code == 201, f"création atelier A ({r.status_code} {r.text[:120]})")
        org = r.json()["id"]
        created.append((org, ta))

        info = c.get(f"/v1/orgs/{org}", headers=A).json()
        ok(info.get("role") == "owner", "A est propriétaire")
        ok((info.get("plan") or {}).get("plan_code") == "essai", "essai 30 jours actif")

        ok(c.get(f"/v1/orgs/{org}", headers=B).status_code == 404, "B ne voit pas l'atelier de A (RLS)")
        ok(c.get(f"/v1/orgs/{org}/lines", headers=B).status_code == 404, "B ne liste pas les lignes de A")

        l1 = c.post(f"/v1/orgs/{org}/lines", json={"name": "Ligne 1", "product": "chemise"}, headers=A)
        ok(l1.status_code == 201, f"ligne 1 créée ({l1.status_code} {l1.text[:120]})")
        l2 = c.post(f"/v1/orgs/{org}/lines", json={"name": "Ligne 2"}, headers=A)
        ok(l2.status_code == 201, "ligne 2 créée")
        l3 = c.post(f"/v1/orgs/{org}/lines", json={"name": "Ligne 3"}, headers=A)
        ok(l3.status_code == 409, f"3e ligne refusée par le quota essai ({l3.status_code} {l3.text[:100]})")

        # B tente d'écrire directement dans l'atelier de A via PostgREST (contourner l'API)
        raw = httpx.post(f"{URL}/rest/v1/lines", headers={"apikey": ANON, "Authorization": f"Bearer {tb}"},
                         json={"org_id": org, "name": "intrus",
                               "created_by": me.json()["user_id"]}, timeout=20)
        ok(raw.status_code in (401, 403), f"écriture directe de B bloquée par RLS ({raw.status_code})")
        raw = httpx.patch(f"{URL}/rest/v1/subscriptions?org_id=eq.{org}",
                          headers={"apikey": ANON, "Authorization": f"Bearer {ta}", "Prefer": "return=representation"},
                          json={"plan_code": "groupe", "status": "active"}, timeout=20)
        ok(raw.status_code in (401, 403) or raw.json() == [], f"A ne peut pas s'auto-upgrader ({raw.status_code})")

        line_id = l1.json()["id"]
        run = c.post(f"/v1/orgs/{org}/runs", headers=A,
                     json={"kind": "balance", "solver": "rpw", "problem": PROBLEM, "line_id": line_id})
        ok(run.status_code == 202, f"calcul RPW accepté ({run.status_code} {run.text[:150]})")
        rid = run.json()["id"]
        detail = {}
        for _ in range(60):
            detail = c.get(f"/v1/orgs/{org}/runs/{rid}", headers=A).json()
            if detail.get("status") in ("done", "failed"):
                break
            time.sleep(0.5)
        ok(detail.get("status") == "done", f"calcul terminé ({detail.get('status')} {detail.get('error','')})")
        ok(detail.get("stations_used") and detail.get("result", {}).get("stations_used") == detail["stations_used"],
           f"synthèse historisée ({detail.get('stations_used')} stations, eff. {detail.get('efficiency')})")
        ok(c.get(f"/v1/orgs/{org}/runs/{rid}", headers=B).status_code == 404, "B ne lit pas le calcul de A")

        mc = c.post(f"/v1/orgs/{org}/runs", headers=A,
                    json={"kind": "min_cycle", "problem_id": run.json()["problem_id"]})
        ok(mc.status_code == 202, "cadence minimale lancée depuis la gamme enregistrée")
        for _ in range(60):
            d2 = c.get(f"/v1/orgs/{org}/runs/{mc.json()['id']}", headers=A).json()
            if d2.get("status") in ("done", "failed"):
                break
            time.sleep(0.5)
        ok(d2.get("status") == "done" and d2.get("min_cycle_time"), f"cadence min = {d2.get('min_cycle_time')}")

        hist = c.get(f"/v1/orgs/{org}/runs", headers=A).json()
        ok(len(hist) == 2 and "result" not in hist[0], "historique : 2 calculs, sans résultat complet")
        ok(len(c.get(f"/v1/orgs/{org}/problems", headers=A).json()) == 1, "1 gamme enregistrée")
        exp = c.get(f"/v1/orgs/{org}/runs/{rid}/export.json", headers=A)
        ok(exp.status_code == 200 and "attachment" in exp.headers.get("content-disposition", ""), "export JSON")

        # Routes sans état accessibles avec le jeton utilisateur
        ok(c.post("/v1/precheck", json=PROBLEM, headers=A).status_code == 200, "precheck avec jeton")
        ok(c.post("/v1/precheck", json=PROBLEM).status_code == 401, "precheck sans jeton -> 401")

    # Nettoyage
    for org, tok in created:
        httpx.delete(f"{URL}/rest/v1/organizations?id=eq.{org}",
                     headers={"apikey": ANON, "Authorization": f"Bearer {tok}"}, timeout=20)
    print(f"\n{'TOUT EST VERT' if not ok.failed else str(ok.failed) + ' échec(s)'}")
    return 1 if ok.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
