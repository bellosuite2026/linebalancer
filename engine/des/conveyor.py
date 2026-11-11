"""Convoyeur suspendu (type Eton / INA / UPS) : géométrie du rail et réglages.

Le rail est une boucle principale fermée (tronçons droits + courbes aux angles) parcourue dans un seul
sens, à une hauteur donnée. Chaque poste est relié à la boucle par une dérivation (aiguillage d'entrée,
tampon de cintres = limite d'encours de la station, aiguillage de sortie). Une station de chargement
(lancement des pièces sur des cintres vides) et une station de déchargement (pièces terminées) sont
placées sur la boucle. Les cintres (porte-pièces) ont un identifiant (C001…) et une capacité en pièces.

    "conveyor": {
      "enabled": true, "name": "UPS ligne 1",
      "speed_m_per_min": 18, "switch_sec": 2.0, "carriers": 0 (0 = automatique), "carrier_capacity": 1,
      "station_wip": 4, "load_min": 0.10, "unload_min": 0.05, "pitch_m": 0.30, "height_m": 2.1,
      "corner_radius_m": 0.5, "margin_m": 0.7, "dynamic_routing": true, "max_on_rail": 0 (0 = 2 par poste),
      "loop": [[x, y], ...]            # sommets de la boucle (vide = générée autour des postes)
      "load": [x, y], "unload": [x, y],  # points projetés sur la boucle (vide = près de l'entrée / sortie)
      "alternates": {"3": ["7"]}        # postes interchangeables (même compétence) pour la réaffectation
    }

`normalize_conveyor` complète la géométrie : `pts` (boucle aplatie, fermée), `length_m`, `segments`
(droits / courbes), `spurs` (abscisse curviligne de l'aiguillage, point sur la boucle, longueur de la
dérivation), `s_load`, `s_unload`, `capacity` (cintres que le rail peut porter = longueur / pas).
"""
from __future__ import annotations

import math
from typing import Any, Optional

P = tuple[float, float]

CONVEYOR_DEFAULTS: dict[str, Any] = {
    "enabled": False, "name": "Convoyeur suspendu", "speed_m_per_min": 18.0, "switch_sec": 2.0, "carriers": 0,
    "carrier_capacity": 1, "station_wip": 4, "load_min": 0.10, "unload_min": 0.05, "pitch_m": 0.30,
    "height_m": 2.1, "corner_radius_m": 0.5, "margin_m": 0.7, "dynamic_routing": True, "max_on_rail": 0, "loop": [],
    "load": None, "unload": None, "alternates": {},
}
MAX_CARRIERS = 2000


def _f(v, d, lo, hi) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        x = float(d)
    if x != x:
        x = float(d)
    return max(lo, min(hi, x))


def _pt(v) -> Optional[P]:
    try:
        return (float(v[0]), float(v[1]))
    except (TypeError, ValueError, IndexError, KeyError):
        return None


# ------------------------------------------------------------------ géométrie
def auto_loop(stations: list[dict], margin: float) -> list[P]:
    """Boucle rectangulaire autour des postes : départ en bas à gauche, sens de la ligne (gauche → droite
    en bas, retour en haut), comme une boucle principale UPS au-dessus de la ligne."""
    xs = [v for s in stations for v in (s["x"], s["qx"], s["mx"])]
    ys = [v for s in stations for v in (s["y"], s["qy"], s["my"])]
    x0, x1, y0, y1 = min(xs) - margin, max(xs) + margin, min(ys) - margin, max(ys) + margin
    if y1 - y0 < 1.2:
        c = (y0 + y1) / 2
        y0, y1 = c - 0.6, c + 0.6
    return [(x0, y1), (x1, y1), (x1, y0), (x0, y0)]


