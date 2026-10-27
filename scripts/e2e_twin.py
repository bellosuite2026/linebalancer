"""Test de bout en bout du jumeau numérique contre le vrai Supabase (RLS, implantations, simulations).

Pré-requis : TLB_SUPABASE_URL, TLB_SUPABASE_ANON_KEY,
  E2E_EMAIL_A (propriétaire de E2E_ORG), E2E_EMAIL_B (autre atelier), E2E_EMAIL_C (lecteur dans E2E_ORG),
  E2E_PASSWORD, E2E_ORG. Comptes et atelier créés puis supprimés par l'appelant (SQL).
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timezone
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
ORG = os.environ["E2E_ORG"]
PROBLEM = {"name": "e2e-jumeau", "target_cycle_time": 1.0, "operations": [
    {"id": "A", "name": "Épaules", "duration": 0.6, "required_skills": ["surjet"]},
    {"id": "B", "name": "Col", "duration": 0.5, "predecessors": ["A"], "required_skills": ["piqure"]},
    {"id": "C", "name": "Manches", "duration": 0.7, "predecessors": ["B"], "required_skills": ["piqure"]},
    {"id": "D", "name": "Ourlet", "duration": 0.4, "predecessors": ["C"], "required_skills": ["piqure"]}],
    "workers": [{"id": f"W{i}", "name": n, "skills": s} for i, (n, s) in enumerate(
        [("Amira", ["surjet", "piqure"]), ("Sami", ["piqure"]), ("Hana", ["piqure"]), ("Rim", ["piqure"])], 1)]}


def login(email: str) -> str:
    r = httpx.post(f"{URL}/auth/v1/token?grant_type=password", headers={"apikey": ANON},
                   json={"email": email, "password": PWD}, timeout=20)
    r.raise_for_status()
    return r.json()["access_token"]


def rest(tok: str, prefer: str = "") -> dict:
    h = {"apikey": ANON, "Authorization": f"Bearer {tok}"}
    if prefer:
        h["Prefer"] = prefer
    return h


def ok(cond: bool, label: str) -> None:
    print(("OK   " if cond else "ÉCHEC"), label)
    if not cond:
        ok.failed += 1  # type: ignore[attr-defined]


ok.failed = 0  # type: ignore[attr-defined]


def main() -> int:
    s = Settings.from_env()
    s.api_keys = set()
    app = create_app(s)
    with TestClient(app) as c:
        ta, tb, tc = (login(os.environ[k]) for k in ("E2E_EMAIL_A", "E2E_EMAIL_B", "E2E_EMAIL_C"))
        A, B, C = ({"Authorization": f"Bearer {t}"} for t in (ta, tb, tc))
        run = c.post(f"/v1/orgs/{ORG}/runs", headers=A, json={"kind": "balance", "solver": "rpw", "problem": PROBLEM,
                                                                "save_problem": True})
        ok(run.status_code == 202, f"calcul lancé ({run.status_code} {run.text[:100]})")
        rid = run.json()["id"]
        for _ in range(60):
            if c.get(f"/v1/orgs/{ORG}/runs/{rid}", headers=A).json().get("status") in ("done", "failed"):
                break
            time.sleep(0.5)
        r = c.get(f"/v1/orgs/{ORG}/runs/{rid}/twin", headers=A)
        ok(r.status_code == 200, f"jumeau lisible ({r.status_code} {r.text[:120]})")
        tw = r.json()
        n = len(tw["plan"]["stations"])
        ok(n >= 2 and tw["layout"]["kind"] == "line", f"plan : {n} stations, implantation en ligne par défaut")
        ok(c.get(f"/v1/orgs/{ORG}/runs/{rid}/twin", headers=C).status_code == 200, "lecteur : jumeau lisible")
        ok(c.get(f"/v1/orgs/{ORG}/runs/{rid}/twin", headers=B).status_code == 404, "B : jumeau invisible")

        pos = {str(st["station"]): {"x": i * 1.2, "y": 0.5} for i, st in enumerate(tw["plan"]["stations"])}
        r = c.put(f"/v1/orgs/{ORG}/runs/{rid}/layout", headers=A, json={"kind": "free", "positions": pos})
        ok(r.status_code == 200 and r.json()["kind"] == "free", f"implantation enregistrée ({r.status_code} {r.text[:120]})")
        r = c.put(f"/v1/orgs/{ORG}/runs/{rid}/layout", headers=A, json={"kind": "u", "positions": pos})
        ok(r.status_code == 200 and r.json()["kind"] == "u", "implantation mise à jour (pas de doublon)")
        ok(c.put(f"/v1/orgs/{ORG}/runs/{rid}/layout", headers=C, json={"kind": "line"}).status_code == 403,
           "lecteur : implantation non modifiable (API)")
        raw = httpx.get(f"{URL}/rest/v1/line_layouts?run_id=eq.{rid}", headers=rest(tb), timeout=20)
        ok(raw.status_code == 200 and raw.json() == [], "B : lecture directe des implantations vide (RLS)")
        raw = httpx.patch(f"{URL}/rest/v1/line_layouts?run_id=eq.{rid}", headers=rest(tc, "return=representation"),
                          json={"kind": "line"}, timeout=20)
        ok(raw.status_code in (401, 403) or raw.json() == [], f"lecteur : écriture directe refusée ({raw.status_code})")
        raw = httpx.patch(f"{URL}/rest/v1/line_layouts?run_id=eq.{rid}", headers=rest(ta, "return=representation"),
                          json={"org_id": "00000000-0000-0000-0000-000000000000"}, timeout=20)
        ok(raw.status_code in (401, 403), f"org_id d'une implantation non modifiable ({raw.status_code})")
        raw = httpx.post(f"{URL}/rest/v1/line_layouts", headers=rest(tb, "return=representation"), timeout=20,
                         json={"org_id": ORG, "run_id": rid, "kind": "line"})
        ok(raw.status_code in (401, 403, 409), f"B : insertion directe refusée ({raw.status_code})")

        bn = tw["plan"]["bottleneck_station"]
        absent = next(st["worker_ids"][0] for st in tw["plan"]["stations"] if st["station"] == bn and st["worker_ids"]) \
            if any(st["worker_ids"] for st in tw["plan"]["stations"] if st["station"] == bn) else "W3"
        body = {"scenarios": [{"name": "Référence"}, {"name": "Absence", "absent": [absent]},
                              {"name": "Panne", "breakdowns": [{"station": bn, "start_min": 60, "duration_min": 45}]}]}
        ok(c.post(f"/v1/orgs/{ORG}/runs/{rid}/simulate", headers=C, json=body).status_code == 403,
           "lecteur : simulation refusée")
        r = c.post(f"/v1/orgs/{ORG}/runs/{rid}/simulate", headers=A, json=body)
        ok(r.status_code == 202, f"simulation lancée ({r.status_code} {r.text[:120]})")
        sid = r.json()["id"]
        sim = {}
        for _ in range(60):
            sim = c.get(f"/v1/orgs/{ORG}/simulations/{sid}", headers=A).json()
            if sim.get("status") in ("done", "failed"):
                break
            time.sleep(0.5)
        ok(sim.get("status") == "done", f"simulation terminée ({sim.get('status')} {sim.get('error', '')[:120]})")
        comp = {row["key"]: row["values"] for row in (sim.get("results") or {}).get("comparison", [])}
        print("     pièces/jour :", comp.get("pieces"), "goulot :", comp.get("bottleneck"))
        ok(bool(comp) and comp["pieces"][0] >= comp["pieces"][2], "comparaison : la panne coûte des pièces")
        ok(c.get(f"/v1/orgs/{ORG}/simulations/{sid}", headers=B).status_code == 404, "B : simulation invisible")
        raw = httpx.get(f"{URL}/rest/v1/twin_simulations?id=eq.{sid}", headers=rest(tb), timeout=20)
        ok(raw.status_code == 200 and raw.json() == [], "B : lecture directe des simulations vide (RLS)")
        raw = httpx.get(f"{URL}/rest/v1/twin_simulations?id=eq.{sid}", headers={"apikey": ANON}, timeout=20)
        ok(raw.status_code in (401, 403) or raw.json() == [], f"anonyme : rien ({raw.status_code})")
        x = c.get(f"/v1/orgs/{ORG}/simulations/{sid}/export.xlsx", headers=C)
        p = c.get(f"/v1/orgs/{ORG}/simulations/{sid}/export.pdf", headers=A)
        ok(x.status_code == 200 and x.content[:2] == b"PK" and p.content[:4] == b"%PDF", "exports Excel + PDF")

        r = c.post(f"/v1/orgs/{ORG}/production/sessions", headers=A,
                   json={"run_id": rid, "model": "Jumeau E2E", "shift_start": "00:00", "shift_hours": 10})
        ok(r.status_code == 201, f"session de production ({r.status_code})")
        ps = r.json()["id"]
        hour = datetime.now(timezone.utc).astimezone().hour
        last = tw["plan"]["stations"][-1]["station"]
        c.post(f"/v1/orgs/{ORG}/production/sessions/{ps}/entries", headers=A, json={"entries": [
            {"station": tw["plan"]["stations"][0]["station"], "pieces": 40},
            {"station": last, "pieces": 30}]})
        r = c.get(f"/v1/orgs/{ORG}/runs/{rid}/twin/sync", headers=C, params={"session_id": ps, "order_qty": 3000})
        ok(r.status_code == 200, f"réel vs simulé ({r.status_code} {r.text[:160]})")
        sy = r.json()
        ok(sy.get("output") == 30 and sy.get("forecast_end_of_day", 0) >= 30 and "order" in sy,
           f"prévision fin de journée {sy.get('forecast_end_of_day')} pcs, commande finie le {sy.get('order', {}).get('finish_date')}")
        ok(c.get(f"/v1/orgs/{ORG}/runs/{rid}/twin/sync", headers=B, params={"session_id": ps}).status_code == 404,
           "B : synchronisation refusée")
        tw2 = c.get(f"/v1/orgs/{ORG}/runs/{rid}/twin", headers=A).json()
        ok(tw2["layout_saved"] and len(tw2["simulations"]) == 1 and len(tw2["sessions"]) == 1,
           "jumeau : implantation, simulation et session rattachées")
        _ = hour
    print("Échecs :", ok.failed)  # type: ignore[attr-defined]
    return 1 if ok.failed else 0  # type: ignore[attr-defined]


if __name__ == "__main__":
    sys.exit(main())
