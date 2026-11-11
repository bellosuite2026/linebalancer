"""Modèle de simulation (format JSON commun moteur / API / interface) et valeurs par défaut.

Un modèle décrit l'atelier comme FlexSim : Source → File → Poste → … → Sortie, avec opérateurs
(ressources mobiles qui marchent entre leurs postes) et transporteurs (agents de liaison / chariots).

    {
      "name": str,
      "shift": {"minutes": 480, "breaks": [{"start_min": 120, "minutes": 15, "label": "Pause"}]},
      "source": {"lots": [{"style": "Chemise", "size": "M", "qty": 600}], "bundle_size": 10,
                 "interval_min": 0, "wip_cap_bundles": null, "start_wip_bundles": 1, "x": .., "y": ..},
      "sink": {"x": .., "y": ..},
      "stations": [{"id": "1", "label": "Station 1", "x": .., "y": .., "qx": .., "qy": ..,
                    "minutes": 1.2, "servers": 1, "operators": ["W1"], "setup_min": 0, "handling_min": 0.1,
                    "dist": {...}, "mtbf_min": 0, "mttr_min": 0, "defect_pct": 0, "rework_to": null,
                    "queue_capacity": 6, "out_capacity": 3, "machine_ids": [], "machine_type": "",
                    "operations": ["Monter col"]}],
      "route": ["1", "2", ...],
      "operators": [{"id": "W1", "name": "Nadia", "efficiency": 1.0, "stations": ["1"]}],
      "transporters": [{"id": "T1", "name": "Agent de liaison 1", "capacity": 4, "speed_m_per_min": 60,
                        "load_min": 0.2}],
      "breakdowns": [{"station": "3", "start_min": 60, "duration_min": 30}],
      "settings": {...DEFAULT_SETTINGS},
      "points": {"1": [x, y], "src": [x, y], "sink": [x, y]},
      "paths": {"a|b": {"m": 3.2, "pts": [[x, y], ...]}}
    }

`x, y` = position de l'opérateur au poste (m, repère du plan : y vers le bas) ; `qx, qy` = chariot
d'encours (file d'entrée) du poste.
"""
from __future__ import annotations

import copy
from typing import Any, Optional

from engine.des.conveyor import normalize_conveyor
from engine.des.distributions import normalize as normalize_dist

LIMITS = {"stations": 150, "operators": 200, "transporters": 12, "shift_minutes": 960, "bundle_size": 200,
          "replications": 20, "scenarios": 3, "trace_events": 90000, "breaks": 10, "lots": 50}

DEFAULT_SETTINGS: dict[str, Any] = {
    "walk_speed_m_per_min": 60.0,     # ~1 m/s à pied
    "efficiency": 1.0,                # efficience de la ligne (1 = temps standard)
    "dist": {"kind": "normal", "cv": 0.10, "low_pct": 80, "high_pct": 140},
    "setup_min": 0.0,                 # mise en route à chaque changement de modèle / taille
    "handling_min": 0.10,             # prise + dépose d'un paquet
    "mtbf_min": 0.0,                  # pannes aléatoires (0 = aucune)
    "mttr_min": 0.0,
    "defect_pct": 0.0,                # défauts au contrôle (dernier poste) → retouche
    "queue_capacity": 6,              # paquets par chariot d'encours
    "out_capacity": 3,                # paquets en attente d'enlèvement (transporteur)
    "transfer": "auto",               # auto | operator | transporter | handoff
    "carry_threshold_m": 2.5,         # au-delà, le paquet est porté (opérateur ou transporteur)
    "seed": 42,
    "trace": True,
    "max_trace_events": 60000,
    "snapshot_every_min": 5.0,
    "target_per_hour": None,
}

STATION_STATES = ["travail", "attente matière", "bloqué aval", "panne", "mise en route", "attente opérateur",
                  "pause", "transfert"]
OPERATOR_STATES = ["inactif", "marche", "travail", "mise en route", "transport", "pause", "attente"]
TRANSPORTER_STATES = ["inactif", "à vide", "chargé", "chargement", "attente", "pause"]
STATION_DEFAULT_KEYS = ("setup_min", "handling_min", "mtbf_min", "mttr_min", "queue_capacity", "out_capacity", "dist")
LOC_KINDS = ["file", "poste", "sortie poste", "opérateur", "transporteur", "terminé", "source"]