def flatten(loop: list[P], radius: float, arc_steps: int = 6) -> tuple[list[P], list[dict]]:
    """Boucle fermée aplatie : angles arrondis (courbes de rayon ≈ `radius`). Renvoie les points (le
    dernier = le premier) et les tronçons [{kind: line|arc, s0, s1}]."""
    n = len(loop)
    pts: list[P] = []
    corners: list[tuple[P, P, P]] = []
    for i in range(n):
        a, b, c = loop[i - 1], loop[i], loop[(i + 1) % n]
        la, lc = math.dist(a, b), math.dist(b, c)
        r = min(radius, la / 2.01, lc / 2.01) if la > 1e-9 and lc > 1e-9 else 0.0
        if r <= 1e-6:
            corners.append((b, b, b))
            continue
        p0 = (b[0] + (a[0] - b[0]) * r / la, b[1] + (a[1] - b[1]) * r / la)
        p1 = (b[0] + (c[0] - b[0]) * r / lc, b[1] + (c[1] - b[1]) * r / lc)
        corners.append((p0, b, p1))
    segs: list[dict] = []
    s = 0.0

    def add(p: P):
        nonlocal s
        if pts:
            s += math.dist(pts[-1], p)
        pts.append(p)

    for i in range(n):
        p0, b, p1 = corners[i]
        if p0 == p1:
            add(b)
            continue
        add(p0)
        s_arc0 = s
        for k in range(1, arc_steps + 1):    # courbe de Bézier quadratique (proche d'un arc de cercle)
            u = k / arc_steps
            add(((1 - u) ** 2 * p0[0] + 2 * u * (1 - u) * b[0] + u * u * p1[0],
                 (1 - u) ** 2 * p0[1] + 2 * u * (1 - u) * b[1] + u * u * p1[1]))
        segs.append({"kind": "arc", "s0": round(s_arc0, 3), "s1": round(s, 3)})
    add(pts[0])
    # tronçons droits = entre les courbes
    arcs = sorted(segs, key=lambda x: x["s0"])
    lines, cur = [], 0.0
    for a in arcs:
        if a["s0"] - cur > 1e-3:
            lines.append({"kind": "line", "s0": round(cur, 3), "s1": a["s0"]})
        cur = a["s1"]
    if s - cur > 1e-3:
        lines.append({"kind": "line", "s0": round(cur, 3), "s1": round(s, 3)})
    return pts, sorted(arcs + lines, key=lambda x: x["s0"])


def cumulative(pts: list[P]) -> list[float]:
    cum = [0.0]
    for i in range(1, len(pts)):
        cum.append(cum[-1] + math.dist(pts[i - 1], pts[i]))
    return cum


def project(pts: list[P], cum: list[float], p: P) -> tuple[float, P, float]:
    """Point de la boucle le plus proche de p : (abscisse curviligne, point, distance)."""
    best = (0.0, pts[0], math.inf)
    for i in range(1, len(pts)):
        a, b = pts[i - 1], pts[i]
        dx, dy = b[0] - a[0], b[1] - a[1]
        L2 = dx * dx + dy * dy
        u = 0.0 if L2 < 1e-12 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
        q = (a[0] + u * dx, a[1] + u * dy)
        d = math.dist(p, q)
        if d < best[2] - 1e-9:
            best = (cum[i - 1] + u * math.sqrt(L2), q, d)
    return best


def point_at(pts: list[P], cum: list[float], s: float) -> P:
    L = cum[-1]
    s = s % L if L > 0 else 0.0
    for i in range(1, len(pts)):
        if s <= cum[i] or i == len(pts) - 1:
            seg = cum[i] - cum[i - 1]
            u = 0.0 if seg <= 0 else (s - cum[i - 1]) / seg
            a, b = pts[i - 1], pts[i]
            return (a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u)
    return pts[-1]


