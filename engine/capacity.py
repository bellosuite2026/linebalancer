"""
Analyse de capacité et aide à la décision pour lignes de confection.

Part d'une commande cliente (quantité, délai, heures disponibles) et répond
aux questions du décideur d'usine :

- Quel est le takt (cadence requise) ?
- Combien d'opérateurs faut-il théoriquement / avec efficacité cible ?
- La ligne équilibrée peut-elle livrer à temps ? (verdict OK / TENDU / INFAISABLE)
- Quelle sera la production journalière réaliste (efficacité ouvriers incluse) ?
- Quel est le coût main-d'œuvre par pièce (si coût minute fourni) ?
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Any

from engine.models import BalancingResult


# ── Commande de production ──────────────────────────────────────────

@dataclass
class ProductionTarget:
    """Une commande à produire : quantité, délai et rythme de travail."""
    order_quantity: int = 0          # Pièces à produire
    work_days: float = 1.0           # Jours de production disponibles
    hours_per_day: float = 8.0       # Heures productives par jour
    line_efficiency: float = 0.85    # Efficacité ligne attendue (0.75–0.90 en confection)

    @property
    def available_minutes(self) -> float:
        """Minutes productives disponibles sur tout le délai."""
        return self.work_days * self.hours_per_day * 60.0

    @property
    def daily_demand(self) -> float:
        """Pièces à produire par jour pour honorer la commande."""
        if self.work_days <= 0:
            return 0.0
        return self.order_quantity / self.work_days

    @property
    def takt_time(self) -> float:
        """Takt time (min/pièce) = temps disponible / quantité demandée."""
        if self.order_quantity <= 0:
            return 0.0
        return self.available_minutes / self.order_quantity

    @property
    def required_cycle_time(self) -> float:
        """Temps de cycle max à planifier = takt × efficacité attendue."""
        return self.takt_time * self.line_efficiency

    def validate(self) -> list[str]:
        errors = []
        if self.order_quantity <= 0:
            errors.append("Quantité commandée doit être > 0")
        if self.work_days <= 0:
            errors.append("Nombre de jours doit être > 0")
        if self.hours_per_day <= 0 or self.hours_per_day > 24:
            errors.append("Heures par jour invalide (0 < h ≤ 24)")
        if not (0.0 < self.line_efficiency <= 1.0):
            errors.append("Efficacité ligne doit être dans ]0, 1]")
        return errors


# ── Résultat d'analyse ──────────────────────────────────────────────

@dataclass
class CapacityAnalysis:
    """Verdict d'aide à la décision face à une ProductionTarget."""
    target: ProductionTarget
    feasible: bool = False
    verdict: str = "INCONNU"             # OK / TENDU / INFAISABLE

    # Besoin
    takt_time: float = 0.0               # min/pièce requis
    required_cycle_time: float = 0.0     # cycle max planifiable
    daily_demand: float = 0.0            # pièces/jour à livrer

    # Dimensionnement
    total_sam: float = 0.0               # Contenu main-d'œuvre nominal (min/pièce)
    theoretical_min_operators: float = 0.0   # SAM / takt (borne inf.)
    required_operators: int = 0          # ceil(SAM / (takt × eff)) — effectif conseillé
    assigned_operators: int = 0          # opérateurs actuellement affectés

    # Projection réaliste de la ligne équilibrée
    projected_cycle_time: float = 0.0    # Cycle réaliste (efficacité ouvriers appliquée)
    nominal_daily_output: float = 0.0    # pièces/jour au SAM nominal
    projected_daily_output: float = 0.0  # pièces/jour réaliste
    projected_order_days: float = 0.0    # Jours réels pour produire la commande
    daily_gap: float = 0.0               # Déficit pièces/jour (0 si OK)

    # Coût
    labor_cost_per_piece: float = 0.0    # 0 si coût minute non fourni

    messages: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = ["📦 ANALYSE DE CAPACITÉ (aide à la décision)"]
        t = self.target
        lines.append(
            f"  Commande: {t.order_quantity} pcs en {t.work_days:g} j "
            f"({t.hours_per_day:g} h/j, efficacité cible {t.line_efficiency:.0%})"
        )
        lines.append(f"  Takt requis:           {self.takt_time:.2f} min/pc "
                     f"({self.daily_demand:.0f} pcs/jour)")
        lines.append(f"  Cycle max planifiable: {self.required_cycle_time:.2f} min "
                     f"(takt × efficacité)")
        lines.append(f"  Opérateurs requis:     {self.required_operators} "
                     f"(borne théorique {self.theoretical_min_operators:.1f}, "
                     f"affectés: {self.assigned_operators})")
        lines.append(f"  Projection/jour:       {self.projected_daily_output:.0f} pcs "
                     f"(nominale {self.nominal_daily_output:.0f})")
        if self.daily_gap > 0:
            lines.append(f"  ⚠️ Déficit:            {self.daily_gap:.0f} pcs/jour "
                         f"(commande en {self.projected_order_days:.1f} j réels)")
        if self.labor_cost_per_piece > 0:
            lines.append(f"  Coût MO/pièce:         {self.labor_cost_per_piece:.3f}")
        icons = {"OK": "✅", "TENDU": "⚠️", "INFAISABLE": "❌"}
        lines.append(f"  {icons.get(self.verdict, '❓')} VERDICT: {self.verdict}")
        for m in self.messages:
            lines.append(f"    • {m}")
        return "\n".join(lines)


