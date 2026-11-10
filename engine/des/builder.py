"""Génération automatique du modèle de simulation depuis un calcul d'équilibrage (plan de ligne du
jumeau : stations, temps, ouvrières) + une implantation (ligne / U / plan d'atelier).

- un poste par station du calcul (serveurs = opératrices en parallèle) ;
- une file (chariot d'encours) devant chaque poste ;
- opérateurs = ouvrières de l'équilibrage (une ouvrière partagée tient plusieurs postes voisins) ;
- chemins à pied par les allées du plan d'atelier (murs, poteaux et machines contournés) ou en ligne
  droite sans plan.
"""
from __future__ import annotations

import math
from typing import Optional

from engine import workshop as W
from engine.des.model import normalize_model
from engine.des.paths import PathTable, grid_paths
from engine.simulation import _positions, station_workers


def _queue_point(x: float, y: float, machine: Optional[dict]) -> tuple[float, float]:
    """Chariot d'encours : à gauche de l'opératrice (côté amont), le long de la table."""
    if machine:
        w, _d = W._dims(machine)
        dx, dy = W._rot(-(w / 2 + 0.35), 0, W._num(machine.get("rot")))
        cx, cy = W._num(machine.get("x")), W._num(machine.get("y"))
        return round(cx + dx, 2), round(cy + dy, 2)
    return round(x - 0.55, 2), round(y + 0.35, 2)


def build_model(plan: dict, layout: Optional[dict] = None, workshop_plan: Optional[dict] = None,
                settings: Optional[dict] = None, name: str = "") -> dict:
    """Modèle brut (non normalisé : les réglages généraux s'appliquent aux postes sans valeur propre)."""
    layout = layout or {}
    order = [int(s["station"]) for s in plan.get("stations", [])]
    pos = _positions(plan, layout)
    sw = station_workers(plan)
    for st in plan.get("stations", []):
        if "operators" in st and int(st.get("operators") or 0) == 0 and not st.get("worker_ids"):
            sw[int(st["station"])] = []
    winfo = plan.get("workers") or {}
    assignment = layout.get("assignment") or {}
    ms = {str(m.get("id")): m for m in W.machines(workshop_plan or {})}
    stations = []
    for st in plan.get("stations", []):
        sid = int(st["station"])
        workers = sw.get(sid) or []
        mids = [m for m in assignment.get(str(sid)) or [] if m in ms]
        mach = ms[mids[0]] if mids else None
        x, y = pos[sid]
        qx, qy = _queue_point(x, y, mach)
        mx, my = (round(W._num(mach.get("x")), 2), round(W._num(mach.get("y")), 2)) if mach else (round(x, 2), round(y - 0.75, 2))
        types = W.station_types(st)
        stations.append({
            "id": str(sid), "label": f"Station {sid}", "x": round(x, 2), "y": round(y, 2), "qx": qx, "qy": qy, "mx": mx, "my": my,
            "rot": W._num(mach.get("rot")) if mach else 0.0, "machine": (mach or {}).get("type") or "",
            "minutes": float(st.get("minutes") or 0), "servers": max(1, len(workers)), "operators": list(workers),
            "machine_ids": mids, "machine_type": types[0] if types else "manuel",
            "operations": [str(o.get("name") or o.get("id") or "") for o in st.get("operations") or []],
        })
    by_op: dict[str, list[str]] = {}
    for st in stations:
        for w in st["operators"]:
            by_op.setdefault(w, []).append(st["id"])
    operators = []
    unq = plan.get("unqualified") or {}
    for w, sts in by_op.items():
        info = winfo.get(w) or {}
        eff = float(info.get("efficiency") or 1.0) or 1.0
        if unq.get(w):
            eff *= 0.5
        operators.append({"id": w, "name": str(info.get("name") or _label(plan, w)), "efficiency": eff, "stations": sts})
    # une station tenue par 2 ouvrières = 2 serveurs ; partagée = 1 serveur par ouvrière présente
    first, last = stations[0], stations[-1]
    src = {"x": round(first["qx"] - 1.0, 2), "y": first["qy"]}
    sink = {"x": round(last["x"] + 1.4, 2), "y": last["y"]}
    target = None
    c = plan.get("cycle_time") or plan.get("takt_time")
    if c:
        try:
            target = round(60.0 / float(c), 1)
        except (TypeError, ValueError, ZeroDivisionError):
            target = None
    model = {
        "name": name or plan.get("problem_name") or "Ligne",
        "shift": {"minutes": 480, "breaks": [{"start_min": 120, "minutes": 15, "label": "Pause"},
                                              {"start_min": 240, "minutes": 30, "label": "Déjeuner"}]},
        "source": {"lots": [{"style": plan.get("problem_name") or "Modèle", "size": "", "qty": 0}],
                   "bundle_size": 10, "interval_min": 0, "start_wip_bundles": 1, **src},
        "sink": sink, "stations": stations, "route": [s["id"] for s in stations], "operators": operators,
        "transporters": [], "settings": {**(settings or {}), "target_per_hour": target},
        "plan_id": layout.get("plan_id"),
    }
    model["paths"] = compute_paths(model, workshop_plan, with_all_pairs=False)
    return model