def _f(v, default=0.0, lo=None, hi=None) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        x = float(default)
    if x != x:  # NaN
        x = float(default)
    if lo is not None:
        x = max(lo, x)
    if hi is not None:
        x = min(hi, x)
    return x


def _i(v, default=0, lo=None, hi=None) -> int:
    return int(round(_f(v, default, lo, hi)))


class ModelError(ValueError):
    pass


def normalize_model(model: dict) -> dict:
    """Complète et borne un modèle (copie). Lève ModelError si inutilisable."""
    m = copy.deepcopy(model or {})
    st_in = [s for s in m.get("stations") or [] if isinstance(s, dict)]
    if not st_in:
        raise ModelError("Le modèle ne contient aucun poste.")
    if len(st_in) > LIMITS["stations"]:
        raise ModelError(f"Trop de postes ({len(st_in)} > {LIMITS['stations']}).")
    s = {**DEFAULT_SETTINGS, **(m.get("settings") or {})}
    s["dist"] = normalize_dist(s.get("dist"))
    s["walk_speed_m_per_min"] = _f(s["walk_speed_m_per_min"], 60, 5, 300)
    s["efficiency"] = _f(s["efficiency"], 1, 0.1, 2.5)
    for k in ("setup_min", "handling_min", "mtbf_min", "mttr_min"):
        s[k] = _f(s[k], 0, 0, 10000)
    s["defect_pct"] = _f(s["defect_pct"], 0, 0, 60)
    s["queue_capacity"] = _i(s["queue_capacity"], 6, 1, 500)
    s["out_capacity"] = _i(s["out_capacity"], 3, 1, 100)
    s["transfer"] = s["transfer"] if s["transfer"] in ("auto", "operator", "transporter", "handoff") else "auto"
    s["carry_threshold_m"] = _f(s["carry_threshold_m"], 2.5, 0, 100)
    s["seed"] = _i(s["seed"], 42, 0, 2**31 - 1)
    s["max_trace_events"] = _i(s["max_trace_events"], 60000, 0, LIMITS["trace_events"])
    s["snapshot_every_min"] = _f(s["snapshot_every_min"], 5, 0.5, 60)
    s["target_per_hour"] = None if s.get("target_per_hour") in (None, "") else _f(s["target_per_hour"], 0, 0, 1e6)
    m["settings"] = s

    sh = m.get("shift") or {}
    T = _f(sh.get("minutes"), 480, 10, LIMITS["shift_minutes"])
    breaks = []
    for b in (sh.get("breaks") or [])[: LIMITS["breaks"]]:
        a, d = _f(b.get("start_min"), 0, 0, T), _f(b.get("minutes"), 0, 0, T)
        if d > 0:
            breaks.append({"start_min": a, "minutes": min(d, T - a), "label": str(b.get("label") or "Pause")[:40]})
    breaks.sort(key=lambda b: b["start_min"])
    m["shift"] = {"minutes": T, "breaks": breaks}

    ids = []
    stations = []
    for k, st in enumerate(st_in):
        sid = str(st.get("id") if st.get("id") not in (None, "") else k + 1)
        if sid in ids:
            raise ModelError(f"Poste en double : {sid}.")
        ids.append(sid)
        x, y = _f(st.get("x"), k * 1.6), _f(st.get("y"), 0)
        stations.append({
            "id": sid, "label": str(st.get("label") or f"Poste {sid}")[:60],
            "x": x, "y": y, "qx": _f(st.get("qx"), x - 0.55), "qy": _f(st.get("qy"), y + 0.35),
            "mx": _f(st.get("mx"), x), "my": _f(st.get("my"), y - 0.75), "rot": _f(st.get("rot"), 0),
            "machine": str(st.get("machine") or "")[:60],
            "minutes": _f(st.get("minutes"), 0, 0, 1000), "servers": _i(st.get("servers"), 1, 1, 20),
            "operators": [str(o) for o in st.get("operators") or []],
            "setup_min": _f(st.get("setup_min"), s["setup_min"], 0, 1000),
            "handling_min": _f(st.get("handling_min"), s["handling_min"], 0, 100),
            "dist": normalize_dist(st.get("dist")) if st.get("dist") else s["dist"],
            "mtbf_min": _f(st.get("mtbf_min"), s["mtbf_min"], 0, 1e6),
            "mttr_min": _f(st.get("mttr_min"), s["mttr_min"], 0, 1e4),
            "defect_pct": _f(st.get("defect_pct"), 0, 0, 60),
            "rework_to": None if st.get("rework_to") in (None, "") else str(st.get("rework_to")),
            "queue_capacity": _i(st.get("queue_capacity"), s["queue_capacity"], 1, 500),
            "out_capacity": _i(st.get("out_capacity"), s["out_capacity"], 1, 100),
            "machine_ids": [str(x) for x in st.get("machine_ids") or []][:6],
            "machine_type": str(st.get("machine_type") or "")[:60],
            "operations": [str(x)[:80] for x in st.get("operations") or []][:30],
            "skills": [str(x)[:60] for x in st.get("skills") or []][:20],
            "machine_types": [str(x)[:60] for x in st.get("machine_types") or []][:10],
        })
    route = [str(r) for r in m.get("route") or ids if str(r) in ids] or ids
    # défauts au contrôle par défaut : dernier poste de la gamme, retouche au poste précédent
    if s["defect_pct"] > 0 and not any(st["defect_pct"] for st in stations):
        last = next(st for st in stations if st["id"] == route[-1])
        last["defect_pct"] = s["defect_pct"]
    for st in stations:
        if st["defect_pct"] > 0 and (st["rework_to"] not in ids):
            i = route.index(st["id"]) if st["id"] in route else 0
            st["rework_to"] = route[max(0, i - 1)]
    m["stations"] = stations
    m["route"] = route

    ops_in = [o for o in m.get("operators") or [] if isinstance(o, dict)][: LIMITS["operators"]]
    ops, known = [], set()
    for o in ops_in:
        oid = str(o.get("id") or f"O{len(ops) + 1}")
        if oid in known:
            continue
        known.add(oid)
        ops.append({"id": oid, "name": str(o.get("name") or oid)[:60], "efficiency": _f(o.get("efficiency"), 1, 0.1, 3),
                    "stations": [str(x) for x in o.get("stations") or [] if str(x) in ids],
                    "skills": [str(x)[:60] for x in o.get("skills") or []][:30]})
    for st in stations:   # opérateurs déclarés au poste
        for oid in st["operators"]:
            if oid not in known:
                known.add(oid)
                ops.append({"id": oid, "name": oid, "efficiency": 1.0, "stations": [st["id"]]})
            o = next(o for o in ops if o["id"] == oid)
            if st["id"] not in o["stations"]:
                o["stations"].append(st["id"])
    for o in ops:
        for sid in o["stations"]:
            st = next(st for st in stations if st["id"] == sid)
            if o["id"] not in st["operators"]:
                st["operators"].append(o["id"])
    m["operators"] = ops

    trs = []
    for k, t in enumerate((m.get("transporters") or [])[: LIMITS["transporters"]]):
        trs.append({"id": str(t.get("id") or f"T{k + 1}"), "name": str(t.get("name") or f"Agent de liaison {k + 1}")[:60],
                    "capacity": _i(t.get("capacity"), 4, 1, 50), "speed_m_per_min": _f(t.get("speed_m_per_min"), 60, 5, 300),
                    "load_min": _f(t.get("load_min"), 0.2, 0, 30)})
    m["transporters"] = trs

    src = m.get("source") or {}
    lots = []
    for lot in (src.get("lots") or [])[: LIMITS["lots"]]:
        lots.append({"style": str(lot.get("style") or "Modèle")[:40], "size": str(lot.get("size") or "")[:20],
                     "qty": _i(lot.get("qty"), 0, 0, 10_000_000)})
    if not lots:
        lots = [{"style": "Modèle", "size": "", "qty": 0}]
    first = next(st for st in stations if st["id"] == route[0])
    last = next(st for st in stations if st["id"] == route[-1])
    m["source"] = {"lots": lots, "bundle_size": _i(src.get("bundle_size"), 10, 1, LIMITS["bundle_size"]),
                   "interval_min": _f(src.get("interval_min"), 0, 0, 1000),
                   "wip_cap_bundles": None if src.get("wip_cap_bundles") in (None, "", 0) else _i(src["wip_cap_bundles"], 1, 1, 10000),
                   "start_wip_bundles": _i(src.get("start_wip_bundles"), 1, 0, 20),
                   "x": _f(src.get("x"), first["qx"] - 1.0), "y": _f(src.get("y"), first["qy"])}
    snk = m.get("sink") or {}
    m["sink"] = {"x": _f(snk.get("x"), last["x"] + 1.2), "y": _f(snk.get("y"), last["y"])}
    bds = []
    for b in m.get("breakdowns") or []:
        if str(b.get("station")) in ids:
            bds.append({"station": str(b.get("station")), "start_min": _f(b.get("start_min"), 0, 0, T),
                        "duration_min": _f(b.get("duration_min"), 0, 0, T)})
    m["breakdowns"] = bds
    pts = {st["id"]: [st["x"], st["y"]] for st in stations}
    pts["src"] = [m["source"]["x"], m["source"]["y"]]
    pts["sink"] = [m["sink"]["x"], m["sink"]["y"]]
    m["points"] = {**pts, **{k: v for k, v in (m.get("points") or {}).items() if k not in pts}}
    m["paths"] = m.get("paths") or {}
    try:
        m["conveyor"] = normalize_conveyor(m)
    except ValueError as e:
        raise ModelError(str(e))
    if m["conveyor"]["enabled"]:
        # sur convoyeur : un cintre = un « paquet » ; la dérivation de chaque poste = sa file
        # encours de départ équivalent en pièces (paquets × pièces par paquet) réparti sur des cintres
        if "start_wip_pieces" not in m["source"]:
            m["source"]["start_wip_pieces"] = m["source"]["start_wip_bundles"] * m["source"]["bundle_size"]
        m["source"]["bundle_size"] = m["conveyor"]["carrier_capacity"]
        m["source"]["start_wip_bundles"] = min(m["conveyor"]["station_wip"], -(-int(m["source"]["start_wip_pieces"]) // m["conveyor"]["carrier_capacity"]))
        for st in stations:
            st["queue_capacity"] = m["conveyor"]["station_wip"]
    m["name"] = str(m.get("name") or "Modèle")[:120]
    return m


def deep_merge(base: dict, over: Optional[dict]) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def apply_overrides(model: dict, ov: Optional[dict]) -> dict:
    """Scénario : réglages / source / équipe / transporteurs / postes surchargés."""
    ov = ov or {}
    m = copy.deepcopy(model)
    for key in ("settings", "source", "shift", "conveyor"):
        if ov.get(key):
            m[key] = deep_merge(m.get(key) or {}, ov[key])
    # un réglage général du scénario s'applique à tous les postes (les surcharges par poste suivent)
    for k in STATION_DEFAULT_KEYS + ("defect_pct",):
        if k in (ov.get("settings") or {}):
            for st in m.get("stations") or []:
                st.pop(k, None)
    if "breaks" in (ov.get("shift") or {}):
        m["shift"]["breaks"] = list(ov["shift"]["breaks"] or [])
    if "lots" in (ov.get("source") or {}):
        m["source"]["lots"] = list(ov["source"]["lots"] or [])
    if "transporters" in ov and ov["transporters"] is not None:
        t = ov["transporters"]
        if isinstance(t, dict):   # {"count": 2, "capacity": 4, "speed_m_per_min": 60}
            n = _i(t.get("count"), 0, 0, LIMITS["transporters"])
            m["transporters"] = [{"id": f"T{k + 1}", "name": f"Agent de liaison {k + 1}",
                                  "capacity": t.get("capacity", 4), "speed_m_per_min": t.get("speed_m_per_min", 60),
                                  "load_min": t.get("load_min", 0.2)} for k in range(n)]
        else:
            m["transporters"] = list(t)
    st_ov = ov.get("stations") or {}
    if st_ov:
        for st in m["stations"]:
            if str(st["id"]) in st_ov:
                st.update(st_ov[str(st["id"])] or {})
    if ov.get("breakdowns") is not None:
        m["breakdowns"] = list(ov["breakdowns"])
    return m
