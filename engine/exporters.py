"""
Exportateurs pour résultats d'équilibrage.
Formats: JSON, Excel (rapport détaillé), Gantt (JSON pour visualisation JS).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side, numbers
    OPENPYXL_AVAILABLE = True
except ImportError:
    OPENPYXL_AVAILABLE = False

from engine.models import BalancingResult


def export_result_to_json(result: BalancingResult, filepath: Path) -> None:
    """Exporte le résultat complet en JSON."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with filepath.open("w", encoding="utf-8") as f:
        f.write(result.to_json())


def export_result_to_excel(result: BalancingResult, filepath: Path) -> None:
    """Exporte un rapport détaillé en Excel."""
    if not OPENPYXL_AVAILABLE:
        raise ImportError("openpyxl requis: pip install openpyxl")
    
    wb = openpyxl.Workbook()
    
    # Styles
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="2F5496", end_color="2F5496", fill_type="solid")
    header_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    thin_border = Border(
        left=Side(style="thin"),
        right=Side(style="thin"),
        top=Side(style="thin"),
        bottom=Side(style="thin"),
    )
    pct_format = "0.0%"
    time_format = "0.00"
    
    def style_header_row(ws, row=1):
        for cell in ws[row]:
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_alignment
            cell.border = thin_border
    
    def style_data_cell(cell, fmt=None):
        cell.border = thin_border
        cell.alignment = Alignment(horizontal="center", vertical="center")
        if fmt:
            cell.number_format = fmt
    
    # ===== Feuille 1: RÉSUMÉ =====
    ws_sum = wb.active
    ws_sum.title = "Résumé"
    
    summary_data = [
        ["Indicateur", "Valeur"],
        ["Projet", result.problem.name],
        ["Solveur", result.solver_used],
        ["Statut", result.status],
        ["Temps résolution (s)", round(result.solve_time_seconds, 2)],
        ["", ""],
        ["📊 KPIs PRINCIPAUX", ""],
        ["Stations utilisées", result.stations_used],
        ["Cycle time cible (min)", result.problem.target_cycle_time],
        ["Cycle time réel (min)", result.actual_cycle_time],
        ["Efficacité ligne (%)", result.efficiency],
        ["Balance delay (%)", result.balance_delay],
        ["Smoothness index", result.smoothness_index],
        ["", ""],
        ["⚠️  Avertissements", "" if not result.warnings else "; ".join(result.warnings)],
    ]
    
    if result.error_message:
        summary_data.append(["❌ Erreur", result.error_message])
    
    for row in summary_data:
        ws_sum.append(row)
    
    style_header_row(ws_sum)
    for row in ws_sum.iter_rows(min_row=2, max_row=ws_sum.max_row, max_col=2):
        for cell in row:
            style_data_cell(cell)
    ws_sum.column_dimensions["A"].width = 35
    ws_sum.column_dimensions["B"].width = 25
    
    # ===== Feuille 2: DÉTAIL POSTES =====
    ws_st = wb.create_sheet("Détail Postes")
    st_headers = [
        "Station", "Poste Physique", "Temps Total (min)", "Charge (%)",
        "Écart Cible (min)", "Nb Opérations", "Opérations", "Ouvriers", "Type Machine"
    ]
    ws_st.append(st_headers)
    style_header_row(ws_st)
    
    for sd in result.station_details:
        ws_st.append([
            sd["station"],
            sd.get("workstation", ""),
            sd["total_time"],
            sd["load_pct"] / 100,
            sd["total_time"] - result.problem.target_cycle_time,
            len(sd["operations"]),
            ", ".join(sd["operations"]),
            ", ".join(sd.get("workers", [])) if sd.get("workers") else "—",
            sd.get("machine_type", ""),
        ])
    
    for row in ws_st.iter_rows(min_row=2, max_row=ws_st.max_row, max_col=len(st_headers)):
        for i, cell in enumerate(row):
            style_data_cell(cell, pct_format if i == 3 else time_format if i in (2, 4) else None)
    
    # Largeurs
    widths = [10, 18, 16, 12, 14, 12, 40, 25, 20]
    for i, w in enumerate(widths, 1):
        ws_st.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w
    
    # ===== Feuille 3: OPÉRATIONS =====
    ws_op = wb.create_sheet("Opérations")
    op_headers = [
        "OpID", "Nom", "Durée (min)", "Station", "Prédécesseurs",
        "Machine Requise", "Compétences Requises", "Section", "Optionnel"
    ]
    ws_op.append(op_headers)
    style_header_row(ws_op)
    
    for op in result.problem.operations:
        station = result.operation_assignments.get(op.id, "—")
        ws_op.append([
            op.id,
            op.name,
            op.duration,
            station,
            "; ".join(op.predecessors) if op.predecessors else "—",
            op.machine_type or "—",
            "; ".join(op.required_skills) if op.required_skills else "—",
            op.section or "—",
            "Oui" if op.optional else "Non",
        ])
    
    for row in ws_op.iter_rows(min_row=2, max_row=ws_op.max_row, max_col=len(op_headers)):
        for i, cell in enumerate(row):
            style_data_cell(cell, time_format if i == 2 else None)
    
    op_widths = [12, 35, 12, 10, 25, 20, 30, 15, 10]
    for i, w in enumerate(op_widths, 1):
        ws_op.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w
    
    # ===== Feuille 4: OUVRIERS =====
    ws_wk = wb.create_sheet("Ouvriers")
    wk_headers = [
        "Ouvrier ID", "Nom", "Station Assignée", "Efficacité",
        "Compétences", "Disponible"
    ]
    ws_wk.append(wk_headers)
    style_header_row(ws_wk)
    
    for wk in result.problem.workers:
        station = result.worker_assignments.get(wk.id, "Non assigné")
        ws_wk.append([
            wk.id,
            wk.name,
            station,
            wk.efficiency,
            "; ".join(wk.skills) if wk.skills else "—",
            "Oui" if wk.available else "Non",
        ])
    
    for row in ws_wk.iter_rows(min_row=2, max_row=ws_wk.max_row, max_col=len(wk_headers)):
        for i, cell in enumerate(row):
            style_data_cell(cell, "0.00" if i == 3 else None)
    
    wk_widths = [15, 20, 18, 12, 50, 12]
    for i, w in enumerate(wk_widths, 1):
        ws_wk.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w
    
    # ===== Feuille 5: MATRICE COMPÉTENCES =====
    ws_sk = wb.create_sheet("Matrice Compétences")
    # Collecter toutes compétences
    all_skills = sorted(set(
        s for wk in result.problem.workers for s in wk.skills
    ))
    sk_headers = ["Ouvrier"] + all_skills
    ws_sk.append(sk_headers)
    style_header_row(ws_sk)
    
    for wk in result.problem.workers:
        row = [wk.name]
        for skill in all_skills:
            row.append("✓" if skill in wk.skills else "")
        ws_sk.append(row)
    
    for row in ws_sk.iter_rows(min_row=1, max_row=ws_sk.max_row, max_col=len(sk_headers)):
        for cell in row:
            style_data_cell(cell)
    
    # ===== Feuille 6: DÉCISION (capacité) — si disponible =====
    if getattr(result, "capacity", None) is not None:
        cap = result.capacity
        ws_cap = wb.create_sheet("Décision")
        cap_rows = [
            ["Indicateur", "Valeur"],
            ["Quantité commandée", cap.target.order_quantity],
            ["Délai (jours)", cap.target.work_days],
            ["Heures productives/jour", cap.target.hours_per_day],
            ["Efficacité ligne cible", cap.target.line_efficiency],
            ["", ""],
            ["Takt requis (min/pièce)", round(cap.takt_time, 3)],
            ["Demande journalière (pcs)", round(cap.daily_demand, 1)],
            ["Cycle max planifiable (min)", round(cap.required_cycle_time, 3)],
            ["Cycle réel (min)", result.actual_cycle_time],
            ["Cycle projeté réaliste (min)", cap.projected_cycle_time],
            ["", ""],
            ["Opérateurs requis (estimation)", cap.required_operators],
            ["Borne théorique opérateurs", round(cap.theoretical_min_operators, 1)],
            ["Opérateurs affectés", cap.assigned_operators],
            ["", ""],
            ["Production projetée (pcs/jour)", round(cap.projected_daily_output, 1)],
            ["Production nominale (pcs/jour)", round(cap.nominal_daily_output, 1)],
            ["Déficit journalier (pcs)", round(cap.daily_gap, 1)],
            ["Jours réels pour la commande", round(cap.projected_order_days, 1)],
            ["Coût MO/pièce", cap.labor_cost_per_piece],
            ["", ""],
            ["VERDICT", cap.verdict],
        ]
        for row in cap_rows:
            ws_cap.append(row)
        style_header_row(ws_cap)
        for row in ws_cap.iter_rows(min_row=2, max_row=ws_cap.max_row, max_col=2):
            for cell in row:
                style_data_cell(cell)
        ws_cap.column_dimensions["A"].width = 35
        ws_cap.column_dimensions["B"].width = 20
        # Verdict en couleur
        vcell = ws_cap.cell(row=ws_cap.max_row, column=2)
        vcell.font = Font(bold=True, color={
            "OK": "1E7D32", "TENDU": "B26A00", "INFAISABLE": "C62828",
        }.get(cap.verdict, "000000"))

    # ===== Feuille 7: RECOMMANDATIONS — si disponibles =====
    if getattr(result, "recommendations", None):
        ws_rec = wb.create_sheet("Recommandations")
        ws_rec.append(["Sévérité", "Catégorie", "Constat", "Action recommandée"])
        style_header_row(ws_rec)
        for rec in result.recommendations:
            sev = rec.severity if hasattr(rec, "severity") else rec.get("severity", "")
            cat = rec.category if hasattr(rec, "category") else rec.get("category", "")
            msg = rec.message if hasattr(rec, "message") else rec.get("message", "")
            act = rec.action if hasattr(rec, "action") else rec.get("action", "")
            ws_rec.append([sev, cat, msg, act])
        for row in ws_rec.iter_rows(min_row=2, max_row=ws_rec.max_row, max_col=4):
            for cell in row:
                style_data_cell(cell)
        for i, w in enumerate([12, 16, 60, 60], 1):
            ws_rec.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w

    # ===== Sauvegarder =====
    filepath.parent.mkdir(parents=True, exist_ok=True)
    wb.save(filepath)


