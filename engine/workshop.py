"""Plan d'atelier (cartographie) — v2.4.

Géométrie pure, sans effet sur les solveurs d'équilibrage :

- MACHINE_CATALOG       : bibliothèque de machines et encombrements par défaut (mètres, modifiables).
- machine_corners / operator_point : géométrie d'une machine posée (centre, rotation, côté opératrice).
- WorkshopGrid          : grille de passage (murs, poteaux, machines = obstacles ; portes = passages).
- auto_assign           : place les stations d'un calcul sur les machines réelles du plan
                          (poste WS lié, puis type de machine, au plus près de la station précédente).
- plan_layout           : implantation de simulation (positions + distances par les allées) et analyse du flux
                          (transferts, retours en arrière, croisements, cellule en U).
- inventory_workstations: postes (WS) à partir des machines du plan, pour l'éditeur de gamme / le moteur.
- derived_travel        : temps de déplacement par machine supplémentaire (option `machine_change_time`).

Unités : mètres. Repère du plan : x vers la droite, y vers le bas (comme l'écran), rotation en degrés
dans le sens horaire. Une machine est décrite par son centre (x, y), sa largeur w (le long de la table),
sa profondeur d, sa rotation rot et le côté de l'opératrice (front/back/left/right).
"""
from __future__ import annotations

import heapq
import math
import unicodedata
from typing import Iterable, Optional

WALK_SPEED_M_PER_MIN = 50.0     # même valeur que engine.simulation (≈ 0,8 m/s avec un paquet)
OPERATOR_GAP_M = 0.45           # centre de l'opératrice à partir du bord de la table
VIRTUAL_SPACING_M = 1.6

# type -> libellé, largeur, profondeur, type machine de la gamme ("" = pas un poste de travail)
MACHINE_CATALOG: dict[str, dict] = {
    "piqueuse_plate":        {"label": "Piqueuse plate", "w": 1.20, "d": 0.60, "machine_type": "piqueuse_plate"},
    "surjeteuse_3_fils":     {"label": "Surjeteuse 3 fils", "w": 1.05, "d": 0.55, "machine_type": "surjeteuse_3_fils"},
    "surjeteuse_4_fils":     {"label": "Surjeteuse 4 fils", "w": 1.05, "d": 0.55, "machine_type": "surjeteuse_4_fils"},
    "surjeteuse_5_fils":     {"label": "Surjeteuse 5 fils", "w": 1.10, "d": 0.55, "machine_type": "surjeteuse_5_fils"},
    "recouvreuse":           {"label": "Recouvreuse", "w": 1.10, "d": 0.60, "machine_type": "recouvreuse"},
    "chainette":             {"label": "Chaînette", "w": 1.20, "d": 0.60, "machine_type": "chainette"},
    "piqueuse_2_aiguilles":  {"label": "Double aiguille", "w": 1.20, "d": 0.60, "machine_type": "piqueuse_2_aiguilles"},
    "piqueuse_boutonniere":  {"label": "Boutonnière", "w": 1.20, "d": 0.70, "machine_type": "piqueuse_boutonniere"},
    "piqueuse_bouton":       {"label": "Pose-boutons", "w": 1.10, "d": 0.65, "machine_type": "piqueuse_bouton"},
    "bride":                 {"label": "Bartack / brides", "w": 1.10, "d": 0.65, "machine_type": "bride"},
    "table_coupe":           {"label": "Table de coupe", "w": 6.00, "d": 1.80, "machine_type": "table_coupe"},
    "table_travail":         {"label": "Table de préparation", "w": 1.60, "d": 0.80, "machine_type": "table_travail"},
    "table_repassage":       {"label": "Fer / table à repasser", "w": 1.40, "d": 0.70, "machine_type": "table_repassage"},
    "presse_thermocollage":  {"label": "Thermocolleuse", "w": 2.20, "d": 1.00, "machine_type": "presse_thermocollage"},
    "table_controle":        {"label": "Poste de contrôle", "w": 1.50, "d": 0.80, "machine_type": "table_controle"},
    "chariot":               {"label": "Chariot / rack d'encours", "w": 1.00, "d": 0.60, "machine_type": ""},
}

