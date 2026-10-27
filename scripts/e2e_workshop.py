"""Test de bout en bout du plan d'atelier contre le vrai Supabase (RLS, stockage du fond, placement, simulation).

Pré-requis : TLB_SUPABASE_URL, TLB_SUPABASE_ANON_KEY, E2E_EMAIL_A, E2E_EMAIL_B, E2E_PASSWORD.
Les deux comptes sont créés puis supprimés par l'appelant (SQL) ; le script crée un atelier par compte
(E2E Plan A / E2E Plan B) et affiche leurs identifiants pour le nettoyage.
"""
from __future__ import annotations

import base64
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
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
TYPES = ["piqueuse_plate", "surjeteuse_4_fils"]
PROBLEM = {"name": "e2e-plan", "target_cycle_time": 0.8, "operations": [
    {"id": f"OP{i + 1:02d}", "name": f"Opération {i + 1}", "duration": 0.7, "machine_type": TYPES[i % 2],
     "predecessors": [f"OP{i:02d}"] if i else []} for i in range(8)]}


def login(email: str) -> str:
    r = httpx.post(f"{URL}/auth/v1/token?grant_type=password", headers={"apikey": ANON},
                   json={"email": email, "password": PWD}, timeout=20)
    r.raise_for_status()
    return r.json()["access_token"]


def h(tok: str, **extra) -> dict:
    return {"apikey": ANON, "Authorization": f"Bearer {tok}", **extra}


def ok(cond: bool, label: str) -> None:
    print(("OK   " if cond else "ÉCHEC"), label)
    if not cond:
        ok.failed += 1  # type: ignore[attr-defined]


ok.failed = 0  # type: ignore[attr-defined]


def plan_body(org: str) -> dict:
    els = [{"kind": "wall", "id": "w1", "x1": 0, "y1": 0, "x2": 14, "y2": 0, "thickness": 0.2},
           {"kind": "door", "id": "d1", "x": 13, "y": 8, "width": 1.2, "rot": 90, "exit": True},
           {"kind": "aisle", "id": "a1", "x": 0.5, "y": 4.2, "w": 13, "h": 1.4, "main": True}]
    for i in range(8):
        els.append({"kind": "machine", "id": f"m{i}", "type": TYPES[i % 2], "x": 1.5 + (i if i < 4 else 7 - i) * 1.6,
                    "y": 2.5 if i < 4 else 6.5, "w": 1.2, "d": 0.6, "rot": 0 if i < 4 else 180,
                    "label": f"M{i + 1:02d}", "operator": "front", "status": "service"})
    return {"name": "Atelier E2E", "width_m": 14, "length_m": 9, "elements": els,
            "background": {"path": f"{org}/e2e.png", "x": 0, "y": 0, "width_m": 14, "height_m": 9, "opacity": 0.5}}