# ── Efficacité ouvriers appliquée (KPIs réalistes) ─────────────────

def worker_efficiency_map(result: BalancingResult) -> dict[str, float]:
    """Map worker_id -> coefficient d'efficacité."""
    return {w.id: (w.efficiency or 1.0) for w in result.problem.workers}


def compute_realistic_station_times(result: BalancingResult) -> dict[int, float]:
    """
    Temps de station réalistes : SAM / efficacité moyenne des opérateurs
    affectés (1.0 si aucun ouvrier affecté à la station).

    Les solveurs travaillent au SAM nominal ; cette couche post-solve
    reflète la performance réelle annoncée des opérateurs.
    """
    eff_map = worker_efficiency_map(result)
    realistic: dict[int, float] = {}
    for sd in result.station_details:
        total = sd.get("total_time", 0.0)
        ids = sd.get("worker_ids") or []
        effs = [eff_map.get(wid, 1.0) for wid in ids if eff_map.get(wid, 0) > 0]
        eff = sum(effs) / len(effs) if effs else 1.0
        realistic[sd["station"]] = round(total / eff, 3)
    return realistic


def mean_worker_efficiency(result: BalancingResult) -> float:
    """Efficacité moyenne des opérateurs disponibles (1.0 si aucun)."""
    effs = [w.efficiency for w in result.problem.workers if w.available and w.efficiency > 0]
    return sum(effs) / len(effs) if effs else 1.0


# ── Analyse principale ──────────────────────────────────────────────

