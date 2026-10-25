"""
Génération de rapports PDF pour l'équilibrage de ligne.

Utilise ReportLab pour produire des documents professionnels
avec tableaux, KPIs et répartitions par section/type machine.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

try:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm, cm
    from reportlab.platypus import (
        Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )

    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False


# ── Helpers ────────────────────────────────────────────────────────

def _safe(obj: Any, attr: str, default):
    """Lit un attribut (objet) ou une clé (dict) en toute sécurité."""
    if isinstance(obj, dict):
        return obj.get(attr, default)
    return getattr(obj, attr, default)


def _style() -> dict:
    styles = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "ReportTitle", parent=styles["Title"],
            fontSize=22, spaceAfter=6, textColor=colors.HexColor("#1a202c"),
        ),
        "subtitle": ParagraphStyle(
            "Subtitle", parent=styles["Normal"],
            fontSize=12, textColor=colors.HexColor("#4a5568"),
            spaceAfter=20,
        ),
        "h1": ParagraphStyle(
            "H1", parent=styles["Heading1"],
            fontSize=16, spaceBefore=12, spaceAfter=6,
            textColor=colors.HexColor("#2d3748"),
        ),
        "h2": ParagraphStyle(
            "H2", parent=styles["Heading2"],
            fontSize=13, spaceBefore=8, spaceAfter=4,
            textColor=colors.HexColor("#2d3748"),
        ),
        "body": ParagraphStyle(
            "Body", parent=styles["Normal"],
            fontSize=9, leading=13, spaceAfter=4,
        ),
        "small": ParagraphStyle(
            "Small", parent=styles["Normal"],
            fontSize=7.5, leading=10,
        ),
        "kpi_value": ParagraphStyle(
            "KPIValue", parent=styles["Normal"],
            fontSize=10, leading=14, alignment=TA_CENTER,
        ),
        "cell": ParagraphStyle(
            "Cell", parent=styles["Normal"],
            fontSize=8, leading=11,
        ),
        "header_cell": ParagraphStyle(
            "HeaderCell", parent=styles["Normal"],
            fontSize=8, leading=11, textColor=colors.white,
        ),
    }


def _format_table(header: list[str], rows: list[list], col_widths: list[float] | None = None) -> Table:
    """Crée un tableau stylisé."""
    if col_widths is None:
        col_widths = [180 / len(header) * cm] * len(header)

    s = _style()
    data = [
        [Paragraph(h, s["header_cell"]) for h in header],
        *[[Paragraph(str(c), s["cell"]) for c in row] for row in rows],
    ]
    t = Table(data, colWidths=col_widths, repeatRows=1)
    n_rows = len(data)
    cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2d3748")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#cbd5e1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#f8fafc"), colors.HexColor("#f1f5f9")]),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if n_rows > 1:
        cmds.append(("LINEBELOW", (0, 0), (-1, 0), 1, colors.HexColor("#1a202c")))
    t.setStyle(TableStyle(cmds))
    return t


def _kpi_card(value: str, label: str) -> Table:
    """Petite carte KPI individuelle."""
    s = _style()
    t = Table(
        [[Paragraph(value, s["kpi_value"])],
         [Paragraph(label, s["small"])]],
        colWidths=[130],
    )
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ebf4ff")),
        ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#f8fafc")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


# ── Report Builder ─────────────────────────────────────────────────

class BalanceReport:
    """Assemble un rapport PDF d'équilibrage de ligne."""

    def __init__(self, path: Path):
        self.path = path
        self._elements: list = []
        self._s = _style()
        self._story: list = []

    # ── Sections ──────────────────────────────────────────────────

    def _add_title_page(self, name: str):
        self._story.append(Spacer(1, 4 * cm))
        self._story.append(Paragraph(
            "Rapport d'équilibrage de ligne", self._s["title"]
        ))
        self._story.append(Paragraph(
            f"Projet: {name}", self._s["subtitle"]
        ))
        self._story.append(Spacer(1, 2 * cm))
        self._story.append(Paragraph(
            f"Généré le {__import__('datetime').datetime.now():%d/%m/%Y à %H:%M}",
            self._s["body"]
        ))

    def _add_kpi_section(self, kpis: list[tuple[str, str]]):
        self._story.append(Paragraph("Indicateurs clés", self._s["h1"]))
        row = []
        cards = []
        for value, label in kpis:
            cards.append(_kpi_card(value, label))
        # 3 KPIs par ligne
        for i in range(0, len(cards), 3):
            chunk = cards[i:i + 3]
            row = Table([chunk], colWidths=[130, 130, 130])
            row.setStyle(TableStyle([
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]))
            self._story.append(row)
        self._story.append(Spacer(1, 4))

    def _add_station_table(self, stations: list[dict]):
        self._story.append(Paragraph("Détail des postes de travail", self._s["h1"]))
        header = ["Poste", "Machine", "Temps cycle\n(min)", "Charge\n(%)",
                   "Nb\nOps", "Nb\nOuvr.", "Opérations"]
        rows = []
        for s in stations:
            rows.append([
                str(s.get("station", "")),
                s.get("workstation", s.get("workstation_name", "")),
                f'{s.get("total_time", s.get("total_time_min", 0)):.3f}',
                f'{s.get("load_pct", 0):.1f}',
                str(len(s.get("operations", []))),
                str(len(s.get("workers", []))),
                ", ".join(s.get("operations", [])[:3]),
            ])
        self._story.append(_format_table(header, rows))

    def _add_operations_table(self, ops: list[dict]):
        self._story.append(Paragraph("Détail des opérations", self._s["h1"]))
        header = ["OpID", "Nom", "Durée (min)", "Machine", "Section", "Poste"]
        rows = []
        for op in ops:
            rows.append([
                op.get("op_id", op.get("id", "")),
                op.get("name", ""),
                f'{op.get("duration_min", op.get("duration", 0)):.3f}',
                op.get("machine_type", ""),
                op.get("section", ""),
                str(op.get("station", op.get("assigned_station", ""))),
            ])
        self._story.append(_format_table(header, rows))

    def _add_distribution_section(self, by_attr: list[tuple[str, float, int]],
                                    title: str, attr_name: str):
        if not by_attr:
            return
        self._story.append(Paragraph(title, self._s["h1"]))
        total_time = sum(t for _, t, _ in by_attr)
        header = [attr_name, "Temps total (min)", "Nb Ops", "% Total"]
        rows = []
        for name, t, n in by_attr:
            pct = t / total_time * 100 if total_time > 0 else 0
            rows.append([name, f"{t:.2f}", str(n), f"{pct:.1f}%"])
        self._story.append(_format_table(header, rows))

    def _add_bottleneck_section(self, bottlenecks: list[dict], target_cycle: float):
        if not bottlenecks:
            return
        self._story.append(PageBreak())
        self._story.append(Paragraph("Analyse des goulets d'étranglement", self._s["h1"]))
        header = ["Poste", "Machine", "Tps cycle (min)", "Charge (%)",
                   "Dépasse. (min)", "Dépasse. (%)"]
        rows = []
        for s in bottlenecks:
            total = s.get("total_time", s.get("total_time_min", 0))
            over = total - target_cycle
            rows.append([
                str(s.get("station", "")),
                s.get("workstation", ""),
                f"{total:.3f}",
                f'{s.get("load_pct", 0):.1f}',
                f"{over:.3f}" if over > 0 else "-",
                f"{over / target_cycle * 100:.1f}%" if over > 0 else "-",
            ])
        self._story.append(_format_table(header, rows))

    def _add_recommendations(self, texts: list[str]):
        if not texts:
            return
        self._story.append(Spacer(1, 6))
        self._story.append(Paragraph("Recommandations", self._s["h2"]))
        for t in texts:
            self._story.append(Paragraph(f"• {t}", self._s["body"]))

    def _add_capacity_section(self, cap: Any):
        """Page « Aide à la décision » : faisabilité commande + projections."""
        self._story.append(PageBreak())
        self._story.append(Paragraph("Aide à la décision — commande & capacité", self._s["h1"]))
        t = _safe(cap, "target", None)
        if t is not None:
            self._story.append(Paragraph(
                f"Commande : {_safe(t, 'order_quantity', 0)} pièces en "
                f"{_safe(t, 'work_days', 0):g} jours "
                f"({_safe(t, 'hours_per_day', 0):g} h/j, "
                f"efficacité cible {_safe(t, 'line_efficiency', 0):.0%})",
                self._s["body"],
            ))
        verdict = _safe(cap, "verdict", "")
        icons = {"OK": "FAISABLE", "TENDU": "TENDU", "INFAISABLE": "INFAISABLE"}
        self._story.append(Spacer(1, 6))
        self._story.append(Paragraph(
            f"Verdict : {icons.get(verdict, verdict)}", self._s["h2"]
        ))
        kpis = [
            (f'{_safe(cap, "takt_time", 0):.2f}', "Takt (min/pc)"),
            (f'{_safe(cap, "daily_demand", 0):.0f}', "Demande (pcs/j)"),
            (f'{_safe(cap, "projected_daily_output", 0):.0f}', "Projection (pcs/j)"),
        ]
        cards = [_kpi_card(v, l) for v, l in kpis]
        self._story.append(Table([cards], colWidths=[130, 130, 130],
                          style=TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER")])))
        self._story.append(Spacer(1, 6))
        header = ["Indicateur", "Valeur"]
        rows = [
            ["Cycle max planifiable (min)", f'{_safe(cap, "required_cycle_time", 0):.2f}'],
            ["Cycle projeté réaliste (min)", f'{_safe(cap, "projected_cycle_time", 0):.2f}'],
            ["Opérateurs requis (estim.)", f'{_safe(cap, "required_operators", 0)}'],
            ["Opérateurs affectés", f'{_safe(cap, "assigned_operators", 0)}'],
            ["Déficit journalier (pcs)", f'{_safe(cap, "daily_gap", 0):.0f}'],
            ["Jours réels pour la commande", f'{_safe(cap, "projected_order_days", 0):.1f}'],
            ["Coût MO/pièce", f'{_safe(cap, "labor_cost_per_piece", 0):.3f}'],
        ]
        self._story.append(_format_table(header, rows,
                                         col_widths=[8 * cm, 4 * cm]))
        messages = _safe(cap, "messages", []) or []
        if messages:
            self._story.append(Spacer(1, 4))
            for m in messages:
                self._story.append(Paragraph(f"• {m}", self._s["body"]))

    def _add_simulation_section(self, sim_result: dict):
        self._story.append(PageBreak())
        self._story.append(Paragraph("Résultats de simulation", self._s["h1"]))
        kpis = [
            (f'{sim_result.get("throughput_per_hour", 0):.1f}', "Débit (pièces/h)"),
            (f'{sim_result.get("avg_cycle_time_min", 0):.2f}', "Tps cycle moy. (min)"),
            (f'{sim_result.get("avg_wip", 0):.1f}', "WIP moyen"),
        ]
        cards = [_kpi_card(v, l) for v, l in kpis]
        self._story.append(Table([cards], colWidths=[130, 130, 130],
                          style=TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER")])))
        self._story.append(Spacer(1, 6))
        station_stats = sim_result.get("station_stats", [])
        if station_stats:
            header = ["Poste", "Tps occup. moy.", "Tps occup. max",
                       "Taux occup. (%)", "Nb pièces"]
            rows = [
                [str(s.get("station_id", "")),
                 f'{s.get("avg_occupancy_time", 0):.3f}',
                 f'{s.get("max_occupancy_time", 0):.3f}',
                 f'{s.get("utilization_pct", 0):.1f}',
                 str(s.get("parts_processed", 0))]
                for s in station_stats
            ]
            self._story.append(_format_table(header, rows))

    # ── Build ─────────────────────────────────────────────────────

    def build(self):
        doc = SimpleDocTemplate(
            str(self.path), pagesize=A4,
            leftMargin=1.5 * cm, rightMargin=1.5 * cm,
            topMargin=1.5 * cm, bottomMargin=1.5 * cm,
        )
        doc.build(self._story)

    # ── API statique ──────────────────────────────────────────────

    @staticmethod
    def balance_result(result: Any, path: Path) -> None:
        """Génère un rapport PDF complet depuis un BalancingResult."""
        if not HAS_REPORTLAB:
            raise RuntimeError("reportlab n'est pas installé: pip install reportlab")

        r = BalanceReport(path)
        problem = result.problem if hasattr(result, "problem") else result.get("problem", {})
        name = problem.name if hasattr(problem, "name") else problem.get("name", "Sans nom")
        target_cycle = (
            problem.target_cycle_time if hasattr(problem, "target_cycle_time")
            else problem.get("target_cycle_time", 0)
        )

        stations = (
            result.station_details if hasattr(result, "station_details")
            else result.get("station_details", [])
        )
        ops = (
            problem.operations if hasattr(problem, "operations")
            else problem.get("operations", [])
        )
        assignments = (
            result.operation_assignments if hasattr(result, "operation_assignments")
            else result.get("operation_assignments", {})
        )
        def _get(obj, attr, default):
            return getattr(obj, attr, None) if not isinstance(obj, dict) else obj.get(attr, default)

        stations_used = str(_get(result, "stations_used", 0))
        actual_ct = _get(result, "actual_cycle_time", 0)
        eff = _get(result, "efficiency", 0)
        bd = _get(result, "balance_delay", 0)
        si = _get(result, "smoothness_index", 0)

        kpis = [
            (stations_used, "Postes utilisés"),
            (f"{actual_ct:.3f} min", "Temps de cycle réel"),
            (f"{eff:.1f}%", "Efficacité"),
            (f"{bd:.1f}%", "Balance delay"),
            (f"{si:.3f}", "Indice de lissage"),
            (f"{60 / target_cycle:.1f}" if target_cycle > 0 else "-", "Cadence (pièces/h)"),
        ]

        r._add_title_page(name)
        r._add_kpi_section(kpis)
        r._add_station_table(stations)
        r._add_operations_table([
            {
                "op_id": op.id if hasattr(op, "id") else op.get("id", ""),
                "name": op.name if hasattr(op, "name") else op.get("name", ""),
                "duration": op.duration if hasattr(op, "duration") else op.get("duration", 0),
                "duration_min": op.duration if hasattr(op, "duration") else op.get("duration", 0),
                "machine_type": op.machine_type if hasattr(op, "machine_type") else op.get("machine_type", ""),
                "section": op.section if hasattr(op, "section") else op.get("section", ""),
                "station": assignments.get(
                    op.id if hasattr(op, "id") else op.get("id", ""), ""
                ),
            }
            for op in ops
        ])

        # Répartition par section et type machine
        sections: dict[str, list] = {}
        mtypes: dict[str, list] = {}
        for op in ops:
            sec = op.section if hasattr(op, "section") else op.get("section", "général")
            mt = op.machine_type if hasattr(op, "machine_type") else op.get("machine_type", "inconnu")
            dur = op.duration if hasattr(op, "duration") else op.get("duration", 0)
            sections.setdefault(sec, []).append(dur)
            mtypes.setdefault(mt, []).append(dur)

        r._add_distribution_section(
            [(k, sum(v), len(v)) for k, v in sorted(sections.items())],
            "Répartition par section", "Section",
        )
        r._add_distribution_section(
            [(k, sum(v), len(v)) for k, v in sorted(mtypes.items())],
            "Répartition par type machine", "Type machine",
        )

        # Goulets (postes > temps de cycle)
        bottlenecks = [s for s in stations if
                       s.get("total_time", s.get("total_time_min", 0)) > target_cycle * 1.01]
        r._add_bottleneck_section(bottlenecks, target_cycle)

        # Page décisionnelle si l'analyse de capacité est attachée
        capacity = _get(result, "capacity", None)
        if capacity is not None:
            r._add_capacity_section(capacity)

        # Recommandations détaillées si disponibles, sinon génériques
        detailed = _get(result, "recommendations", None) or []
        if detailed:
            texts = []
            for rec in detailed:
                msg = _get(rec, "message", str(rec))
                action = _get(rec, "action", "")
                sev = _get(rec, "severity", "")
                texts.append(f"[{sev}] {msg}" + (f" → {action}" if action else ""))
            r._add_recommendations(texts)
        elif bottlenecks:
            r._add_recommendations([
                f"Réduire le temps des {len(bottlenecks)} postes goulots.",
                "Augmenter la capacité ou réaffecter des opérations.",
            ])

        r.build()

    @staticmethod
    def bottleneck_analysis(
        stations: list[dict], ops: list[dict],
        target_cycle: float, path: Path, project_name: str = "Analyse"
    ) -> None:
        """Génère un rapport PDF d'analyse des goulets."""
        if not HAS_REPORTLAB:
            raise RuntimeError("reportlab n'est pas installé: pip install reportlab")

        r = BalanceReport(path)
        bottlenecks = [s for s in stations if
                       s.get("total_time", s.get("total_time_min", 0)) > target_cycle * 1.01]
        near = [s for s in stations if
                s.get("total_time", s.get("total_time_min", 0)) >= target_cycle * 0.9
                and s.get("total_time", s.get("total_time_min", 0)) <= target_cycle * 1.01]

        r._add_title_page(project_name)
        r._add_kpi_section([
            (f"{len(stations)}", "Postes"),
            (f"{len(bottlenecks)}", "Goulots"),
            (f"{len(near)}", "Proches limite"),
            (f"{target_cycle:.3f} min", "Tps cycle cible"),
            (f"{60 / target_cycle:.1f}" if target_cycle > 0 else "-", "Cadence (pièces/h)"),
        ])
        r._add_station_table(stations)
        r._add_operations_table(ops)
        r._add_bottleneck_section(bottlenecks, target_cycle)

        sec_dist: dict[str, list] = {}
        mt_dist: dict[str, list] = {}
        for op in ops:
            sec = op.get("section", "général")
            mt = op.get("machine_type", "inconnu")
            d = op.get("duration_min", op.get("duration", 0))
            sec_dist.setdefault(sec, []).append(d)
            mt_dist.setdefault(mt, []).append(d)

        r._add_distribution_section(
            [(k, sum(v), len(v)) for k, v in sorted(sec_dist.items())],
            "Répartition par section", "Section",
        )
        r._add_distribution_section(
            [(k, sum(v), len(v)) for k, v in sorted(mt_dist.items())],
            "Répartition par type machine", "Type machine",
        )

        recs = []
        if bottlenecks:
            recs.append(
                f"Réduire le temps des {len(bottlenecks)} postes goulots "
                f"(excédent total: {sum(s.get('total_time', s.get('total_time_min', 0)) - target_cycle for s in bottlenecks):.3f} min/pièce)."
            )
        if near:
            recs.append(f"Surveiller les {len(near)} postes proches de la limite (≥ 90 %).")
        # Poste avec le plus de temps mort
        idle = [target_cycle - s.get("total_time", s.get("total_time_min", 0))
                for s in stations]
        if idle:
            max_idle = max(idle)
            if max_idle > 0:
                worst = stations[idle.index(max_idle)]
                recs.append(
                    f"Poste {worst.get('station', '?')} a le plus de temps mort "
                    f"({max_idle:.3f} min). Envisager d'ajouter des opérations."
                )
        r._add_recommendations(recs)
        r.build()

    @staticmethod
    def simulation_report(sim_result: Any, path: Path, project_name: str = "Simulation") -> None:
        """Génère un rapport PDF complet depuis un SimulationResult."""
        if not HAS_REPORTLAB:
            raise RuntimeError("reportlab n'est pas installé: pip install reportlab")

        r = BalanceReport(path)

        station_stats = (
            sim_result.station_stats
            if hasattr(sim_result, "station_stats") else sim_result.get("station_stats", [])
        )
        sim_dict = {
            "throughput_per_hour": _safe(sim_result, "throughput_per_hour", 0),
            "avg_cycle_time_min": _safe(sim_result, "avg_cycle_time_min", 0),
            "avg_wip": _safe(sim_result, "avg_wip", 0),
            "total_parts_completed": _safe(sim_result, "total_parts_completed", 0),
            "simulation_time_min": _safe(sim_result, "simulation_time_min", 0),
            "station_stats": [
                {
                    "station_id": _safe(s, "station_id", ""),
                    "avg_occupancy_time": _safe(s, "total_time_worked", 0),
                    "max_occupancy_time": _safe(s, "total_time_worked", 0),
                    "utilization_pct": _safe(s, "utilization_pct", 0),
                    "parts_processed": _safe(s, "total_processed", 0),
                }
                for s in station_stats
            ],
        }

        r._add_title_page(f"Simulation — {project_name}")
        r._add_simulation_section(sim_dict)
        r._add_kpi_section([
            (f'{sim_dict["total_parts_completed"]}', "Pièces produites"),
            (f'{sim_dict["simulation_time_min"]:.1f}', "Temps simulé (min)"),
            (f'{sim_dict["avg_wip"]:.1f}', "WIP moyen"),
        ])
        r.build()