# ------------------------------------------------------------------ réglages
def normalize_conveyor(m: dict) -> dict:
    """Complète `m["conveyor"]` (copie déjà faite par normalize_model) ; m["stations"] normalisés."""
    raw = m.get("conveyor") or {}
    c = {**CONVEYOR_DEFAULTS, **{k: v for k, v in raw.items() if v is not None}}
    c["enabled"] = bool(c.get("enabled"))
    c["name"] = str(c.get("name") or "Convoyeur suspendu")[:60]
    c["speed_m_per_min"] = _f(c["speed_m_per_min"], 18, 1, 120)
    c["switch_sec"] = _f(c["switch_sec"], 2, 0, 60)
    c["carrier_capacity"] = int(_f(c["carrier_capacity"], 1, 1, 50))
    c["station_wip"] = int(_f(c["station_wip"], 4, 1, 50))
    c["load_min"] = _f(c["load_min"], 0.1, 0, 30)
    c["unload_min"] = _f(c["unload_min"], 0.05, 0, 30)
    c["pitch_m"] = _f(c["pitch_m"], 0.3, 0.05, 5)
    c["height_m"] = _f(c["height_m"], 2.1, 1.2, 4)
    c["corner_radius_m"] = _f(c["corner_radius_m"], 0.5, 0, 5)
    c["margin_m"] = _f(c["margin_m"], 0.7, 0.2, 5)
    c["dynamic_routing"] = bool(c.get("dynamic_routing", True))
    if not c["enabled"]:
        return c
    stations = m["stations"]
    ids = [s["id"] for s in stations]
    loop = [p for p in (_pt(v) for v in c.get("loop") or []) if p is not None]
    # supprime les sommets confondus
    clean: list[P] = []
    for p in loop:
        if not clean or math.dist(clean[-1], p) > 1e-6:
            clean.append(p)
    if len(clean) > 1 and math.dist(clean[0], clean[-1]) < 1e-6:
        clean.pop()
    if len(clean) < 3:
        clean = auto_loop(stations, c["margin_m"])
        c["auto_loop"] = True
    else:
        c["auto_loop"] = False
    c["loop"] = [[round(x, 3), round(y, 3)] for x, y in clean]
    pts, segs = flatten(clean, c["corner_radius_m"])
    cum = cumulative(pts)
    L = cum[-1]
    if L < 1.0:
        raise ValueError("Rail du convoyeur trop court (< 1 m).")
    c["pts"] = [[round(x, 3), round(y, 3)] for x, y in pts]
    c["cum"] = [round(v, 4) for v in cum]
    c["length_m"] = round(L, 2)
    c["segments"] = segs
    spurs = {}
    for s in stations:
        sv, q, d = project(pts, cum, (s["qx"], s["qy"]))
        spurs[s["id"]] = {"s": round(sv, 3), "pt": [round(q[0], 3), round(q[1], 3)], "to": [s["qx"], s["qy"]],
                          "len": round(d, 3)}
    c["spurs"] = spurs
    src, snk = m["source"], m["sink"]
    lp = _pt(c.get("load")) or (src["x"], src["y"])
    up = _pt(c.get("unload")) or (snk["x"], snk["y"])
    sl, lq, _ = project(pts, cum, lp)
    su, uq, _ = project(pts, cum, up)
    c["s_load"], c["load_pt"] = round(sl, 3), [round(lq[0], 3), round(lq[1], 3)]
    c["s_unload"], c["unload_pt"] = round(su, 3), [round(uq[0], 3), round(uq[1], 3)]
    c["capacity"] = max(1, int(L / c["pitch_m"]))
    n = int(_f(c.get("carriers"), 0, 0, MAX_CARRIERS))
    if n <= 0:     # automatique : tampon de chaque dérivation + 1 cintre en route par poste + chargement
        n = len(stations) * (c["station_wip"] + 1) + 4
    c["carriers"] = int(min(n, MAX_CARRIERS))
    # pilotage du chargement : on ne lance un cintre que si la boucle porte moins de `max_on_rail` cintres
    # en circulation (0 = automatique : 2 par poste) → peu de tours à vide derrière le goulot
    mr = int(_f(c.get("max_on_rail"), 0, 0, MAX_CARRIERS))
    c["max_on_rail"] = mr if mr > 0 else max(4, 2 * len(stations))
    alt: dict[str, list[str]] = {}
    for k, v in (c.get("alternates") or {}).items():
        if str(k) in ids:
            alt[str(k)] = [str(x) for x in (v or []) if str(x) in ids and str(x) != str(k)][:10]
    # postes qui portent exactement les mêmes opérations (opération partagée par l'équilibrage) :
    # interchangeables d'office
    by_ops: dict[tuple, list[str]] = {}
    for s in stations:
        if s.get("operations"):
            by_ops.setdefault(tuple(sorted(s["operations"])), []).append(s["id"])
    for grp in by_ops.values():
        if len(grp) > 1:
            for sid in grp:
                alt[sid] = list(dict.fromkeys((alt.get(sid) or []) + [x for x in grp if x != sid]))
    # compétences : un poste peut reprendre l'étape d'un autre si l'une de ses opératrices a toutes les
    # compétences requises et s'il a les machines de cette étape
    op_sk = {o["id"]: set(o.get("skills") or []) for o in m.get("operators") or []}
    for s in stations:
        need, mt = set(s.get("skills") or []), set(s.get("machine_types") or [])
        if not need:
            continue
        for o in stations:
            if o["id"] == s["id"] or not o["operators"] or not mt or not mt <= set(o.get("machine_types") or []):
                continue
            if any(need <= op_sk.get(w, set()) for w in o["operators"]):
                alt[s["id"]] = list(dict.fromkeys((alt.get(s["id"]) or []) + [o["id"]]))
    c["alternates"] = alt
    return c


def view(c: dict) -> dict:
    """Ce que l'animation doit connaître du convoyeur."""
    keep = ("enabled", "name", "speed_m_per_min", "switch_sec", "carriers", "carrier_capacity", "station_wip",
            "load_min", "unload_min", "pitch_m", "height_m", "corner_radius_m", "margin_m", "dynamic_routing", "max_on_rail", "loop",
            "pts", "cum", "length_m", "segments", "spurs", "s_load", "s_unload", "load_pt", "unload_pt", "capacity",
            "alternates", "auto_loop")
    return {k: c.get(k) for k in keep if k in c}