ZONES = {
    "coupe": "Coupe", "preparation": "Préparation", "montage": "Montage", "finition": "Finition",
    "repassage": "Repassage", "controle": "Contrôle", "stock": "Stock / magasin", "expedition": "Expédition",
}

# Familles interchangeables quand le type exact manque (repli, signalé dans les notes).
_FAMILIES = {
    "surjeteuse": {"surjeteuse_3_fils", "surjeteuse_4_fils", "surjeteuse_5_fils", "surjeteuse"},
    "repassage": {"table_repassage", "fer_repassage", "presse_vapeur", "repassage"},
    "table": {"table_travail", "table_controle", "manuel", "table", "table_preparation"},
    "piqueuse": {"piqueuse_plate", "piqueuse", "piqueuse_1_aiguille", "plate"},
    "thermo": {"presse_thermocollage", "thermocolleuse", "thermocollage"},
    "bouton": {"piqueuse_bouton", "pose_bouton", "pose_boutons", "boutons"},
    "boutonniere": {"piqueuse_boutonniere", "boutonniere"},
    "bride": {"bride", "bartack", "brides"},
    "double": {"piqueuse_2_aiguilles", "double_aiguille", "2_aiguilles"},
}


def norm_type(s: Optional[str]) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower().strip()
    out = "".join(c if c.isalnum() else "_" for c in s)
    while "__" in out:
        out = out.replace("__", "_")
    return out.strip("_")


def family(t: str) -> str:
    t = norm_type(t)
    for f, members in _FAMILIES.items():
        if t in members:
            return f
    return t


def machine_type_of(m: dict) -> str:
    """Type machine de la gamme pour une machine du plan ("" pour un chariot)."""
    if "machine_type" in m and m.get("machine_type") is not None:
        return norm_type(m["machine_type"])
    return norm_type((MACHINE_CATALOG.get(m.get("type", "")) or {"machine_type": m.get("type", "")})["machine_type"])


def _num(v, default=0.0) -> float:
    try:
        f = float(v)
        return f if math.isfinite(f) else float(default)
    except (TypeError, ValueError):
        return float(default)


def machines(plan: dict) -> list[dict]:
    return [e for e in plan.get("elements") or [] if isinstance(e, dict) and e.get("kind") == "machine"]


def usable(m: dict) -> bool:
    """Machine en service et poste de travail (pas un chariot)."""
    return (m.get("status") or "service") == "service" and bool(machine_type_of(m))


# --------------------------------------------------------------------------- géométrie
def _rot(lx: float, ly: float, deg: float) -> tuple[float, float]:
    a = math.radians(deg)
    return lx * math.cos(a) - ly * math.sin(a), lx * math.sin(a) + ly * math.cos(a)


def _dims(e: dict) -> tuple[float, float]:
    cat = MACHINE_CATALOG.get(e.get("type", ""), {})
    return max(0.05, _num(e.get("w"), cat.get("w", 1.2))), max(0.05, _num(e.get("d"), cat.get("d", 0.6)))


def machine_corners(m: dict) -> list[tuple[float, float]]:
    w, d = _dims(m)
    cx, cy, r = _num(m.get("x")), _num(m.get("y")), _num(m.get("rot"))
    out = []
    for lx, ly in ((-w / 2, -d / 2), (w / 2, -d / 2), (w / 2, d / 2), (-w / 2, d / 2)):
        dx, dy = _rot(lx, ly, r)
        out.append((cx + dx, cy + dy))
    return out


