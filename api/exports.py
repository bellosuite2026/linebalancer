"""Exports Excel et PDF d'un calcul historisé (côté API, sans toucher au moteur).

Les fonctions travaillent sur les données telles qu'enregistrées en base :
le calcul (`run`, avec `result`) et, si disponible, la gamme (`problem` = payload).
"""
from __future__ import annotations

import io
from datetime import datetime
from typing import Any, Optional

STATUS_FR = {
    "OPTIMAL": "solution optimale", "FEASIBLE": "solution réalisable", "INFEASIBLE": "aucune solution",
    "INFEASIBLE_CONSTRAINTS": "contraintes non respectées", "HEURISTIC": "solution heuristique",
    "TIMEOUT": "temps limite atteint", "ERROR": "erreur",
}
SOLVER_FR = {"rpw": "RPW (heuristique rapide)", "cp_sat": "CP-SAT (optimisation)"}
SEVERITY_FR = {"error": "Bloquant", "warning": "Attention", "info": "Info"}


# --------------------------------------------------------------------------- données
def _balance(run: dict) -> Optional[dict]:
    res = run.get("result") or {}
    if run.get("kind") == "min_cycle":
        return res.get("result")
    return res or None


def _ops_index(problem: Optional[dict]) -> dict[str, dict]:
    return {o["id"]: o for o in (problem or {}).get("operations", [])}


def _fmt(v: Any, d: int = 2) -> str:
    if v is None:
        return "—"
    s = f"{float(v):,.{d}f}".replace(",", " ").replace(".", ",")
    if "," in s:
        s = s.rstrip("0").rstrip(",")
    return s


def _date(s: Optional[str]) -> str:
    if not s:
        return "—"
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).strftime("%d/%m/%Y %H:%M UTC")
    except ValueError:
        return s


def summary(run: dict) -> list[tuple[str, str]]:
    """Indicateurs clés, communs aux deux formats."""
    r = _balance(run) or {}
    rows: list[tuple[str, str]] = []
    if run.get("kind") == "min_cycle":
        mc = run.get("result") or {}
        rows.append(("Cadence minimale", f"{_fmt(mc.get('min_cycle_time'), 3)} min/pièce" if mc.get("found")
                     else "non trouvée"))
    if r:
        cyc = r.get("actual_cycle_time") or 0
        out = 60 / cyc if cyc else 0
        rows += [
            ("Cadence cible", f"{_fmt(r.get('target_cycle_time'), 3)} min"),
            ("Cycle réel", f"{_fmt(r.get('actual_cycle_time'), 3)} min"),
            ("Stations", str(r.get("stations_used", "—"))),
            ("Opérateurs", str(r.get("operators", "—"))),
            ("Rendement ligne", f"{_fmt(r.get('efficiency'), 1)} %"),
            ("Perte d'équilibrage", f"{_fmt(r.get('balance_delay'), 1)} %"),
            ("Indice de lissage", _fmt(r.get("smoothness_index"))),
            ("Production horaire", f"{_fmt(out, 0)} pièces/h"),
            ("Production 8 h", f"{_fmt(out * 8, 0)} pièces"),
            ("Conformité", "Conforme" if r.get("compliant") else "Non conforme"),
            ("Méthode", SOLVER_FR.get(r.get("solver", ""), r.get("solver", ""))),
            ("Statut solveur", STATUS_FR.get(r.get("status", ""), r.get("status", ""))),
        ]
    return rows


def _issues(r: dict) -> list[tuple[str, str, str]]:
    out = [(SEVERITY_FR.get(v.get("severity", ""), v.get("severity", "")), v.get("code", ""),
            v.get("message", "") + (f" → {v['suggestion']}" if v.get("suggestion") else ""))
           for v in r.get("violations", [])]
    out += [("Attention", "", w) for w in r.get("warnings", []) if w.startswith("[")]
    return out