def export_gantt_data(result: BalancingResult, filepath: Path) -> None:
    """Exporte données pour diagramme de Gantt (JSON pour visualisation web)."""
    # Calculer temps début/fin par station
    station_start = {}
    current = 0.0
    for sd in result.station_details:
        station_start[sd["station"]] = current
        current += sd["total_time"]
    
    gantt = {
        "problem": result.problem.name,
        "target_cycle_time": result.problem.target_cycle_time,
        "actual_cycle_time": result.actual_cycle_time,
        "stations": []
    }
    
    for sd in result.station_details:
        st = sd["station"]
        ops = []
        t = 0.0
        for op_id in sd["operations"]:
            op = result.problem.get_operation(op_id)
            if op:
                ops.append({
                    "id": op.id,
                    "name": op.name,
                    "start": round(t, 3),
                    "end": round(t + op.duration, 3),
                    "duration": op.duration,
                    "machine_type": op.machine_type,
                    "skills": op.required_skills,
                })
                t += op.duration
        
        gantt["stations"].append({
            "station": st,
            "label": f"Station {st}" + (f" ({sd.get('workstation', '')})" if sd.get("workstation") else ""),
            "start": round(station_start.get(st, 0), 3),
            "end": round(station_start.get(st, 0) + sd["total_time"], 3),
            "total_time": sd["total_time"],
            "load_pct": sd["load_pct"],
            "operations": ops,
            "workers": sd.get("workers", []),
        })
    
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with filepath.open("w", encoding="utf-8") as f:
        json.dump(gantt, f, indent=2, ensure_ascii=False)


