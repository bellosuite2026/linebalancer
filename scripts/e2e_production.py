"""Test de bout en bout du suivi de production contre le vrai Supabase (RLS, sessions, saisies).

Pré-requis : TLB_SUPABASE_URL, TLB_SUPABASE_ANON_KEY,
  E2E_EMAIL_A (propriétaire), E2E_EMAIL_B (autre atelier), E2E_EMAIL_C (lecteur dans l'atelier de A),
  E2E_EMAIL_D (chef de ligne dans l'atelier de A), E2E_PASSWORD, E2E_ORG (atelier de A, essai actif).
Les comptes et l'atelier sont créés et supprimés par l'appelant (SQL), voir notes/decisions.md.
"""
from __future__ import annotations

import os
import sys
import time
import uuid
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
PROBLEM = {"name": "e2e-polo", "target_cycle_time": 1.0, "operations": [
    {"id": "A", "name": "Épaules", "duration": 0.6}, {"id": "B", "name": "Col", "duration": 0.5, "predecessors": ["A"]},
    {"id": "C", "name": "Manches", "duration": 0.7, "predecessors": ["A"]},
    {"id": "D", "name": "Ourlet", "duration": 0.4, "predecessors": ["B", "C"]}]}


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
        ta, tb, tc, td = (login(os.environ[k]) for k in ("E2E_EMAIL_A", "E2E_EMAIL_B", "E2E_EMAIL_C", "E2E_EMAIL_D"))
        A, B, C, D = ({"Authorization": f"Bearer {t}"} for t in (ta, tb, tc, td))
        base = f"/v1/orgs/{ORG}/production/sessions"

        run = c.post(f"/v1/orgs/{ORG}/runs", headers=A, json={"kind": "balance", "solver": "rpw", "problem": PROBLEM})
        ok(run.status_code == 202, f"calcul lancé ({run.status_code} {run.text[:100]})")
        rid = run.json()["id"]
        for _ in range(60):
            if c.get(f"/v1/orgs/{ORG}/runs/{rid}", headers=A).json().get("status") in ("done", "failed"):
                break
            time.sleep(0.5)

        r = c.post(base, headers=A, json={"run_id": rid, "model": "Polo E2E", "shift_start": "00:00", "shift_hours": 24})
        ok(r.status_code == 201, f"session ouverte ({r.status_code} {r.text[:160]})")
        sess = r.json()
        sid = sess["id"]
        ok(len(sess["plan"]["stations"]) >= 2 and sess["target_per_hour"] > 0,
           f"plan figé : {len(sess['plan']['stations'])} stations, objectif {sess['target_per_hour']} pcs/h")
        n = len(sess["plan"]["stations"])

        # Isolation
        ok(c.get(f"{base}/{sid}", headers=B).status_code == 404, "B (autre atelier) ne voit pas la session")
        raw = httpx.get(f"{URL}/rest/v1/production_sessions?id=eq.{sid}", headers=rest(tb), timeout=20)
        ok(raw.status_code == 200 and raw.json() == [], "B : lecture directe PostgREST vide (RLS)")
        raw = httpx.post(f"{URL}/rest/v1/rpc/production_upsert_entries", headers=rest(tb), timeout=20,
                         json={"p_session": sid, "p_entries": [{"station": 1, "pieces": 5, "slot_hour": 8}]})
        ok(raw.status_code in (401, 403) or raw.json() == [], f"B : écriture directe refusée ({raw.status_code})")
        raw = httpx.post(f"{URL}/rest/v1/production_entries", headers=rest(tb), timeout=20,
                         json={"session_id": sid, "org_id": ORG, "station": 1, "pieces": 5, "slot_hour": 8})
        ok(raw.status_code in (401, 403), f"B : insertion directe refusée ({raw.status_code})")
        raw = httpx.get(f"{URL}/rest/v1/production_sessions?id=eq.{sid}", headers={"apikey": ANON}, timeout=20)
        ok(raw.status_code in (401, 403) or raw.json() == [], f"anonyme : rien ({raw.status_code})")

        # Saisies
        cid = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        r = c.post(f"{base}/{sid}/entries", headers=D, json={"entries": [
            {"client_id": cid, "station": 1, "pieces": 10},
            {"station": n, "pieces": 6, "defects": 1},
            {"station": 2, "downtime_reason": "panne", "downtime_start": now}]})
        ok(r.status_code == 200 and r.json()["saved"] == 3, f"chef de ligne : 3 saisies ({r.status_code} {r.text[:120]})")
        ok(all(e["entered_by"] for e in r.json()["entries"]), "saisi_par renseigné par la base")
        r = c.post(f"{base}/{sid}/entries", headers=D, json={"entries": [{"client_id": cid, "station": 1, "pieces": 12}]})
        ents = c.get(f"{base}/{sid}/entries", headers=A).json()
        ok(len(ents) == 3 and next(e for e in ents if e["client_id"] == cid)["pieces"] == 12,
           "renvoi du même client_id = mise à jour (pas de doublon)")
        raw = httpx.post(f"{URL}/rest/v1/rpc/production_upsert_entries", headers=rest(tc), timeout=20,
                         json={"p_session": sid, "p_entries": [{"station": 1, "pieces": 5, "slot_hour": 8}]})
        ok(raw.status_code in (401, 403), f"lecteur : écriture directe refusée ({raw.status_code})")
        ok(c.post(f"{base}/{sid}/entries", headers=C, json={"entries": [{"station": 1, "pieces": 1}]}).status_code == 403,
           "lecteur : saisie refusée par l'API")
        ok(c.get(f"{base}/{sid}/dashboard", headers=C).status_code == 200, "lecteur : tableau de bord lisible")
        raw = httpx.patch(f"{URL}/rest/v1/production_entries?client_id=eq.{cid}", headers=rest(td, "return=representation"),
                          json={"org_id": str(uuid.uuid4())}, timeout=20)
        ok(raw.status_code in (401, 403), f"org_id d'une saisie non modifiable ({raw.status_code})")

        d = c.get(f"{base}/{sid}/dashboard", headers=A).json()
        ok(d["stations"][0]["pieces"] == 12 and d["output"] == 6, f"tableau de bord : S1=12, sortie={d['output']}")
        ok(d["stations"][1]["ongoing_stop"] is not None, "arrêt en cours visible")
        ok(d["bottleneck_planned"] is not None, f"goulot calculé S{d['bottleneck_planned']}, observé S{d['bottleneck_observed']}")
        x = c.get(f"{base}/{sid}/export.xlsx", headers=A)
        ok(x.status_code == 200 and x.content[:2] == b"PK", "export Excel")
        p = c.get(f"{base}/{sid}/export.pdf", headers=A)
        ok(p.status_code == 200 and p.content[:4] == b"%PDF", "export PDF")
        ok(c.get(f"{base}/{sid}/export.pdf", headers=B).status_code == 404, "B : export refusé")

        # Fermeture
        r = c.patch(f"{base}/{sid}", headers=D, json={"status": "closed"})
        ok(r.status_code == 200 and r.json()["closed_at"], "session fermée (horodatée)")
        raw = httpx.post(f"{URL}/rest/v1/rpc/production_upsert_entries", headers=rest(td), timeout=20,
                         json={"p_session": sid, "p_entries": [{"station": 1, "pieces": 5, "slot_hour": 8}]})
        ok(raw.status_code >= 400 and "fermée" in raw.text, f"saisie directe refusée après fermeture ({raw.status_code})")
        ok(c.get(base, headers=A).json()[0]["status"] == "closed", "liste des sessions")
        print("SESSION", sid)
    print(f"\n{'TOUT EST VERT' if not ok.failed else str(ok.failed) + ' échec(s)'}")
    return 1 if ok.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
