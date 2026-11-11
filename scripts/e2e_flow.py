"""Test de bout en bout de la logique par blocs (Process Flow) contre l'API déployée.

Pré-requis : comme scripts/e2e_des.py (TLB_SUPABASE_URL, TLB_SUPABASE_ANON_KEY, E2E_EMAIL, E2E_PASSWORD :
compte de test créé puis supprimé par SQL par l'appelant). Crée l'atelier « E2E FLOW », un calcul
(exemple chemise), génère le graphe depuis la gamme, le valide, l'enregistre (RLS), ajoute un contrôle avec
retouche, l'exécute (tâche de fond) et vérifie la conservation des pièces.
"""
from __future__ import annotations

import os
import sys

import httpx

from scripts.e2e_des import API, ANON, ROOT, URL, ok, wait
import scripts.e2e_des as E


def main() -> int:
    r = httpx.post(f"{URL}/auth/v1/token?grant_type=password", headers={"apikey": ANON},
                   json={"email": os.environ["E2E_EMAIL"], "password": os.environ["E2E_PASSWORD"]}, timeout=30)
    r.raise_for_status()
    c = httpx.Client(base_url=API, headers={"Authorization": f"Bearer {r.json()['access_token']}"}, timeout=120)
    org = c.post("/v1/orgs", json={"name": "E2E FLOW"}).json()["id"]
    m = ROOT / "web" / "public" / "modeles"
    files = {"sam": open(m / "exemple_chemise_SAM.csv", "rb"), "workstations": open(m / "exemple_chemise_postes.csv", "rb"),
             "workers": open(m / "exemple_chemise_ouvriers.csv", "rb")}
    imp = c.post("/v1/import/problem", files=files, data={"target_cycle_time": "1.2", "name": "Chemise E2E"})
    run = c.post(f"/v1/orgs/{org}/runs", json={"problem": imp.json()["problem"], "solver": "rpw", "save_problem": True}).json()
    run = wait(c, f"/v1/orgs/{org}/runs/{run['id']}")
    ok(run["status"] == "done", f"calcul {run['id']}")
    auto = c.get(f"/v1/orgs/{org}/runs/{run['id']}/flow/auto").json()
    g = auto["graph"]
    types = [b["type"] for b in g["blocks"]]
    print("     graphe :", {t: types.count(t) for t in set(types)}, g.get("generated"))
    ok(auto["validation"]["ok"], "graphe généré valide")
    ok(types.count("operation") == run["stations_used"], "un bloc opération par station")
    # contrôle + retouche avant la sortie
    sink = next(b for b in g["blocks"] if b["type"] == "sink")
    last = next(e for e in g["edges"] if e["to"] == sink["id"])
    g["blocks"] += [{"id": "ctl", "type": "inspect", "label": "Contrôle final", "params": {"minutes": 0.3, "defect_pct": 4}},
                    {"id": "ret", "type": "operation", "label": "Retouche", "params": {"minutes": 1.5}}]
    last["to"] = "ctl"
    g["edges"] += [{"from": "ctl", "port": 0, "to": sink["id"]}, {"from": "ctl", "port": 1, "to": "ret"}, {"from": "ret", "port": 0, "to": "ctl"}]
    v = c.post(f"/v1/orgs/{org}/flows/validate", json={"graph": g}).json()
    ok(v["ok"] and v["warnings"], f"validation : boucle de retouche signalée ({len(v['warnings'])} avertissement)")
    bad = {**g, "edges": [e for e in g["edges"] if e["from"] != "ret"]}
    vb = c.post(f"/v1/orgs/{org}/flows/validate", json={"graph": bad}).json()
    ok(not vb["ok"], f"validation : sortie non reliée détectée ({vb['errors'][0]['msg'][:60]})")
    f = c.post(f"/v1/orgs/{org}/flows", json={"name": "Chemise + contrôle", "graph": g, "run_id": run["id"]})
    ok(f.status_code == 201, f"graphe enregistré ({f.status_code})")
    fid = f.json()["id"]
    ok(c.patch(f"/v1/orgs/{org}/flows/{fid}", json={"name": "Chemise + contrôle v2"}).json()["name"].endswith("v2"), "renommage")
    ok(len(c.get(f"/v1/orgs/{org}/flows", params={"run_id": run["id"]}).json()) == 1, "liste des graphes du calcul")
    s = c.post(f"/v1/orgs/{org}/runs/{run['id']}/flow/simulate", json={"graph": g, "replications": 3, "flow_id": fid})
    ok(s.status_code == 202, f"exécution lancée ({s.status_code})")
    s = wait(c, f"/v1/orgs/{org}/simulations/{s.json()['id']}")
    ok(s["status"] == "done", f"exécution terminée {s.get('error', '')}")
    res = s["results"]["result"]
    k = res["kpis"]
    print(f"     {k['pieces']} pcs ({k['per_hour']}/h), traversée {k['lead_time_avg']} min, encours {k['wip_avg']}, goulot {k['bottleneck']}")
    ok(res["conservation"]["ok"], f"conservation {res['conservation']}")
    ok(next(b for b in res["blocks"] if b["id"] == "ctl").get("defects", 0) > 0, "retouches au contrôle")
    ok(any(e[1] == 0 for e in res["trace"]["events"]), "postes du plan animés par les blocs")
    print(f"     QA : /flux/{run['id']}?flux={fid}&sim={s['id']}")
    return 1 if E.FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