def export_problem_to_json(problem, filepath: Path) -> None:
    """Exporte un problème en JSON."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with filepath.open("w", encoding="utf-8") as f:
        f.write(problem.to_json())


def export_comparison_to_excel(comparison, filepath: Path) -> None:
    """Exporte un comparatif de scénarios (ScenarioComparison) en Excel.

    Feuille 1 : tableau comparatif + scénario recommandé.
    Feuille 2 : détail par poste du meilleur scénario.
    """
    if not OPENPYXL_AVAILABLE:
        raise ImportError("openpyxl requis: pip install openpyxl")

    wb = openpyxl.Workbook()
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="2F5496", end_color="2F5496", fill_type="solid")
    thin_border = Border(
        left=Side(style="thin"), right=Side(style="thin"),
        top=Side(style="thin"), bottom=Side(style="thin"),
    )

    ws = wb.active
    ws.title = "Comparaison"
    header, rows = comparison.table()
    ws.append(header)
    for cell in ws[1]:
        cell.font = header_font
        cell.fill = header_fill
        cell.border = thin_border
    for r in rows:
        ws.append(r)
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, max_col=len(header)):
        for cell in row:
            cell.border = thin_border
            cell.alignment = Alignment(horizontal="center", vertical="center")
    for i, h in enumerate(header, 1):
        width = max(len(h) + 2, max((len(str(r[i - 1])) for r in rows), default=8) + 2)
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = min(width, 30)

    best = comparison.best()
    if best is not None:
        ws.append([])
        ws.append(["Scénario recommandé", best.scenario.name])
        ws.cell(row=ws.max_row, column=1).font = Font(bold=True)

        # Contexte commande
        if comparison.target is not None:
            t = comparison.target
            ws.append(["Quantité commandée", t.order_quantity])
            ws.append(["Takt requis (min/pièce)", round(t.takt_time, 3)])
            ws.append(["Demande journalière (pcs)", round(t.daily_demand, 1)])

        # Détail du meilleur scénario
        ws2 = wb.create_sheet("Meilleur scénario")
        ws2.append(["Station", "Temps (min)", "Temps réel (min)", "Charge (%)",
                    "Nb Ops", "Opérations", "Ouvriers"])
        for cell in ws2[1]:
            cell.font = header_font
            cell.fill = header_fill
            cell.border = thin_border
        realistic = getattr(best.result, "realistic_station_times", {}) or {}
        for sd in best.result.station_details:
            ws2.append([
                sd["station"], sd["total_time"],
                realistic.get(sd["station"], sd["total_time"]),
                sd["load_pct"], len(sd["operations"]),
                ", ".join(sd["operations"]),
                ", ".join(sd.get("workers", [])),
            ])
        for row in ws2.iter_rows(min_row=2, max_row=ws2.max_row, max_col=7):
            for cell in row:
                cell.border = thin_border
                cell.alignment = Alignment(horizontal="center", vertical="center")
        for i, w in enumerate([10, 12, 14, 10, 8, 40, 30], 1):
            ws2.column_dimensions[openpyxl.utils.get_column_letter(i)].width = w

    filepath.parent.mkdir(parents=True, exist_ok=True)
    wb.save(filepath)