def main() -> int:
    s = Settings.from_env()
    s.api_keys = set()
    with TestClient(create_app(s)) as c:
        ta, tb = login(os.environ["E2E_EMAIL_A"]), login(os.environ["E2E_EMAIL_B"])
        A, B = {"Authorization": f"Bearer {ta}"}, {"Authorization": f"Bearer {tb}"}
        org = c.post("/v1/orgs", headers=A, json={"name": "E2E Plan A"}).json()["id"]
        orgb = c.post("/v1/orgs", headers=B, json={"name": "E2E Plan B"}).json()["id"]
        print("     ateliers :", org, orgb)

        st = f"{URL}/storage/v1/object/workshop-plans"
        r = httpx.post(f"{st}/{org}/e2e.png", headers=h(ta, **{"Content-Type": "image/png"}), content=PNG, timeout=20)
        ok(r.status_code == 200, f"A : fond déposé dans son dossier ({r.status_code} {r.text[:80]})")
        r = httpx.post(f"{st}/{org}/intrus.png", headers=h(tb, **{"Content-Type": "image/png"}), content=PNG, timeout=20)
        ok(r.status_code >= 400, f"B : dépôt dans le dossier de A refusé ({r.status_code})")
        r = httpx.post(f"{st}/{org}/x.txt", headers=h(ta, **{"Content-Type": "text/plain"}), content=b"x", timeout=20)
        ok(r.status_code >= 400, f"type de fichier non image refusé ({r.status_code})")
        sv = f"{URL}/storage/v1/object"
        ok(httpx.get(f"{sv}/authenticated/workshop-plans/{org}/e2e.png", headers=h(ta), timeout=20).status_code == 200, "A : fond lisible")
        ok(httpx.get(f"{sv}/authenticated/workshop-plans/{org}/e2e.png", headers=h(tb), timeout=20).status_code >= 400, "B : fond de A illisible")
        ok(httpx.get(f"{sv}/public/workshop-plans/{org}/e2e.png", timeout=20).status_code >= 400, "anonyme : bucket non public")

        r = c.post(f"/v1/orgs/{org}/workshop-plans", headers=A, json=plan_body(org))
        ok(r.status_code == 201 and r.json().get("machine_count") == 8, f"plan créé, 8 machines ({r.status_code} {r.text[:100]})")
        pid = r.json()["id"]
        ok(c.get(f"/v1/orgs/{org}/workshop-plans/{pid}", headers=B).status_code == 404, "B : plan invisible (API)")
        raw = httpx.get(f"{URL}/rest/v1/workshop_plans?id=eq.{pid}", headers=h(tb), timeout=20)
        ok(raw.status_code == 200 and raw.json() == [], "B : lecture directe vide (RLS)")
        raw = httpx.post(f"{URL}/rest/v1/workshop_plans", headers=h(tb, Prefer="return=representation"), timeout=20,
                         json={"org_id": org, "name": "intrus"})
        ok(raw.status_code in (401, 403), f"B : insertion dans l'atelier A refusée ({raw.status_code})")
        raw = httpx.patch(f"{URL}/rest/v1/workshop_plans?id=eq.{pid}", headers=h(ta, Prefer="return=representation"),
                          json={"org_id": orgb}, timeout=20)
        ok(raw.status_code in (401, 403), f"atelier d'un plan non modifiable ({raw.status_code})")
        raw = httpx.patch(f"{URL}/rest/v1/workshop_plans?id=eq.{pid}", headers=h(ta, Prefer="return=representation"),
                          json={"background": {"path": f"{orgb}/x.png"}}, timeout=20)
        ok(raw.status_code >= 400, f"fond hors du dossier de l'atelier refusé (trigger, {raw.status_code})")
        bad = plan_body(org) | {"background": {"path": f"{orgb}/x.png"}}
        ok(c.post(f"/v1/orgs/{org}/workshop-plans", headers=A, json=bad).status_code == 422, "API : fond d'un autre atelier refusé")
        inv = c.get(f"/v1/orgs/{org}/workshop-plans/{pid}/inventory", headers=A).json()
        ok(len(inv.get("workstations", [])) == 8, f"inventaire : 8 postes, déplacement {inv.get('travel')}")

        run = c.post(f"/v1/orgs/{org}/runs", headers=A, json={"kind": "balance", "solver": "rpw", "problem": PROBLEM,
                                                               "save_problem": True}).json()
        for _ in range(60):
            if c.get(f"/v1/orgs/{org}/runs/{run['id']}", headers=A).json().get("status") in ("done", "failed"):
                break
            time.sleep(0.5)
        rid = run["id"]
        r = c.post(f"/v1/orgs/{org}/runs/{rid}/twin/plan", headers=A, json={"plan_id": pid})
        ok(r.status_code == 200, f"placement sur le plan ({r.status_code} {r.text[:100]})")
        pl = r.json()
        used = sum(len(v) for v in pl.get("assignment", {}).values())
        ok(used == 8 and not pl.get("missing") and pl.get("flow", {}).get("u_cell"),
           f"8 stations sur 8 machines, cellule en U détectée ("
                                                 f"{pl.get('flow', {}).get('meters_per_bundle')} m/paquet)")
        ok(c.post(f"/v1/orgs/{org}/runs/{rid}/twin/plan", headers=B, json={"plan_id": pid}).status_code == 404,
           "B : placement refusé")
        r = c.put(f"/v1/orgs/{org}/runs/{rid}/layout", headers=A, json={"plan_id": pid, "assignment": pl["assignment"]})
        ok(r.status_code == 200 and r.json().get("plan_id") == pid, f"implantation liée au plan ({r.status_code})")
        r = c.post(f"/v1/orgs/{org}/runs/{rid}/simulate", headers=A, json={"scenarios": [{"name": "Sur le plan"}]})
        sid = r.json()["id"]
        sim = {}
        for _ in range(60):
            sim = c.get(f"/v1/orgs/{org}/simulations/{sid}", headers=A).json()
            if sim.get("status") in ("done", "failed"):
                break
            time.sleep(0.5)
        res = ((sim.get("results") or {}).get("scenarios") or [{}])[0].get("result", {})
        ok(sim.get("status") == "done" and res.get("pieces", 0) > 0,
           f"simulation sur le plan : {res.get('pieces')} pièces, {res.get('transport_m')} m de transport")
        ok(c.delete(f"/v1/orgs/{org}/workshop-plans/{pid}", headers=A).status_code == 204, "plan supprimé")
        lay = httpx.get(f"{URL}/rest/v1/line_layouts?run_id=eq.{rid}&select=plan_id", headers=h(ta), timeout=20).json()
        ok(lay and lay[0]["plan_id"] is None, "implantation conservée, lien vers le plan remis à vide")
        httpx.delete(f"{st}/{org}/e2e.png", headers=h(ta), timeout=20)
    print("Échecs :", ok.failed)  # type: ignore[attr-defined]
    return 1 if ok.failed else 0  # type: ignore[attr-defined]


if __name__ == "__main__":
    sys.exit(main())
