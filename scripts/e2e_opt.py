"""Test de bout en bout de l'optimiseur (phase 2.3) contre l'API déployée.

Pré-requis : TLB_API_URL (défaut https://tlb-api.onrender.com), TLB_SUPABASE_URL, TLB_SUPABASE_ANON_KEY,
E2E_EMAIL, E2E_PASSWORD (compte de test créé puis supprimé par SQL par l'appelant).
Crée l'atelier « E2E OPT », un calcul (exemple chemise), lance une optimisation (budget 45 s) sans plan
d'atelier (variantes ligne / U), applique la solution au meilleur débit (simulation DES créée).
E2E_PLAN=1 : avec un plan d'atelier (échanges de postes sur machines du même type).
Affiche les identifiants pour le nettoyage et pour la QA navigateur.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
API = os.environ.get("TLB_API_URL", "https://tlb-api.onrender.com").rstrip("/")
URL = os.environ["TLB_SUPABASE_URL"].rstrip("/")
ANON = os.environ["TLB_SUPABASE_ANON_KEY"]
FAIL = 0


def ok(cond: bool, label: str) -> None:
    global FAIL
    print(("OK   " if cond else "ÉCHEC"), label)
    FAIL += 0 if cond else 1


def wait(c: httpx.Client, url: str, key: str = "status", timeout: float = 240) -> dict:
    t = time.time()
    while time.time() - t < timeout:
        d = c.get(url).json()
        if d.get(key) in ("done", "failed"):
            return d
        time.sleep(2)
    raise SystemExit(f"trop long : {url}")


def plan_body(stations: list[dict]) -> dict:
    """Deux rangées de machines face à face de part et d'autre d'une allée, + équipements de la bibliothèque."""
    n = len(stations)
    half = (n + 1) // 2
    W, L = max(16.0, 2.5 + half * 1.6 + 6), 14.0
    els = [
        {"kind": "wall", "id": "w1", "x1": 0, "y1": 0, "x2": W, "y2": 0, "thickness": 0.2},
        {"kind": "wall", "id": "w2", "x1": W, "y1": 0, "x2": W, "y2": L, "thickness": 0.2},
        {"kind": "wall", "id": "w3", "x1": W, "y1": L, "x2": 0, "y2": L, "thickness": 0.2},
        {"kind": "wall", "id": "w4", "x1": 0, "y1": L, "x2": 0, "y2": 0, "thickness": 0.2},
        {"kind": "door", "id": "d1", "x": W, "y": 7, "width": 1.4, "rot": 90, "exit": True},
        {"kind": "pillar", "id": "p1", "x": W / 2, "y": 9.3, "w": 0.4, "d": 0.4},
        {"kind": "aisle", "id": "a1", "x": 1, "y": 5.0, "w": W - 2, "h": 1.6, "main": True},
        {"kind": "zone", "id": "z1", "x": 0.5, "y": 0.5, "w": W - 1, "h": 9.5, "zone": "montage", "name": "Montage"},
        {"kind": "zone", "id": "z2", "x": 0.5, "y": 10.2, "w": W - 1, "h": 3.3, "zone": "finition", "name": "Finition"},
    ]
    k = 0
    for i, st in enumerate(stations):
        types = [t for t in (st.get("machine_types") or []) if t and t != "manuel"] or ["table_travail"]
        for t in types[:1]:
            row = 0 if i < half else 1
            j = i if row == 0 else n - 1 - i
            k += 1
            els.append({"kind": "machine", "id": f"m{k}", "type": t, "x": 2.0 + j * 1.6, "y": 3.6 if row == 0 else 7.9,
                        "w": 1.2, "d": 0.6, "rot": 0 if row == 0 else 180, "label": f"M{k:02d}", "operator": "front",
                        "status": "service"})
    extra = [("table_controle", 2.0, 11.5), ("table_repassage", 4.2, 11.5), ("mannequin_vapeur", 6.4, 11.5),
             ("detecteur_aiguilles", 8.8, 11.5), ("etiqueteuse_emballage", 11.2, 11.5), ("rack_encours", W - 2, 2.0),
             ("palette_carton", W - 2, 12.5), ("convoyeur_suspendu", 13.5, 11.5)]
    for t, x, y in extra:
        k += 1
        els.append({"kind": "machine", "id": f"m{k}", "type": t, "x": x, "y": y, "rot": 0, "label": f"M{k:02d}",
                    "operator": "front", "status": "service", "w": {"table_controle": 1.5, "table_repassage": 1.55,
                    "mannequin_vapeur": 1.2, "detecteur_aiguilles": 1.8, "etiqueteuse_emballage": 1.8, "rack_encours": 1.2,
                    "palette_carton": 1.2, "convoyeur_suspendu": 1.5}[t], "d": 0.8})
    if os.environ.get("E2E_CONVEYOR"):     # convoyeur suspendu dessiné au-dessus de l'allée et des deux rangées
        els.append({"kind": "rail", "id": "r1", "label": "UPS E2E", "height": 2.2, "radius": 0.5, "speed": 20,
                    "pts": [[1.2, 4.8], [W - 1.5, 4.8], [W - 1.5, 6.9], [1.2, 6.9]]})
    return {"name": "Atelier E2E DES", "width_m": W, "length_m": L, "elements": els}


def main() -> int:
    r = httpx.post(f"{URL}/auth/v1/token?grant_type=password", headers={"apikey": ANON},
                   json={"email": os.environ["E2E_EMAIL"], "password": os.environ["E2E_PASSWORD"]}, timeout=30)
    r.raise_for_status()
    tok = r.json()["access_token"]
    c = httpx.Client(base_url=API, headers={"Authorization": f"Bearer {tok}"}, timeout=120)
    print("     API", c.get("/health").json())
    org = c.post("/v1/orgs", json={"name": "E2E OPT"}).json()["id"]
    print("     atelier :", org)
    m = ROOT / "web" / "public" / "modeles"
    files = {"sam": open(m / "exemple_chemise_SAM.csv", "rb"), "workstations": open(m / "exemple_chemise_postes.csv", "rb"),
             "workers": open(m / "exemple_chemise_ouvriers.csv", "rb")}
    imp = c.post("/v1/import/problem", files=files, data={"target_cycle_time": "1.2", "name": "Chemise E2E"})
    ok(imp.status_code == 200, f"import exemple chemise ({imp.status_code})")
    run = c.post(f"/v1/orgs/{org}/runs", json={"problem": imp.json()["problem"], "solver": "rpw", "save_problem": True}).json()
    run = wait(c, f"/v1/orgs/{org}/runs/{run['id']}")
    ok(run["status"] == "done", f"calcul {run['id']} ({run.get('stations_used')} stations)")
    plan_id = None
    if os.environ.get("E2E_PLAN"):
        twin = c.get(f"/v1/orgs/{org}/runs/{run['id']}/twin").json()
        plan_id = c.post(f"/v1/orgs/{org}/workshop-plans", json=plan_body(twin["plan"]["stations"])).json()["id"]
        c.put(f"/v1/orgs/{org}/runs/{run['id']}/layout", json={"plan_id": plan_id, "assignment": {}})
    cfg = {"time_budget_s": float(os.environ.get("E2E_BUDGET", "45")), "replications": 2, "cost_per_minute": 0.06,
           "max_extra_operators": 2, "max_fewer_operators": 2}
    t0 = time.time()
    o = c.post(f"/v1/orgs/{org}/runs/{run['id']}/optimize", json={"name": "E2E optimisation", "plan_id": plan_id, "config": cfg})
    ok(o.status_code == 202, f"optimisation lancée ({o.status_code})")
    sid = o.json()["id"]
    seen = 0
    while time.time() - t0 < 300:
        s = c.get(f"/v1/orgs/{org}/simulations/{sid}").json()
        if (s.get("results") or {}).get("progress", {}).get("pct", 0) not in (0, 100):
            seen += 1
        if s["status"] in ("done", "failed"):
            break
        time.sleep(2)
    ok(s["status"] == "done", f"optimisation terminée en {time.time() - t0:.0f} s {s.get('error') or ''}")
    ok(seen > 0, "progression visible pendant la recherche")
    res = s["results"]
    b = res["base"]["mean"]
    print(f"     {res['evals']} configurations, {res['simulations']} journées simulées, {res['elapsed_s']} s, arrêt : {res['stopped_by']}")
    print(f"     variantes : {res['variants']}")
    print(f"     actuel : {b['pieces']} pcs/j, coût minute {b['cost_minute']}, encours {b['wip_avg']}, marche {b['walk_m']} m, {b['people']} pers.")
    for sol in res["pareto"][:8]:
        mm = sol["mean"]
        print(f"     #{sol['id']} {mm['pieces']} pcs/j, coût minute {mm['cost_minute']}, encours {mm['wip_avg']}, marche {mm['walk_m']} m, "
              f"{mm['people']} pers. : {' · '.join(sol['changes'])}")
    ok(len(res["pareto"]) >= 2, f"front de Pareto ({len(res['pareto'])} solutions)")
    best = res["pareto"][0]
    a = c.post(f"/v1/orgs/{org}/optimizations/{sid}/apply", json={"solution": best["id"], "replications": 3})
    ok(a.status_code == 202, f"appliquer la solution {best['id']} ({a.status_code})")
    d = wait(c, f"/v1/orgs/{org}/simulations/{a.json()['simulation']['id']}")
    ok(d["status"] == "done", f"simulation de la solution {d['id']} {d.get('error') or ''}")
    k = d["results"]["scenarios"][0]["result"]["kpis"]
    print(f"     simulation de la solution (3 réplications) : {k['pieces']} pcs, encours {k['wip_avg']}, goulot {k['bottleneck']}")
    print(f"     QA : /optimiseur/{run['id']}?opt={sid}  puis /simulation/{run['id']}?sim={d['id']}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