def analyze_capacity(
    result: BalancingResult,
    target: ProductionTarget,
    labor_cost_per_minute: Optional[float] = None,
) -> CapacityAnalysis:
    """
    Évalue si la ligne équilibrée (result) peut honorer la commande (target).

    Hypothèses :
    - le débit est dicté par le poste goulot (temps station max ajusté par
      l'efficacité des opérateurs affectés),
    - pas de pertes hors efficacité ouvrier (pannes, aléas => voir simulation).
    """
    a = CapacityAnalysis(target=target)
    a.takt_time = target.takt_time
    a.required_cycle_time = target.required_cycle_time
    a.daily_demand = target.daily_demand
    a.total_sam = round(sum(op.duration for op in result.problem.operations), 3)

    if a.takt_time > 0 and a.total_sam > 0:
        a.theoretical_min_operators = a.total_sam / a.takt_time
        a.required_operators = math.ceil(
            a.total_sam / max(1e-9, target.required_cycle_time)
        )
    a.assigned_operators = sum(
        max(1, len(sd.get("worker_ids") or sd.get("workers") or []))
        for sd in result.station_details
    ) if result.station_details else 0

    if not result.success or not result.station_details or result.actual_cycle_time <= 0:
        a.verdict = "INFAISABLE"
        a.feasible = False
        a.messages.append("Équilibrage non résolu — impossible d'évaluer la capacité.")
        return a

    minutes_per_day = target.hours_per_day * 60.0

    # Nominal (SAM théorique)
    a.nominal_daily_output = minutes_per_day / result.actual_cycle_time

    # Réaliste (efficacité ouvriers appliquée)
    realistic = compute_realistic_station_times(result)
    a.projected_cycle_time = max(realistic.values(), default=result.actual_cycle_time)
    a.projected_daily_output = (
        minutes_per_day / a.projected_cycle_time if a.projected_cycle_time > 0 else 0.0
    )
    a.projected_order_days = (
        target.order_quantity / a.projected_daily_output
        if a.projected_daily_output > 0 else 0.0
    )
    a.daily_gap = max(0.0, a.daily_demand - a.projected_daily_output)

    # Coût main-d'œuvre
    if labor_cost_per_minute is not None and labor_cost_per_minute > 0:
        real_minutes = a.total_sam / max(0.3, mean_worker_efficiency(result))
        a.labor_cost_per_piece = round(real_minutes * labor_cost_per_minute, 4)

    # Verdict
    a.feasible = a.projected_daily_output >= a.daily_demand > 0
    if not a.feasible:
        a.verdict = "INFAISABLE"
        a.messages.append(
            f"Débit projeté {a.projected_daily_output:.0f} pcs/j < demande "
            f"{a.daily_demand:.0f} pcs/j."
        )
        if a.required_operators > a.assigned_operators > 0:
            a.messages.append(
                f"Passer de {a.assigned_operators} à {a.required_operators} opérateurs "
                f"(cycle cible {target.required_cycle_time:.2f} min)."
            )
        a.messages.append(
            "Sinon : réduire le contenu (SAM), ajouter des heures, ou négocier le délai."
        )
    else:
        margin = (a.projected_daily_output - a.daily_demand) / a.daily_demand
        if margin < 0.05:
            a.verdict = "TENDU"
            a.messages.append(
                f"Marge de débit faible ({margin:.0%}) — prévoir heures sup. ou "
                "une solution avec marge (cycle plus court)."
            )
        else:
            a.verdict = "OK"
            a.messages.append(
                f"Capacité suffisante ({a.projected_daily_output:.0f} pcs/j ≥ "
                f"{a.daily_demand:.0f} pcs/j)."
            )
    return a


def enrich_result(
    result: BalancingResult,
    target: Optional[ProductionTarget] = None,
    labor_cost_per_minute: Optional[float] = None,
    with_recommendations: bool = True,
) -> BalancingResult:
    """
    Enrichit un BalancingResult avec l'analyse de capacité et les
    recommandations (attache les objets au résultat pour la console,
    les exports et la GUI).
    """
    if result.success and result.station_details:
        result.realistic_station_times = compute_realistic_station_times(result)
    if target is not None:
        result.capacity = analyze_capacity(result, target, labor_cost_per_minute)
    if with_recommendations:
        from engine.recommendations import generate_recommendations
        result.recommendations = generate_recommendations(result, target)
    return result


def suggest_cycle_times(
    total_sam: float,
    max_op_duration: float,
    target: Optional[ProductionTarget] = None,
    n_points: int = 3,
) -> list[float]:
    """
    Propose des temps de cycle candidats pour une étude what-if :
    autour du cycle requis (commande) — sinon entre la durée de la plus
    longue opération et le SAM total.
    """
    if target is not None and target.takt_time > 0:
        base = target.required_cycle_time
        lo = max(max_op_duration * 1.001, base * 0.85)
        hi = base * 1.15
    else:
        lo = max_op_duration * 1.001
        hi = max(lo * 1.2, min(total_sam, lo * 2.0))
    if n_points <= 1 or hi <= lo:
        return [round((lo + hi) / 2, 3)]
    step = (hi - lo) / (n_points - 1)
    return [round(lo + i * step, 3) for i in range(n_points)]