def operator_point(m: dict) -> tuple[float, float]:
    """Position de l'opératrice : devant la table (côté choisi), à 45 cm du bord."""
    w, d = _dims(m)
    side = m.get("operator") or "front"
    lx, ly = {"front": (0, d / 2 + OPERATOR_GAP_M), "back": (0, -d / 2 - OPERATOR_GAP_M),
              "left": (-w / 2 - OPERATOR_GAP_M, 0), "right": (w / 2 + OPERATOR_GAP_M, 0)}.get(side, (0, d / 2 + OPERATOR_GAP_M))
    dx, dy = _rot(lx, ly, _num(m.get("rot")))
    return round(_num(m.get("x")) + dx, 3), round(_num(m.get("y")) + dy, 3)


def _inside_rect(px: float, py: float, cx: float, cy: float, w: float, d: float, rot: float) -> bool:
    lx, ly = _rot(px - cx, py - cy, -rot)
    return abs(lx) <= w / 2 and abs(ly) <= d / 2


def _seg_dist(px, py, x1, y1, x2, y2) -> float:
    vx, vy = x2 - x1, y2 - y1
    L2 = vx * vx + vy * vy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - x1) * vx + (py - y1) * vy) / L2))
    return math.hypot(px - (x1 + t * vx), py - (y1 + t * vy))


# --------------------------------------------------------------------------- grille de passage
FREE, BLOCKED = -1, -2


