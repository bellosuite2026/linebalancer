"""Expérimentateur : plusieurs réplications (graines) × scénarios, moyenne et intervalle de confiance
à 95 % (loi de Student) des indicateurs clés."""
from __future__ import annotations

import math
import statistics
from collections import Counter
from typing import Optional

from engine.des.model import LIMITS, apply_overrides, normalize_model
from engine.des.sim import simulate

# t de Student bilatéral 95 % (ddl 1..30 ; au-delà ≈ 1,96)
_T95 = [12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228, 2.201, 2.179, 2.160, 2.145,
        2.131, 2.120, 2.110, 2.101, 2.093, 2.086, 2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048,
        2.045, 2.042]

KPI_KEYS = ["pieces", "per_hour", "lead_time_avg", "wip_avg", "wip_max", "operator_util_avg", "walk_m",
            "transport_m", "defects"]


def t95(df: int) -> float:
    return _T95[df - 1] if 1 <= df <= len(_T95) else 1.96


def ci(values: list[float]) -> dict:
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return {"mean": None, "sd": None, "lo": None, "hi": None, "n": 0}
    mean = statistics.mean(vals)
    if len(vals) < 2:
        return {"mean": round(mean, 2), "sd": 0.0, "lo": round(mean, 2), "hi": round(mean, 2), "n": 1}
    sd = statistics.stdev(vals)
    h = t95(len(vals) - 1) * sd / math.sqrt(len(vals))
    return {"mean": round(mean, 2), "sd": round(sd, 2), "lo": round(mean - h, 2), "hi": round(mean + h, 2),
            "n": len(vals)}


def run_scenario(model: dict, replications: int = 1, seed: Optional[int] = None, trace: bool = True) -> dict:
    """Réplication 1 complète (trace + détails), réplications suivantes = indicateurs seulement."""
    n = max(1, min(LIMITS["replications"], int(replications)))
    m = normalize_model(model)
    base_seed = m["settings"]["seed"] if seed is None else int(seed)
    first = simulate(m, base_seed, trace)
    kpis = [first["kpis"]]
    station_util = {s["id"]: [s["utilization_pct"]] for s in first["stations"]}
    for r in range(1, n):
        res = simulate(m, base_seed + r, False)
        kpis.append(res["kpis"])
        for s in res["stations"]:
            station_util[s["id"]].append(s["utilization_pct"])
    summary = {k: ci([kp.get(k) for kp in kpis]) for k in KPI_KEYS}
    summary["bottleneck"] = Counter(kp["bottleneck"] for kp in kpis).most_common(1)[0][0]
    first["replications"] = {"n": n, "seeds": [base_seed + r for r in range(n)], "kpis": summary,
                             "values": {k: [kp.get(k) for kp in kpis] for k in KPI_KEYS},
                             "station_util": {k: ci(v) for k, v in station_util.items()}}
    return first


def run_experiment(model: dict, scenarios: Optional[list[dict]] = None, replications: int = 1,
                   trace: bool = True, max_trace_events: Optional[int] = None) -> dict:
    """scenarios : [{"name": "...", "overrides": {...}}] (vide = modèle de base seul)."""
    scenarios = (scenarios or [{"name": "Référence", "overrides": {}}])[: LIMITS["scenarios"]]
    out = []
    for sc in scenarios:
        m = apply_overrides(model, sc.get("overrides") or {})
        if max_trace_events is not None:
            m.setdefault("settings", {})["max_trace_events"] = max_trace_events
        res = run_scenario(m, replications, trace=trace)
        res["model"] = model_for_view(normalize_model(m))
        out.append({"name": str(sc.get("name") or "Scénario")[:60], "overrides": sc.get("overrides") or {},
                    "result": res})
    return {"scenarios": out, "comparison": comparison(out)}


def model_for_view(m: dict) -> dict:
    """Ce que l'animation doit connaître du modèle (positions, files, acteurs, chemins)."""
    keep = ("id", "label", "x", "y", "qx", "qy", "servers", "operators", "machine_ids", "machine_type", "minutes",
            "setup_min", "mtbf_min", "mttr_min", "defect_pct", "rework_to", "queue_capacity", "operations")
    return {"name": m["name"], "stations": [{k: s.get(k) for k in keep} for s in m["stations"]],
            "route": m["route"], "operators": m["operators"], "transporters": m["transporters"],
            "source": m["source"], "sink": m["sink"], "shift": m["shift"], "settings": m["settings"],
            "plan_id": m.get("plan_id")}


COMPARISON_ROWS = [
    ("pieces", "Pièces produites"), ("per_hour", "Pièces / heure"), ("lead_time_avg", "Temps de traversée moyen (min)"),
    ("wip_avg", "Encours moyen (pièces)"), ("wip_max", "Encours max (pièces)"),
    ("operator_util_avg", "Occupation opérateurs (%)"), ("walk_m", "Marche des opérateurs (m)"),
    ("transport_m", "Transport des paquets (m)"), ("defects", "Pièces en retouche"),
]


def comparison(items: list[dict]) -> list[dict]:
    rows = []
    for key, label in COMPARISON_ROWS:
        rows.append({"key": key, "label": label,
                     "values": [it["result"]["replications"]["kpis"][key] for it in items]})
    rows.append({"key": "bottleneck", "label": "Goulot (poste)",
                 "values": [{"mean": it["result"]["replications"]["kpis"]["bottleneck"]} for it in items]})
    return rows
