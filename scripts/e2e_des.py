"""Test de bout en bout de la simulation à événements discrets contre l'API déployée.

Pré-requis : TLB_API_URL (défaut https://tlb-api.onrender.com), TLB_SUPABASE_URL, TLB_SUPABASE_ANON_KEY,
E2E_EMAIL, E2E_PASSWORD (compte de test créé puis supprimé par SQL par l'appelant).
Crée l'atelier « E2E DES », un calcul (exemple chemise), un plan d'atelier avec des machines de la
bibliothèque, l'implantation sur le plan, puis lance une simulation (2 scénarios × 3 réplications).
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
    org = c.post("/v1/orgs", json={"name": "E2E DES"}).json()["id"]
    print("     atelier :", org)
    m = ROOT / "web" / "public" / "modeles"
    files = {"sam": open(m / "exemple_chemise_SAM.csv", "rb"), "workstations": open(m / "exemple_chemise_postes.csv", "rb"),
             "workers": open(m / "exemple_chemise_ouvriers.csv", "rb")}
    imp = c.post("/v1/import/problem", files=files, data={"target_cycle_time": "1.2", "name": "Chemise E2E"})
    ok(imp.status_code == 200, f"import exemple chemise ({imp.status_code})")
    run = c.post(f"/v1/orgs/{org}/runs", json={"problem": imp.json()["problem"], "solver": "rpw", "save_problem": True}).json()
    run = wait(c, f"/v1/orgs/{org}/runs/{run['id']}")
    ok(run["status"] == "done", f"calcul {run['id']} ({run.get('stations_used')} stations)")
    twin = c.get(f"/v1/orgs/{org}/runs/{run['id']}/twin").json()
    plan = c.post(f"/v1/orgs/{org}/workshop-plans", json=plan_body(twin["plan"]["stations"])).json()
    ok("id" in plan, f"plan d'atelier {plan.get('id')}")
    lay = c.put(f"/v1/orgs/{org}/runs/{run['id']}/layout", json={"plan_id": plan["id"], "assignment": {}})
    ok(lay.status_code == 200, f"implantation sur le plan ({lay.status_code})")
    mod = c.get(f"/v1/orgs/{org}/runs/{run['id']}/des/model", params={"plan_id": plan["id"]}).json()
    model = mod["model"]
    ok(len(model["stations"]) == run["stations_used"], f"modèle généré : {len(model['stations'])} postes, {len(model['operators'])} opérateurs")
    ok(any(len(v["pts"]) > 2 for v in model["paths"].values()), "chemins à pied par les allées (polylignes)")
    if os.environ.get("E2E_CONVEYOR"):
        cv = model.get("conveyor") or {}
        ok(cv.get("enabled") and len(cv.get("loop") or []) == 4, "rail du plan repris dans le modèle (convoyeur actif)")
        body = {"name": "E2E UPS", "model": model, "replications": 2, "plan_id": plan["id"],
                "scenarios": [{"name": "Convoyeur suspendu"}, {"name": "Paquets / chariots", "overrides": {"conveyor": {"enabled": False}}}]}
        sim = c.post(f"/v1/orgs/{org}/runs/{run['id']}/des", json=body)
        ok(sim.status_code == 202, f"simulation convoyeur lancée ({sim.status_code})")
        s = wait(c, f"/v1/orgs/{org}/simulations/{sim.json()['id']}")
        ok(s["status"] == "done", f"simulation convoyeur terminée {s['id']} {s.get('error', '')}")
        r0, r1 = (it["result"] for it in s["results"]["scenarios"])
        k0, k1 = r0["kpis"], r1["kpis"]
        print(f"     UPS : {k0['pieces']} pcs, encours {k0['wip_avg']}, traversée {k0['lead_time_avg']} min, rail {k0['rail_util_pct']} %, "
              f"cintres {k0['carriers_in_circulation']}, rail/poste {k0['rail_time_avg']}/{k0['station_time_avg']} min ; "
              f"chariots : {k1['pieces']} pcs, encours {k1['wip_avg']}, traversée {k1['lead_time_avg']} min")
        ok(r0["conservation"]["ok"] and r1["conservation"]["ok"], "conservation des pièces (2 scénarios)")
        ok(r0["conveyor"]["carriers"] > 0 and any(e[1] == 4 for e in r0["trace"]["events"]), "cintres animés (trace)")
        ok(r0["model"]["conveyor"]["pts"] and r1["conveyor"] is None, "géométrie du rail renvoyée ; chariots sans convoyeur")
        print(f"     QA : /simulation/{run['id']}?plan={plan['id']}&sim={s['id']}")
        return 1 if FAIL else 0
    body = {"name": "E2E", "model": model, "replications": 3, "plan_id": plan["id"],
            "scenarios": [{"name": "Référence"}, {"name": "Agent de liaison + pannes",
                                                  "overrides": {"transporters": {"count": 1, "capacity": 4},
                                                                "settings": {"transfer": "transporter", "mtbf_min": 120, "mttr_min": 8}}}]}
    sim = c.post(f"/v1/orgs/{org}/runs/{run['id']}/des", json=body)
    ok(sim.status_code == 202, f"simulation lancée ({sim.status_code})")
    s = wait(c, f"/v1/orgs/{org}/simulations/{sim.json()['id']}")
    ok(s["status"] == "done", f"simulation terminée {s['id']} {s.get('error', '')}")
    res = s["results"]
    for it in res["scenarios"]:
        k = it["result"]["kpis"]
        print(f"     {it['name']} : {k['pieces']} pcs, goulot {k['bottleneck']}, traversée {k['lead_time_avg']} min, "
              f"encours {k['wip_avg']}, marche {k['walk_m']} m, IC pièces {it['result']['replications']['kpis']['pieces']}")
        ok(it["result"]["conservation"]["ok"], f"conservation des pièces ({it['name']})")
        ok(len(it["result"]["trace"]["events"]) > 100, f"trace d'animation ({len(it['result']['trace']['events'])} événements)")
    ok(res["scenarios"][1]["result"]["transporters"][0]["loads"] > 0, "agent de liaison actif")
    for ext in ("xlsx", "pdf"):
        e = c.get(f"/v1/orgs/{org}/simulations/{s['id']}/des.{ext}")
        ok(e.status_code == 200 and len(e.content) > 1000, f"export {ext}")
    print(f"     QA : /simulation/{run['id']}?plan={plan['id']}&sim={s['id']}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