class WorkshopGrid:
    """Grille de passage : murs et poteaux bloquent, portes ouvrent les murs, chaque machine occupe
    ses cellules (traversables seulement par les parcours qui partent ou arrivent à cette machine)."""

    def __init__(self, plan: dict, cell: Optional[float] = None):
        self.W = max(1.0, _num(plan.get("width_m"), 30))
        self.L = max(1.0, _num(plan.get("length_m"), 20))
        self.cell = cell or max(0.2, round(math.sqrt(self.W * self.L / 20000), 2))
        self.nx, self.ny = int(math.ceil(self.W / self.cell)), int(math.ceil(self.L / self.cell))
        self.owner = [FREE] * (self.nx * self.ny)
        self.ids: list[str] = []
        els = [e for e in plan.get("elements") or [] if isinstance(e, dict)]
        c = self.cell
        for e in els:
            k = e.get("kind")
            if k == "wall":
                x1, y1, x2, y2 = (_num(e.get(n)) for n in ("x1", "y1", "x2", "y2"))
                half = max(0.05, _num(e.get("thickness"), 0.2)) / 2 + c * 0.5
                self._mark_box(min(x1, x2) - half, min(y1, y2) - half, max(x1, x2) + half, max(y1, y2) + half,
                               lambda px, py: _seg_dist(px, py, x1, y1, x2, y2) <= half, BLOCKED)
            elif k == "pillar":
                x, y = _num(e.get("x")), _num(e.get("y"))
                w, d = max(0.05, _num(e.get("w"), 0.4)), max(0.05, _num(e.get("d"), 0.4))
                self._mark_box(x - w / 2, y - d / 2, x + w / 2, y + d / 2, lambda px, py: True, BLOCKED)
        for e in els:   # portes : rouvrent le mur sur leur largeur
            if e.get("kind") == "door":
                x, y, r = _num(e.get("x")), _num(e.get("y")), _num(e.get("rot"))
                w = max(0.4, _num(e.get("width"), 1.0))
                R = max(w, 0.8)
                self._mark_box(x - R, y - R, x + R, y + R,
                               lambda px, py: _inside_rect(px, py, x, y, w, 0.6 + c, r), FREE, force=True)
        for e in els:
            if e.get("kind") == "machine":
                idx = len(self.ids)
                self.ids.append(str(e.get("id")))
                w, d = _dims(e)
                x, y, r = _num(e.get("x")), _num(e.get("y")), _num(e.get("rot"))
                R = math.hypot(w, d) / 2
                self._mark_box(x - R, y - R, x + R, y + R,
                               lambda px, py: _inside_rect(px, py, x, y, w, d, r), idx)

    def _mark_box(self, x0, y0, x1, y1, test, value, force=False):
        c = self.cell
        i0, i1 = max(0, int(x0 / c)), min(self.nx - 1, int(x1 / c))
        j0, j1 = max(0, int(y0 / c)), min(self.ny - 1, int(y1 / c))
        for j in range(j0, j1 + 1):
            py = (j + 0.5) * c
            for i in range(i0, i1 + 1):
                px = (i + 0.5) * c
                if test(px, py):
                    k = j * self.nx + i
                    if force or self.owner[k] != BLOCKED:
                        self.owner[k] = value

    def cell_of(self, x: float, y: float) -> tuple[int, int]:
        return (min(self.nx - 1, max(0, int(x / self.cell))), min(self.ny - 1, max(0, int(y / self.cell))))

    def route(self, a: tuple[float, float], b: tuple[float, float],
              allow: Iterable[str] = ()) -> tuple[Optional[float], list[list[float]]]:
        """Plus court chemin (A*, 8 directions sans couper les angles) ; None si aucun passage."""
        allowed = {i for i, mid in enumerate(self.ids) if mid in set(allow)}
        nx, ny, c, own = self.nx, self.ny, self.cell, self.owner
        s, g = self.cell_of(*a), self.cell_of(*b)
        sk, gk = s[1] * nx + s[0], g[1] * nx + g[0]

        def ok(i, j):
            if i < 0 or j < 0 or i >= nx or j >= ny:
                return False
            o = own[j * nx + i]
            return o == FREE or o in allowed or (j * nx + i) in (sk, gk)

        dist = {sk: 0.0}
        prev: dict[int, int] = {}
        heap = [(0.0, sk)]
        S2 = math.sqrt(2)
        while heap:
            f, k = heapq.heappop(heap)
            if k == gk:
                break
            dk = dist[k]
            i, j = k % nx, k // nx
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                ni, nj = i + di, j + dj
                if not ok(ni, nj):
                    continue
                if di and dj and not (ok(i + di, j) and ok(i, j + dj)):
                    continue
                nk = nj * nx + ni
                nd = dk + (S2 if di and dj else 1.0)
                if nd < dist.get(nk, 1e18):
                    dist[nk] = nd
                    prev[nk] = k
                    heapq.heappush(heap, (nd + math.hypot(ni - g[0], nj - g[1]), nk))
        if gk not in dist:
            return None, []
        cells = [gk]
        while cells[-1] != sk:
            cells.append(prev[cells[-1]])
        cells.reverse()
        pts = [[round((k % nx + 0.5) * c, 2), round((k // nx + 0.5) * c, 2)] for k in cells]
        pts[0], pts[-1] = [round(a[0], 2), round(a[1], 2)], [round(b[0], 2), round(b[1], 2)]
        pts = _simplify(pts)
        meters = sum(math.hypot(p[0] - q[0], p[1] - q[1]) for p, q in zip(pts, pts[1:]))
        return round(meters, 2), pts


def _simplify(pts: list[list[float]]) -> list[list[float]]:
    if len(pts) <= 2:
        return pts
    out = [pts[0]]
    for k in range(1, len(pts) - 1):
        a, b, c = out[-1], pts[k], pts[k + 1]
        cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        if abs(cross) > 1e-6:
            out.append(b)
    out.append(pts[-1])
    return out


# --------------------------------------------------------------------------- stations -> machines
def station_types(st: dict) -> list[str]:
    """Types de machines d'une station (un par machine), d'après le calcul ou ses opérations."""
    types = [norm_type(t) for t in st.get("machine_types") or [] if norm_type(t) and norm_type(t) != "manuel"]
    if not types:
        seen: list[str] = []
        for op in st.get("operations") or []:
            t = norm_type(op.get("machine_type"))
            if t and t != "manuel" and t not in seen:
                seen.append(t)
        types = seen
    return types


def _label_num(m: dict) -> Optional[int]:
    digits = "".join(ch if ch.isdigit() else " " for ch in str(m.get("label") or "")).split()
    return int(digits[-1]) if digits else None


def auto_assign(stations: list[dict], plan: dict, fixed: Optional[dict] = None, strategy: str = "numero") -> dict:
    """Associe chaque station à des machines du plan (en service).

    Ordre : association manuelle conservée (fixed) → machine liée au poste WS de la station →
    même type de machine → famille voisine (signalée) → table libre pour une station manuelle.
    Parmi les candidates : strategy « numero » = plus petit n° de machine supérieur au précédent
    (les machines sont numérotées dans le sens du flux), puis la plus proche ; « proche » = la plus
    proche de la station précédente. Une station sans machine reste « virtuelle »."""
    ms = {str(m.get("id")): m for m in machines(plan)}
    avail = {mid for mid, m in ms.items() if usable(m)}
    taken: set[str] = set()
    out: dict[str, list[str]] = {}
    notes: list[str] = []
    missing: list[dict] = []
    fixed = {str(k): [str(x) for x in (v or [])] for k, v in (fixed or {}).items()}
    last_pt: Optional[tuple[float, float]] = None

    last_num: list[int] = [-1]

    def pick(cands: set[str]) -> Optional[str]:
        cands = cands - taken
        if not cands:
            return None
        ref = last_pt

        def dist(k: str) -> float:
            if ref is None:
                return _num(ms[k].get("x")) + _num(ms[k].get("y"))
            return math.dist(ref, operator_point(ms[k]))
        if strategy == "numero":
            def key(k: str):
                n = _label_num(ms[k])
                if n is None:
                    return (2, 0, dist(k), k)
                return (0 if n > last_num[0] else 1, n if n > last_num[0] else -n, dist(k), k)
            return min(cands, key=key)
        return min(cands, key=lambda k: (dist(k), k))

    for st in stations:
        sid = str(st["station"])
        chosen: list[str] = []
        if sid in fixed:
            chosen = [m for m in fixed[sid] if m in ms and m not in taken]
            if fixed[sid] and not chosen:
                notes.append(f"Station {sid} : machine choisie introuvable ou déjà prise, association automatique.")
        if not chosen and not (sid in fixed and fixed[sid] == []):
            ws_ids = {str(w) for w in st.get("workstations") or []}
            types = station_types(st)
            operators = max(1, int(st.get("operators") or 1))
            want = types * operators if types else ["__table"] * operators
            for t in want:
                cand = None
                if ws_ids:
                    linked = {k for k in avail if str(ms[k].get("ws_id") or "") in ws_ids
                              and (t == "__table" or machine_type_of(ms[k]) == t)}
                    cand = pick(linked)
                if cand is None and t != "__table":
                    cand = pick({k for k in avail if machine_type_of(ms[k]) == t})
                    if cand is None:
                        cand = pick({k for k in avail if family(machine_type_of(ms[k])) == family(t)})
                        if cand is not None:
                            notes.append(f"Station {sid} : pas de {t} libre, {machine_type_of(ms[cand])} utilisée "
                                         f"({ms[cand].get('label') or cand}).")
                if cand is None and t == "__table":
                    cand = pick({k for k in avail if family(machine_type_of(ms[k])) == "table"})
                if cand is None:
                    if t != "__table":
                        missing.append({"station": int(st["station"]), "type": t})
                    continue
                chosen.append(cand)
                taken.add(cand)
        else:
            taken.update(chosen)
        out[sid] = chosen
        if chosen:
            last_pt = operator_point(ms[chosen[0]])
            nums = [n for n in (_label_num(ms[c]) for c in chosen) if n is not None]
            if nums:
                last_num[0] = max(nums)
    for m in missing:
        notes.append(f"Station {m['station']} : aucune machine « {m['type']} » en service libre sur le plan.")
    unused = sorted(k for k in avail if k not in taken)
    return {"assignment": out, "missing": missing, "unused": unused, "notes": notes}


# --------------------------------------------------------------------------- implantation + flux
def plan_layout(stations: list[dict], plan: dict, assignment: dict) -> dict:
    """Implantation de simulation sur le plan : positions (opératrice de la 1re machine de chaque station),
    distances par les allées (contournement des murs, poteaux et machines) et analyse du flux."""
    ms = {str(m.get("id")): m for m in machines(plan)}
    order = [int(s["station"]) for s in stations]
    pos: dict[int, tuple[float, float]] = {}
    first: dict[int, Optional[str]] = {}
    virtual: list[int] = []
    for sid in order:
        mids = [m for m in assignment.get(str(sid)) or [] if m in ms]
        first[sid] = mids[0] if mids else None
        if mids:
            pos[sid] = operator_point(ms[mids[0]])
    # stations sans machine : posées à côté de la précédente (virtuelles)
    for k, sid in enumerate(order):
        if sid in pos:
            continue
        virtual.append(sid)
        ref = next((pos[o] for o in reversed(order[:k]) if o in pos), None)
        if ref is None:
            ref = next((pos[o] for o in order if o in pos), (1.0, 1.0))
        pos[sid] = (round(ref[0] + VIRTUAL_SPACING_M, 2), ref[1])

    grid = WorkshopGrid(plan)
    pairs = list(zip(order, order[1:]))
    by_worker: dict[str, list[int]] = {}
    for st in stations:
        for w in st.get("worker_ids") or []:
            by_worker.setdefault(str(w), []).append(int(st["station"]))
    for sts in by_worker.values():
        for i, a in enumerate(sts):
            for b in sts[i + 1:]:
                if (a, b) not in pairs and (b, a) not in pairs:
                    pairs.append((a, b))
    distances: dict[str, float] = {}
    routes: dict[str, list] = {}
    blocked: list[list[int]] = []
    for a, b in pairs:
        straight = math.dist(pos[a], pos[b])
        allow = [m for m in (first[a], first[b]) if m]
        if a in virtual or b in virtual:
            d, path = None, []
        else:
            d, path = grid.route(pos[a], pos[b], allow)
        if d is None:
            if a not in virtual and b not in virtual:
                blocked.append([a, b])
            d = round(abs(pos[a][0] - pos[b][0]) + abs(pos[a][1] - pos[b][1]), 2)
            path = [[pos[a][0], pos[a][1]], [pos[b][0], pos[a][1]], [pos[b][0], pos[b][1]]]
        distances[f"{a}-{b}"] = round(max(d, straight), 2)
        routes[f"{a}-{b}"] = path
    flow = flow_analysis(order, pos, distances)
    if blocked:
        flow["warnings"].append({"kind": "no_path", "stations": blocked[0],
                                 "message": "Aucun passage trouvé entre "
                                            + ", ".join(f"{a} → {b}" for a, b in blocked[:5])
                                            + " (mur ou machines fermant l'allée) : distance en équerre utilisée."})
    if virtual:
        flow["warnings"].append({"kind": "virtual", "stations": virtual,
                                 "message": f"Stations sans machine sur le plan (placées à côté) : "
                                            f"{', '.join(map(str, virtual))}."})
    return {
        "kind": "u" if flow["u_cell"] else "free",
        "positions": {str(s): {"x": round(p[0], 2), "y": round(p[1], 2)} for s, p in pos.items()},
        "distances": distances, "routes": routes, "virtual": virtual, "flow": flow,
        "grid_cell_m": grid.cell,
    }


def flow_analysis(order: list[int], pos: dict[int, tuple[float, float]], distances: dict[str, float]) -> dict:
    transfers, warnings = [], []
    for a, b in zip(order, order[1:]):
        transfers.append({"from": a, "to": b, "meters": distances.get(f"{a}-{b}", round(math.dist(pos[a], pos[b]), 2)),
                          "straight": round(math.dist(pos[a], pos[b]), 2)})
    pts = [pos[s] for s in order]
    extent = max((math.dist(p, q) for p in pts for q in pts), default=0.0)
    u_cell = len(order) >= 4 and extent > 0 and math.dist(pts[0], pts[-1]) <= max(2.5, 0.35 * extent)
    backtracks = []
    if not u_cell and len(order) >= 2:
        ax = (pts[-1][0] - pts[0][0], pts[-1][1] - pts[0][1])
        n = math.hypot(*ax) or 1.0
        for a, b in zip(order, order[1:]):
            proj = ((pos[b][0] - pos[a][0]) * ax[0] + (pos[b][1] - pos[a][1]) * ax[1]) / n
            if proj < -0.5:
                backtracks.append({"from": a, "to": b, "meters": round(-proj, 2)})
                warnings.append({"kind": "backtrack", "stations": [a, b],
                                 "message": f"Retour en arrière {a} → {b} ({-proj:.1f} m contre le sens du flux)."})
    for t in transfers:
        if t["meters"] > 3.0:
            warnings.append({"kind": "long_transfer", "stations": [t["from"], t["to"]],
                             "message": f"Transfert {t['from']} → {t['to']} : {t['meters']:.1f} m par les allées."})
        if t["straight"] > 0.5 and t["meters"] > 1.8 * t["straight"] + 1:
            warnings.append({"kind": "detour", "stations": [t["from"], t["to"]],
                             "message": f"Détour {t['from']} → {t['to']} : {t['meters']:.1f} m pour "
                                        f"{t['straight']:.1f} m à vol d'oiseau."})
    total = round(sum(t["meters"] for t in transfers), 2)
    return {"transfers": transfers, "meters_per_bundle": total, "backtracks": backtracks,
            "u_cell": bool(u_cell), "entry_exit_m": round(math.dist(pts[0], pts[-1]), 2) if pts else 0,
            "extent_m": round(extent, 2), "warnings": warnings}


# --------------------------------------------------------------------------- données moteur
def zone_of(plan: dict, x: float, y: float) -> str:
    for e in plan.get("elements") or []:
        if isinstance(e, dict) and e.get("kind") == "zone":
            zx, zy, zw, zh = (_num(e.get(k)) for k in ("x", "y", "w", "h"))
            if zx <= x <= zx + zw and zy <= y <= zy + zh:
                return e.get("name") or ZONES.get(e.get("zone", ""), "")
    return ""


def inventory_workstations(plan: dict) -> list[dict]:
    """Postes (WS) du plan pour la gamme / le moteur : une machine = un poste (chariots exclus).
    Identifiant = poste lié (ws_id) sinon étiquette de la machine ; disponible = en service."""
    out, seen = [], set()
    for k, m in enumerate(machines(plan), 1):
        mt = machine_type_of(m)
        if not mt:
            continue
        base = str(m.get("ws_id") or m.get("label") or f"M{k:02d}").strip()[:40] or f"M{k:02d}"
        wid, n = base, 2
        while wid in seen:
            wid, n = f"{base}-{n}", n + 1
        seen.add(wid)
        cat = MACHINE_CATALOG.get(m.get("type", ""), {})
        name = " ".join(x for x in (str(m.get("label") or ""), cat.get("label", "")) if x).strip() or wid
        out.append({"id": wid, "name": name[:80], "machine_type": mt, "available": usable(m),
                    "max_workers": 1, "section": zone_of(plan, _num(m.get("x")), _num(m.get("y"))),
                    "machine_id": str(m.get("id"))})
    return out


def derived_travel(plan: dict, walk_speed: float = WALK_SPEED_M_PER_MIN) -> dict:
    """Temps de déplacement par machine supplémentaire tenue par une ouvrière : aller-retour vers la
    machine voisine la plus proche (médiane sur le plan), à `walk_speed` m/min."""
    pts = [operator_point(m) for m in machines(plan) if usable(m)]
    if len(pts) < 2:
        return {"neighbour_m": None, "minutes": 0.0}
    near = sorted(min(math.dist(p, q) for j, q in enumerate(pts) if j != i) for i, p in enumerate(pts))
    med = near[len(near) // 2]
    return {"neighbour_m": round(med, 2), "minutes": round(2 * med / max(1e-6, walk_speed), 3)}
