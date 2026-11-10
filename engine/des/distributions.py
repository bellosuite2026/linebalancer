"""Lois de variabilité des temps opératoires (relatives à la moyenne).

Une loi est un dict : {"kind": "constant" | "normal" | "triangular" | "lognormal", "cv": 0.10,
"low_pct": 80, "high_pct": 140}. `cv` = coefficient de variation (normale tronquée, lognormale) ;
`low_pct` / `high_pct` = bornes de la triangulaire en % de la moyenne (le mode est déduit pour que
la moyenne reste égale au temps standard).

Le temps d'un paquet de n pièces est la somme de n tirages ; au-delà de 20 pièces on tire directement
la somme (théorème central limite, mêmes moyenne et variance), ce qui garde la simulation rapide.
"""
from __future__ import annotations

import math
import random
from typing import Optional

KINDS = ("constant", "normal", "triangular", "lognormal")
TRUNC_LOW = 0.3   # normale tronquée : au moins 30 % de la moyenne par pièce


def normalize(d: Optional[dict]) -> dict:
    d = dict(d or {})
    kind = d.get("kind") if d.get("kind") in KINDS else "normal"
    cv = max(0.0, min(1.5, float(d.get("cv", 0.10) or 0.0)))
    lo = max(10.0, min(100.0, float(d.get("low_pct", 80) or 80)))
    hi = max(100.0, min(400.0, float(d.get("high_pct", 140) or 140)))
    if kind != "constant" and cv == 0 and kind != "triangular":
        kind = "constant"
    return {"kind": kind, "cv": cv, "low_pct": lo, "high_pct": hi}


def _tri_params(d: dict) -> tuple[float, float, float]:
    a, b = d["low_pct"] / 100.0, d["high_pct"] / 100.0
    c = 3.0 - a - b                    # mode tel que (a + b + c) / 3 = 1
    c = min(b, max(a, c))
    return a, c, b


def unit_variance(d: dict) -> float:
    """Variance d'une pièce pour une moyenne de 1."""
    k = d["kind"]
    if k == "constant":
        return 0.0
    if k == "triangular":
        a, c, b = _tri_params(d)
        return (a * a + b * b + c * c - a * b - a * c - b * c) / 18.0
    return d["cv"] ** 2


def sample_one(rng: random.Random, d: dict) -> float:
    k = d["kind"]
    if k == "constant":
        return 1.0
    if k == "normal":
        return max(TRUNC_LOW, rng.gauss(1.0, d["cv"]))
    if k == "triangular":
        a, c, b = _tri_params(d)
        return rng.triangular(a, b, c)
    # lognormale de moyenne 1 et de CV donné
    s2 = math.log(1.0 + d["cv"] ** 2)
    return rng.lognormvariate(-s2 / 2.0, math.sqrt(s2))


def sample_total(rng: random.Random, d: dict, mean_per_piece: float, n: int) -> float:
    """Durée totale de n pièces (minutes) pour un temps moyen par pièce donné."""
    if n <= 0 or mean_per_piece <= 0:
        return 0.0
    if d["kind"] == "constant":
        return mean_per_piece * n
    if n <= 20:
        return mean_per_piece * sum(sample_one(rng, d) for _ in range(n))
    sd = math.sqrt(unit_variance(d) * n)
    return mean_per_piece * max(TRUNC_LOW * n, rng.gauss(n, sd))