def _label(plan: dict, wid: str) -> str:
    for st in plan.get("stations", []):
        ids, names = list(st.get("worker_ids") or []), list(st.get("workers") or [])
        if wid in ids and ids.index(wid) < len(names):
            return str(names[ids.index(wid)])
    return f"Opératrice {wid[1:]}" if wid.startswith("S") and "-" in wid else wid


def needed_pairs(model: dict, all_pairs: bool) -> list[tuple[str, str]]:
    route = [str(r) for r in model.get("route") or [s["id"] for s in model["stations"]]]
    pairs = [("src", route[0]), (route[-1], "sink")] + list(zip(route, route[1:]))
    for o in model.get("operators") or []:
        sts = [str(s) for s in o.get("stations") or []]
        pairs += [(a, b) for i, a in enumerate(sts) for b in sts[i + 1:]]
    for st in model["stations"]:
        if st.get("rework_to"):
            pairs.append((str(st["id"]), str(st["rework_to"])))
    if all_pairs or model.get("transporters"):
        keys = ["src"] + route
        pairs += [(a, b) for i, a in enumerate(keys) for b in keys[i + 1:]]
    return list(dict.fromkeys(pairs))


def compute_paths(model: dict, workshop_plan: Optional[dict], with_all_pairs: bool = False) -> dict:
    pts = {str(s["id"]): (float(s["x"]), float(s["y"])) for s in model["stations"]}
    pts["src"] = (float(model["source"]["x"]), float(model["source"]["y"]))
    pts["sink"] = (float(model["sink"]["x"]), float(model["sink"]["y"]))
    pairs = needed_pairs(model, with_all_pairs)
    if workshop_plan and W.machines(workshop_plan):
        grid = W.WorkshopGrid(workshop_plan)
        allow = {str(s["id"]): list(s.get("machine_ids") or []) for s in model["stations"]}
        return grid_paths(grid, pts, pairs, allow).to_json()
    t = PathTable(pts)
    for a, b in pairs:
        t.get(a, b)
    return t.to_json()


def ensure_paths(model: dict, workshop_plan: Optional[dict]) -> dict:
    """Ajoute les chemins manquants (transporteurs ajoutés, opérateurs réaffectés)."""
    have = set(model.get("paths") or {})
    missing = [(a, b) for a, b in needed_pairs(model, False)
               if f"{min(a, b)}|{max(a, b)}" not in have]
    if missing:
        extra = compute_paths({**model, "operators": model.get("operators")}, workshop_plan, False)
        model["paths"] = {**extra, **(model.get("paths") or {})}
    return model


def summary(model: dict) -> dict:
    m = normalize_model(model)
    return {"stations": len(m["stations"]), "operators": len(m["operators"]), "transporters": len(m["transporters"]),
            "sam_total": round(sum(s["minutes"] for s in m["stations"]), 3),
            "path_m": round(sum(v.get("m", 0) for v in (m.get("paths") or {}).values()), 1),
            "length_m": round(max((math.dist((s["x"], s["y"]), (t["x"], t["y"])) for s in m["stations"] for t in m["stations"]),
                                  default=0), 1)}
