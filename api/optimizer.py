"""Optimiseur de la simulation (phase 2.3) : adaptateur entre calculs / plans d'atelier et
engine.des.optimize (variantes d'implantation candidates, budget Render gratuit, solution → modèle).
Aucune logique de recherche ici."""
from __future__ import annotations

import copy
from typing import Callable, Optional

from engine.des import build_model
from engine.des.builder import compute_paths
from engine.des.optimize import apply_genes, normalize_config, optimize, swap_variant

KEEP = ("settings", "source", "shift", "transporters", "conveyor", "breakdowns", "name")
MAX_BUDGET_S = 90.0          # Render gratuit : la recherche tourne dans le processus de l'API


def variants(plan: dict, layout: dict, workshop_plan: Optional[dict], base_model: dict) -> list[dict]:
    """Implantations candidates : actuelle, en ligne / en U (sans plan d'atelier), postes échangés entre
    machines du même type (raccourcit les trajets)."""
    out = [{"name": "Implantation actuelle", "layout": {"kind": layout.get("kind") or "line",
                                                         "plan_id": layout.get("plan_id")}, "model": base_model}]
    if not workshop_plan:
        for kind, name in (("line", "En ligne"), ("u", "En U")):
            if kind == (layout.get("kind") or "line") and not layout.get("positions_custom"):
                continue
            m = build_model(plan, {"kind": kind}, None)
            for k in KEEP:
                if k in base_model:
                    m[k] = copy.deepcopy(base_model[k])
            m["paths"] = compute_paths(m, None, bool(m.get("transporters")))
            out.append({"name": name, "layout": {"kind": kind}, "model": m})
    sv = swap_variant(base_model)
    if sv:
        sv["paths"] = compute_paths(sv, workshop_plan, bool(sv.get("transporters")))
        out.append({"name": "Postes échangés (machines du même type)",
                    "layout": {"kind": "free", "plan_id": layout.get("plan_id"), "swap": True}, "model": sv})
    return out


def run(vs: list[dict], config: dict, workshop_plan: Optional[dict],
        progress: Optional[Callable[[dict], None]] = None) -> dict:
    cfg = normalize_config(config)
    cfg["time_budget_s"] = min(cfg["time_budget_s"], MAX_BUDGET_S)
    return optimize([{"name": v["name"], "model": v["model"]} for v in vs], cfg, workshop_plan, progress)


def solution_model(vs: list[dict], solution: dict, workshop_plan: Optional[dict]) -> dict:
    g = dict(solution["genes"])
    g["helpers"], g["fewer"] = tuple(g.get("helpers") or ()), tuple(g.get("fewer") or ())
    m = apply_genes([{"name": v["name"], "model": v["model"]} for v in vs], g, workshop_plan)
    m["name"] = f"Optimiseur — solution {solution.get('id')}"
    return m


def layout_to_save(vs: list[dict], solution: dict, model: dict) -> Optional[dict]:
    """Implantation à enregistrer pour le calcul quand la solution change le placement des postes."""
    v = int(solution["genes"].get("layout") or 0)
    if v <= 0 or v >= len(vs):
        return None
    lay = vs[v]["layout"]
    if lay.get("swap"):
        pos = {str(s["id"]): {"x": float(s["x"]), "y": float(s["y"])} for s in model["stations"]}
        asg = {str(s["id"]): list(s.get("machine_ids") or []) for s in model["stations"] if s.get("machine_ids")}
        return {"kind": "free", "positions": pos, "plan_id": lay.get("plan_id"), "assignment": asg if lay.get("plan_id") else None}
    return {"kind": lay["kind"], "positions": {}, "plan_id": None, "assignment": None}