# --------------------------------------------------------------------------- Excel
def build_xlsx(run: dict, problem: Optional[dict], org_name: str = "") -> bytes:
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, LineChart, Reference
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    brand = "1F4E79"
    head_font, head_fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor=brand)
    thin = Side(style="thin", color="D9D9D9")
    border = Border(top=thin, bottom=thin, left=thin, right=thin)
    wrap = Alignment(wrap_text=True, vertical="top")

    def header(ws, row: int, cols: list[str]):
        for i, c in enumerate(cols, 1):
            cell = ws.cell(row=row, column=i, value=c)
            cell.font, cell.fill, cell.border = head_font, head_fill, border
            cell.alignment = Alignment(vertical="center", wrap_text=True)

    def widths(ws, ws_widths: list[int]):
        for i, w in enumerate(ws_widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w

    r = _balance(run) or {}
    ops = _ops_index(problem)
    wb = Workbook()

    # Synthèse
    ws = wb.active
    ws.title = "Synthèse"
    ws["A1"] = "Rapport d'équilibrage de ligne"
    ws["A1"].font = Font(bold=True, size=16, color=brand)
    meta = [("Atelier", org_name or "—"), ("Gamme", (problem or {}).get("name", "—")),
            ("Calcul", "Cadence minimale" if run.get("kind") == "min_cycle" else "Équilibrage à la cadence cible"),
            ("Date", _date(run.get("created_at"))), ("Référence", run.get("id", ""))]
    row = 3
    for k, v in meta + [("", "")] + summary(run):
        ws.cell(row=row, column=1, value=k).font = Font(bold=True)
        ws.cell(row=row, column=2, value=v)
        row += 1
    widths(ws, [26, 48])

    # Répartition
    st = r.get("station_details", [])
    ws = wb.create_sheet("Répartition")
    cols = ["Station", "Opérations", "Désignations", "Temps (min)", "Charge (%)", "Postes parallèles",
            "Poste(s)", "Machine(s)", "Ouvrier(s)", "Section(s)"]
    header(ws, 1, cols)
    for i, s in enumerate(st, 2):
        sh = s.get("shares") or {}
        vals = [s.get("station"), ", ".join(f"{o} (part {sh[o]:.2f} min)" if o in sh else o
                                             for o in s.get("operations", [])),
                " ; ".join(ops.get(o, {}).get("name", "") for o in s.get("operations", [])),
                s.get("total_time"), s.get("load_pct"), s.get("parallel", 1),
                ", ".join(s.get("workstations") or ([s["workstation"]] if s.get("workstation") else [])),
                ", ".join(s.get("machine_types", [])), ", ".join(s.get("workers", [])),
                ", ".join(s.get("sections", []))]
        for j, v in enumerate(vals, 1):
            c = ws.cell(row=i, column=j, value=v)
            c.border, c.alignment = border, wrap
        if (s.get("load_pct") or 0) > 100.01:
            for j in range(1, len(cols) + 1):
                ws.cell(row=i, column=j).fill = PatternFill("solid", fgColor="FBEAEA")
    widths(ws, [9, 22, 44, 12, 11, 11, 16, 20, 26, 14])
    ws.freeze_panes = "A2"

    # Graphique de charge
    if st:
        ws2 = wb.create_sheet("Graphique")
        header(ws2, 1, ["Station", "Charge (min)", "Cadence cible (min)"])
        cyc = r.get("target_cycle_time") or 0
        for i, s in enumerate(st, 2):
            ws2.cell(row=i, column=1, value=f"S{s.get('station')}")
            ws2.cell(row=i, column=2, value=round((s.get("load_pct") or 0) / 100 * cyc, 3))
            ws2.cell(row=i, column=3, value=cyc)
        n = len(st) + 1
        bar = BarChart()
        bar.title, bar.y_axis.title, bar.x_axis.title = "Charge par station", "min", "Station"
        bar.add_data(Reference(ws2, min_col=2, min_row=1, max_row=n), titles_from_data=True)
        bar.set_categories(Reference(ws2, min_col=1, min_row=2, max_row=n))
        line = LineChart()
        line.add_data(Reference(ws2, min_col=3, min_row=1, max_row=n), titles_from_data=True)
        bar += line
        bar.height, bar.width = 9, max(16, len(st) * 0.9)
        ws2.add_chart(bar, "E2")
        widths(ws2, [10, 14, 20])

    # Gamme
    if ops:
        ws = wb.create_sheet("Gamme")
        assign = {k: v for k, v in (r.get("operation_assignments") or {}).items()}
        header(ws, 1, ["Op_ID", "Désignation", "SAM (min)", "Prédécesseurs", "Machine", "Compétences",
                       "Section", "Station"])
        for i, o in enumerate(ops.values(), 2):
            vals = [o["id"], o.get("name", ""), o.get("duration"), ", ".join(o.get("predecessors", [])),
                    o.get("machine_type", ""), ", ".join(o.get("required_skills", [])), o.get("section", ""),
                    assign.get(o["id"])]
            for j, v in enumerate(vals, 1):
                c = ws.cell(row=i, column=j, value=v)
                c.border, c.alignment = border, wrap
        widths(ws, [10, 42, 10, 16, 18, 30, 12, 9])
        ws.freeze_panes = "A2"

    # Points d'attention
    iss = _issues(r)
    if iss:
        ws = wb.create_sheet("Points d'attention")
        header(ws, 1, ["Niveau", "Code", "Détail"])
        for i, (lvl, code, msg) in enumerate(iss, 2):
            for j, v in enumerate((lvl, code, msg), 1):
                c = ws.cell(row=i, column=j, value=v)
                c.border, c.alignment = border, wrap
        widths(ws, [12, 20, 100])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# --------------------------------------------------------------------------- PDF
def _pdf_text(t: str) -> str:
    """Les polices PDF standard ne couvrent que le jeu Windows-1252."""
    t = t.replace("→", "»").replace("≥", ">=").replace("≤", "<=")
    return t.encode("cp1252", "ignore").decode("cp1252").strip()


def build_pdf(run: dict, problem: Optional[dict], org_name: str = "") -> bytes:
    from reportlab.graphics.shapes import Drawing, Line, Rect, String
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    brand = colors.HexColor("#1F4E79")
    r = _balance(run) or {}
    ops = _ops_index(problem)
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], textColor=brand, alignment=TA_LEFT, fontSize=18, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=brand, fontSize=12, spaceBefore=8, spaceAfter=4)
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=8.5, leading=11)
    small = ParagraphStyle("s", parent=body, fontSize=7.5, leading=9.5, textColor=colors.HexColor("#555555"))

    buf = io.BytesIO()
    page = landscape(A4)
    doc = SimpleDocTemplate(buf, pagesize=page, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=12 * mm,
                            bottomMargin=12 * mm, title="Rapport d'équilibrage", author="Textile Line Balancer")
    W = page[0] - 28 * mm
    story: list = []

    story.append(Paragraph("Rapport d'équilibrage de ligne", h1))
    kind = "Cadence minimale" if run.get("kind") == "min_cycle" else "Équilibrage à la cadence cible"
    story.append(Paragraph(" · ".join(x for x in [org_name, (problem or {}).get("name", ""), kind,
                                                   _date(run.get("created_at"))] if x), small))
    story.append(Spacer(1, 6))

    # Indicateurs en grille
    kp = summary(run)
    cells = [[Paragraph(f"<font size=7 color='#666666'>{k}</font><br/><b>{v}</b>", body) for k, v in kp[i:i + 5]]
             for i in range(0, len(kp), 5)]
    if cells:
        while len(cells[-1]) < 5:
            cells[-1].append("")
        t = Table(cells, colWidths=[W / 5] * 5)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F4F6F9")),
                               ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#DDDDDD")),
                               ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.white),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 5),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
        story.append(t)

    st = r.get("station_details", [])
    cyc = r.get("target_cycle_time") or 0
    if st and cyc:
        story.append(Paragraph("Charge par station", h2))
        H, padl, padb = 58 * mm, 26, 16
        d = Drawing(W, H)
        vals = [(s.get("load_pct") or 0) / 100 * cyc for s in st]
        top = max(cyc * 1.15, *vals)
        pw, ph = W - padl - 4, H - padb - 8
        bw = pw / len(st)
        y = lambda v: padb + ph * v / top  # noqa: E731
        for t_ in (0, cyc / 2, cyc):
            d.add(Line(padl, y(t_), W - 4, y(t_), strokeColor=colors.HexColor("#EEEEEE"), strokeWidth=0.5))
            d.add(String(padl - 3, y(t_) - 3, _fmt(t_), fontSize=6.5, textAnchor="end", fillColor=colors.grey))
        for i, (s, v) in enumerate(zip(st, vals)):
            ratio = v / cyc
            col = ("#C0392B" if ratio > 1.0001 else "#2F9E6E" if ratio >= .85 else "#E0A93B" if ratio >= .6
                   else "#B9C3CF")
            d.add(Rect(padl + i * bw + bw * .15, padb, bw * .7, y(v) - padb, fillColor=colors.HexColor(col),
                       strokeColor=None))
            d.add(String(padl + i * bw + bw / 2, padb - 9, str(s.get("station")), fontSize=6.5,
                         textAnchor="middle", fillColor=colors.grey))
        d.add(Line(padl, y(cyc), W - 4, y(cyc), strokeColor=brand, strokeWidth=1, strokeDashArray=[3, 2]))
        d.add(String(W - 4, y(cyc) + 3, f"Cadence {_fmt(cyc, 3)} min", fontSize=7, textAnchor="end",
                     fillColor=brand))
        story.append(d)

        story.append(Paragraph("Répartition des opérations", h2))
        data = [["Station", "Opérations", "Temps (min)", "Charge", "Poste(s)", "Ouvrier(s)"]]
        for s in st:
            sh = s.get("shares") or {}
            names = "<br/>".join(f"<b>{o}</b> {ops.get(o, {}).get('name', '')}"
                                 + (f" <i>(part {_fmt(sh[o])} min)</i>" if o in sh else "")
                                 for o in s.get("operations", []))
            par = f" ×{s['parallel']}" if (s.get("parallel") or 1) > 1 else ""
            data.append([f"{s.get('station')}{par}", Paragraph(names, small), _fmt(s.get("total_time")),
                         f"{_fmt(s.get('load_pct'), 0)} %",
                         Paragraph(", ".join(s.get("workstations") or ([s["workstation"]] if s.get("workstation")
                                                                       else [])) or "aucun", small),
                         Paragraph(", ".join(s.get("workers", [])) or "—", small)])
        t = Table(data, colWidths=[W * .07, W * .45, W * .09, W * .08, W * .13, W * .18], repeatRows=1)
        style = [("BACKGROUND", (0, 0), (-1, 0), brand), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                 ("FONTSIZE", (0, 0), (-1, -1), 8), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                 ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#DDDDDD")),
                 ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FAFAF8")])]
        for i, s in enumerate(st, 1):
            if (s.get("load_pct") or 0) > 100.01:
                style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#FBEAEA")))
        t.setStyle(TableStyle(style))
        story.append(t)

    iss = _issues(r)
    if iss:
        story.append(Paragraph("Points d'attention", h2))
        for lvl, code, msg in iss:
            story.append(Paragraph(_pdf_text(f"<b>{lvl}</b> {code + ' – ' if code else ''}{msg}"), body))

    def footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.grey)
        canvas.drawString(14 * mm, 7 * mm, "Textile Line Balancer · linebalancer.netlify.app")
        canvas.drawRightString(page[0] - 14 * mm, 7 * mm, f"Page {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
