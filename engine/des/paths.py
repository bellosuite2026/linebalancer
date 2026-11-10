"""Graphe de déplacement : chemins à pied entre les points du modèle (postes, source, sortie).

Avec un plan d'atelier : grille de passage de engine.workshop (murs, poteaux et machines contournés,
portes ouvertes) et plus courts chemins (Dijkstra multi-cibles depuis chaque point). Sans plan :
ligne droite (implantation ligne / U du jumeau).
"""
from __future__ import annotations

import heapq
import math
from typing import Iterable, Optional

from engine.workshop import FREE, WorkshopGrid, _simplify


def _straight(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, list[list[float]]]:
    return round(math.dist(a, b), 2), [[round(a[0], 2), round(a[1], 2)], [round(b[0], 2), round(b[1], 2)]]


class PathTable:
    """Distances (m) et polylignes entre points nommés ; symétrique (chemin inversé au retour)."""

    def __init__(self, points: dict[str, tuple[float, float]]):
        self.points = dict(points)
        self.table: dict[tuple[str, str], tuple[float, list[list[float]]]] = {}

    def set(self, a: str, b: str, meters: float, pts: list[list[float]]) -> None:
        key = (a, b) if a <= b else (b, a)
        if key != (a, b):
            pts = list(reversed(pts))
        self.table[key] = (round(float(meters), 2), [[round(p[0], 2), round(p[1], 2)] for p in pts])

    def get(self, a: str, b: str) -> tuple[float, list[list[float]]]:
        if a == b:
            p = self.points.get(a, (0.0, 0.0))
            return 0.0, [[p[0], p[1]]]
        key = (a, b) if a <= b else (b, a)
        if key not in self.table:
            m, pts = _straight(self.points.get(a, (0, 0)), self.points.get(b, (0, 0)))
            self.table[key] = (m, pts)
        m, pts = self.table[key]
        return (m, pts) if key == (a, b) else (m, list(reversed(pts)))

    def to_json(self) -> dict:
        return {f"{a}|{b}": {"m": m, "pts": pts} for (a, b), (m, pts) in self.table.items()}

    @classmethod
    def from_json(cls, points: dict, data: Optional[dict]) -> "PathTable":
        t = cls({k: (float(v[0]), float(v[1])) for k, v in points.items()})
        for k, v in (data or {}).items():
            if "|" in k and isinstance(v, dict) and v.get("pts"):
                a, b = k.split("|", 1)
                t.set(a, b, float(v.get("m") or 0), v["pts"])
        return t


def grid_paths(grid: WorkshopGrid, points: dict[str, tuple[float, float]],
               pairs: Iterable[tuple[str, str]], allow: Optional[dict[str, list[str]]] = None,
               max_sources: int = 200) -> PathTable:
    """Plus courts chemins sur la grille pour les paires demandées : un Dijkstra par point de départ,
    arrêté quand toutes ses cibles sont atteintes. `allow` = machines traversables par point
    (la machine du poste lui-même, pour sortir du recoin)."""
    table = PathTable(points)
    need: dict[str, set[str]] = {}
    for a, b in pairs:
        if a == b or a not in points or b not in points:
            continue
        x, y = (a, b) if a <= b else (b, a)
        need.setdefault(x, set()).add(y)
    allow = allow or {}
    nx, ny, c, own = grid.nx, grid.ny, grid.cell, grid.owner
    idx_of = {mid: i for i, mid in enumerate(grid.ids)}
    S2 = math.sqrt(2)
    for n_src, (src, targets) in enumerate(need.items()):
        if n_src >= max_sources:
            break
        allowed = {idx_of[m] for t in [src, *targets] for m in allow.get(t, []) if m in idx_of}
        si, sj = grid.cell_of(*points[src])
        sk = sj * nx + si
        goal_cells = {}
        for t in targets:
            gi, gj = grid.cell_of(*points[t])
            goal_cells.setdefault(gj * nx + gi, []).append(t)
        remaining = set(goal_cells)

        def ok(i, j):
            if i < 0 or j < 0 or i >= nx or j >= ny:
                return False
            k = j * nx + i
            o = own[k]
            return o == FREE or o in allowed or k in goal_cells or k == sk

        dist = {sk: 0.0}
        prev: dict[int, int] = {}
        heap = [(0.0, sk)]
        while heap and remaining:
            dk, k = heapq.heappop(heap)
            if dk > dist.get(k, 1e18):
                continue
            remaining.discard(k)
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
                    heapq.heappush(heap, (nd, nk))
        for gk, names in goal_cells.items():
            for t in names:
                a, b = points[src], points[t]
                if gk not in dist:
                    # aucun passage : équerre (signalée par le jumeau) ; chemin direct pour l'animation
                    m = abs(a[0] - b[0]) + abs(a[1] - b[1])
                    table.set(src, t, m, [[a[0], a[1]], [b[0], a[1]], [b[0], b[1]]])
                    continue
                cells = [gk]
                while cells[-1] != sk:
                    cells.append(prev[cells[-1]])
                cells.reverse()
                pts = [[(k % nx + 0.5) * c, (k // nx + 0.5) * c] for k in cells]
                pts[0], pts[-1] = [a[0], a[1]], [b[0], b[1]]
                pts = _simplify(pts)
                m = sum(math.dist(p, q) for p, q in zip(pts, pts[1:]))
                table.set(src, t, max(m, math.dist(a, b)), pts)
    return table
