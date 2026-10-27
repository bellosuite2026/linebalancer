"""Jumeau numérique : adaptateur entre les calculs/sessions enregistrés et engine.simulation.

- twin_plan(run, problem)       : plan de ligne (stations, opérations + compétences, ouvrières).
- run_scenarios(...)            : simule 2–3 scénarios « et si » et prépare la comparaison.
- sync(...)                     : réel (suivi de production) vs simulé, prévision fin de journée / commande.
- build_xlsx / build_pdf        : exports de la comparaison.

Aucune logique d'équilibrage ici : la simulation est dans engine/simulation.py.
"""
from __future__ import annotations

import io
import math
from datetime import date, timedelta
from typing import Any, Optional

from engine.simulation import LineDayConfig, default_layout, simulate_line_day

from api import production
from api.production import _fmt, _pdf_text

FORECAST_STOP_MIN = 15.0      # durée supposée restante d'une panne en cours
TRACE_EVENTS_PER_SCENARIO = 15000


# --------------------------------------------------------------------------- plan
def twin_plan(run: dict, problem: Optional[dict], base_plan: Optional[dict] = None) -> dict:
    """Plan de la ligne enrichi des compétences (réaffectation) et rendements des ouvrières."""
    plan = dict(base_plan or production.build_plan(run, problem))
    ops = {o["id"]: o for o in (problem or {}).get("operations", [])}
    stations = []
    for st in plan.get("stations", []):
        st = dict(st)
        st["operations"] = [{**o, "skills": list(ops.get(o["id"], {}).get("required_skills") or []),
                             "machine_type": ops.get(o["id"], {}).get("machine_type", "")}
                            for o in st.get("operations", [])]
        stations.append(st)
    plan["stations"] = stations
    workers = {}
    for w in (problem or {}).get("workers", []):
        if w.get("available", True) is False:
            continue
        workers[str(w["id"])] = {"name": w.get("name") or w["id"], "skills": list(w.get("skills") or []),
                                 "efficiency": float(w.get("efficiency") or 1.0)}
    for st in stations:
        for wid, name in zip(st.get("worker_ids") or [], st.get("workers") or []):
            workers.setdefault(str(wid), {"name": name, "skills": [], "efficiency": 1.0})
    plan["workers"] = workers
    return plan


def layout_for(plan: dict, saved: Optional[dict], kind: str = "line") -> dict:
    """Implantation enregistrée complétée des stations manquantes (ou implantation par défaut)."""
    base = default_layout(plan.get("stations", []), (saved or {}).get("kind") or kind)
    pos = dict(base["positions"])
    for k, v in ((saved or {}).get("positions") or {}).items():
        if k in pos and isinstance(v, dict):
            pos[k] = {"x": float(v.get("x", 0)), "y": float(v.get("y", 0))}
    return {"kind": (saved or {}).get("kind") or base["kind"], "positions": pos}


# --------------------------------------------------------------------------- scénarios
def scenario_config(s: dict, trace_events: int = TRACE_EVENTS_PER_SCENARIO) -> LineDayConfig:
    return LineDayConfig(shift_minutes=float(s.get("shift_minutes", 480)), bundle_size=int(s.get("bundle_size", 10)),
                         efficiency=float(s.get("efficiency_pct", 100)) / 100,
                         variability=float(s.get("variability_pct", 10)) / 100, seed=int(s.get("seed", 42)),
                         max_trace_events=trace_events)


def engine_scenario(s: dict) -> dict:
    return {"absent": list(s.get("absent") or []), "reassign": bool(s.get("reassign", True)),
            "operators": {str(k): int(v) for k, v in (s.get("operators") or {}).items()},
            "breakdowns": [dict(b) for b in s.get("breakdowns") or []]}


def run_one(plan: dict, layout: dict, s: dict) -> dict:
    res = simulate_line_day(plan, layout, scenario_config(s), engine_scenario(s))
    return res


def run_scenarios(plans: dict[str, dict], layouts: dict[str, dict], scenarios: list[dict],
                  base_run_id: str) -> dict:
    """plans/layouts indexés par run_id (le calcul de base + éventuels autres modèles)."""
    out = []
    for s in scenarios:
        rid = s.get("run_id") or base_run_id
        res = run_one(plans[rid], layouts[rid], s)
        out.append({"name": s.get("name") or "Scénario", "params": s, "run_id": rid, "result": res})
    return {"scenarios": out, "comparison": comparison(out)}


def comparison(items: list[dict]) -> list[dict]:
    """Lignes de la comparaison côte à côte (valeurs brutes, la première colonne sert de référence)."""
    rows = [
        ("pieces", "Pièces / jour"), ("per_hour", "Pièces / heure"), ("bottleneck", "Goulot (station)"),
        ("wip_max", "Encours max (pièces)"), ("wip_avg", "Encours moyen (pièces)"),
        ("lead_time_min", "Temps de traversée (min)"), ("avg_wait_min", "Attente moyenne par paquet (min)"),
        ("utilization_avg", "Occupation moyenne (%)"), ("operators", "Ouvrières"),
        ("transport_m", "Paquets transportés (m)"), ("walk_m", "Déplacements ouvrières (m)"),
    ]
    vals = []
    for it in items:
        r = it["result"]
        ws = r.get("workers") or []
        r["utilization_avg"] = round(sum(w["utilization_pct"] for w in ws) / len(ws), 1) if ws else 0
        r["operators"] = len({w["id"] for w in ws})
        vals.append(r)
    return [{"key": k, "label": label, "values": [v.get(k) for v in vals]} for k, label in rows]


def strip_for_list(results: dict) -> dict:
    return {"comparison": results.get("comparison")}


# --------------------------------------------------------------------------- réel vs simulé
def sync(session: dict, entries: list[dict], plan: dict, layout: dict, *, now=None,
         order_qty: Optional[int] = None, order_done: int = 0, bundle_size: int = 10) -> dict:
    dash = production.dashboard(session, entries, now)
    shift = float(dash["shift_minutes"] or 480)
    elapsed = float(dash["elapsed_minutes"] or 0)
    shift = min(shift, 600.0)
    eff_real = dash.get("efficiency")
    eff = max(0.1, min(2.0, (eff_real or 100) / 100))

    # Journée prévue : simulation au temps standard (100 %) et recalée sur l'efficience réelle
    planned = simulate_line_day(plan, layout, LineDayConfig(shift_minutes=shift, bundle_size=bundle_size,
                                                           trace=False))
    calibrated = simulate_line_day(plan, layout, LineDayConfig(shift_minutes=shift, bundle_size=bundle_size,
                                                              efficiency=eff, trace=False))
    hours = [h["hour"] for h in dash["hourly"]]
    hourly = []
    for i, h in enumerate(dash["hourly"]):
        hourly.append({"hour": h["hour"], "target": h["target"], "real": h["output"],
                       "simulated": planned["hourly"][i] if i < len(planned["hourly"]) else None,
                       "simulated_calibrated": calibrated["hourly"][i] if i < len(calibrated["hourly"]) else None})
    by_station = []
    real_st = {s["station"]: s for s in dash["stations"]}
    for s in planned["stations"]:
        rs = real_st.get(s["station"], {})
        ratio = elapsed / shift if shift else 0
        by_station.append({"station": s["station"], "real": rs.get("pieces", 0),
                           "simulated_to_date": round(s["pieces"] * ratio),
                           "simulated_day": s["pieces"], "real_efficiency": rs.get("efficiency"),
                           "downtime_minutes": rs.get("downtime_minutes", 0)})

    # Prévision : reste du poste simulé à partir de l'encours réel entre stations
    remaining = max(0.0, shift - elapsed)
    order = [s["station"] for s in dash["stations"]]
    pieces = {s["station"]: s["pieces"] for s in dash["stations"]}
    notes = []
    forecast_rest = 0
    if remaining > 0 and order:
        init = {}
        for a, b in zip(order, order[1:]):
            init[b] = max(0, pieces.get(a, 0) - pieces.get(b, 0)) if elapsed > 0 else bundle_size
        scen: dict[str, Any] = {"absent": [], "breakdowns": []}
        for s in dash["stations"]:
            stop = s.get("ongoing_stop")
            if not stop:
                continue
            if stop["reason"] == "absence":
                st_plan = next((p for p in plan["stations"] if p["station"] == s["station"]), {})
                if st_plan.get("worker_ids"):
                    scen["absent"].append(st_plan["worker_ids"][0])
                    notes.append(f"Station {s['station']} : absence en cours prise en compte jusqu'à la fin du poste.")
            else:
                scen["breakdowns"].append({"station": s["station"], "start_min": 0, "duration_min": FORECAST_STOP_MIN})
                notes.append(f"Station {s['station']} : arrêt en cours supposé durer encore "
                             f"{FORECAST_STOP_MIN:.0f} min.")
        rest = simulate_line_day(plan, layout, LineDayConfig(shift_minutes=remaining, bundle_size=bundle_size,
                                                            efficiency=eff, initial_wip=init, trace=False), scen)
        forecast_rest = rest["pieces"]
        notes += [n for n in rest["notes"] if not n.startswith("Panne")]
    output = int(dash["output"])
    forecast_day = output + forecast_rest
    linear = round(output / elapsed * shift) if elapsed >= 15 else None
    res = {
        "session_id": session.get("id"), "elapsed_minutes": elapsed, "shift_minutes": shift,
        "real_efficiency": eff_real, "efficiency_used_pct": round(eff * 100, 1),
        "output": output, "target_shift": dash["target_shift"],
        "planned_day": planned["pieces"], "calibrated_day": calibrated["pieces"],
        "forecast_end_of_day": forecast_day, "forecast_linear": linear,
        "bottleneck_planned": planned["bottleneck"], "bottleneck_observed": dash["bottleneck_observed"],
        "hourly": hourly, "stations": by_station, "notes": notes, "hours": hours,
    }
    if order_qty:
        left_after_today = max(0, int(order_qty) - int(order_done or 0) - forecast_day)
        per_day = max(1, calibrated["pieces"])
        days = math.ceil(left_after_today / per_day) if left_after_today else 0
        d = date.fromisoformat(str(session.get("session_date"))[:10])
        n = 0
        while n < days:
            d += timedelta(days=1)
            if d.weekday() != 6:          # dimanche non travaillé
                n += 1
        res["order"] = {"quantity": int(order_qty), "done_before": int(order_done or 0),
                        "left_after_today": left_after_today, "pieces_per_day": calibrated["pieces"],
                        "extra_days": days, "finish_date": d.isoformat()}
    return res


# --------------------------------------------------------------------------- exports
def _cell(v: Any) -> Any:
    return "—" if v is None else v


def build_xlsx(sim: dict, org_name: str = "") -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    brand = "1F4E79"
    hf, hfill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor=brand)
    thin = Side(style="thin", color="D9D9D9")
    border = Border(top=thin, bottom=thin, left=thin, right=thin)

    def table(ws, row, cols, data, widths):
        for i, c in enumerate(cols, 1):
            cell = ws.cell(row=row, column=i, value=c)
            cell.font, cell.fill, cell.border = hf, hfill, border
        for r_i, vals in enumerate(data, row + 1):
            for j, v in enumerate(vals, 1):
                ws.cell(row=r_i, column=j, value=v).border = border
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w

    res = sim.get("results") or {}
    items = res.get("scenarios") or []
    wb = Workbook()
    ws = wb.active
    ws.title = "Comparaison"
    ws["A1"] = "Jumeau numérique : comparaison de scénarios"
    ws["A1"].font = Font(bold=True, size=15, color=brand)
    ws["A2"] = f"{org_name} · {sim.get('name') or ''} · {str(sim.get('created_at', ''))[:16]}"
    names = [it["name"] for it in items]
    data = [[r["label"]] + [_cell(v) for v in r["values"]] for r in res.get("comparison") or []]
    table(ws, 4, ["Indicateur"] + names, data, [34] + [22] * len(names))
    row = 6 + len(data)
    for it in items:
        ws.cell(row=row, column=1, value=it["name"]).font = Font(bold=True, color=brand)
        row += 1
        for n in it["result"].get("notes", []) + [w["message"] for w in it["result"].get("lean", {}).get("warnings", [])]:
            ws.cell(row=row, column=1, value=n)
            row += 1
        row += 1
    for k, it in enumerate(items, 1):
        r = it["result"]
        ws = wb.create_sheet(f"S{k} stations"[:31])
        table(ws, 1, ["Station", "Ouvrières", "Pièces", "Occupation (%)", "Attente moy. (min)", "Encours max",
                      "Encours moyen", "Arrêt (min)", "Temps (min/pce)"],
              [[s["station"], ", ".join(it["result"]["plan"]["stations"][i]["workers"]) if i < len(r["plan"]["stations"]) else "",
                s["pieces"], s["utilization_pct"], s["avg_wait_min"], s["max_wip"], s["avg_wip"], s["down_min"],
                s["minutes_per_piece"]] for i, s in enumerate(r["stations"])],
              [9, 30, 9, 14, 16, 12, 13, 11, 14])
        ws = wb.create_sheet(f"S{k} ouvrières"[:31])
        table(ws, 1, ["Ouvrière", "Stations", "Occupation (%)", "Déplacements (m)"],
              [[w["name"], ", ".join(map(str, w["stations"])), w["utilization_pct"], w["walk_m"]] for w in r["workers"]],
              [24, 14, 14, 16])
        ws = wb.create_sheet(f"S{k} par heure"[:31])
        table(ws, 1, ["Heure", "Pièces finies"], [[f"H{i + 1}", n] for i, n in enumerate(r["hourly"])], [10, 14])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_pdf(sim: dict, org_name: str = "") -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    brand = colors.HexColor("#1F4E79")
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], textColor=brand, alignment=TA_LEFT, fontSize=17, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=brand, fontSize=12, spaceBefore=8, spaceAfter=4)
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=8.5, leading=11)
    small = ParagraphStyle("s", parent=body, fontSize=7.5, leading=9.5, textColor=colors.HexColor("#555555"))
    res = sim.get("results") or {}
    items = res.get("scenarios") or []
    buf = io.BytesIO()
    page = landscape(A4)
    doc = SimpleDocTemplate(buf, pagesize=page, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=12 * mm,
                            bottomMargin=12 * mm, title="Jumeau numérique", author="Textile Line Balancer")
    W = page[0] - 28 * mm
    story: list = [Paragraph("Jumeau numérique : comparaison de scénarios", h1),
                   Paragraph(_pdf_text(f"{org_name} · {sim.get('name') or 'Simulation'} · "
                                       f"{str(sim.get('created_at', ''))[:16].replace('T', ' ')} UTC"), small),
                   Spacer(1, 6)]
    head = ["Indicateur"] + [_pdf_text(it["name"]) for it in items]
    data = [head]
    for r in res.get("comparison") or []:
        row = [_pdf_text(r["label"])]
        for v in r["values"]:
            row.append("—" if v is None else (f"Station {v}" if r["key"] == "bottleneck" else _fmt(v, 1)))
        data.append(row)
    n = max(1, len(items))
    t = Table(data, colWidths=[W * .34] + [W * .66 / n] * n, repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), brand), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                           ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                           ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#DDDDDD"))]))
    story.append(t)
    for it in items:
        r = it["result"]
        story.append(Paragraph(_pdf_text(f"{it['name']} : {r['pieces']} pièces, goulot station {r['bottleneck']}"), h2))
        p = it["params"]
        story.append(Paragraph(_pdf_text(
            f"Paquets de {p.get('bundle_size')} pièces · efficience {_fmt(p.get('efficiency_pct'), 0)} % · "
            f"variabilité {_fmt(p.get('variability_pct'), 0)} % · {_fmt(p.get('shift_minutes'), 0)} min simulées"), small))
        for line in r.get("notes", []) + [w["message"] for w in r.get("lean", {}).get("warnings", [])]:
            story.append(Paragraph(_pdf_text("• " + line), body))
        data = [["Station", "Ouvrières", "Pièces", "Occupation", "Attente moy.", "Encours max", "Arrêt"]]
        for i, s in enumerate(r["stations"]):
            names = r["plan"]["stations"][i]["workers"] if i < len(r["plan"]["stations"]) else []
            data.append([str(s["station"]), Paragraph(_pdf_text(", ".join(names) or "—"), small), str(s["pieces"]),
                         f"{_fmt(s['utilization_pct'], 0)} %", f"{_fmt(s['avg_wait_min'], 1)} min",
                         str(s["max_wip"]), f"{_fmt(s['down_min'], 0)} min"])
        t = Table(data, colWidths=[W * .08, W * .36, W * .09, W * .12, W * .12, W * .12, W * .11], repeatRows=1)
        style = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E6EFFA")), ("FONTSIZE", (0, 0), (-1, -1), 8),
                 ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#DDDDDD"))]
        for i, s in enumerate(r["stations"], 1):
            if s["station"] == r["bottleneck"]:
                style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#FDF3E1")))
        t.setStyle(TableStyle(style))
        story.append(t)

    def footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.grey)
        canvas.drawString(14 * mm, 7 * mm, "Textile Line Balancer · linebalancer.netlify.app · simulation indicative")
        canvas.drawRightString(page[0] - 14 * mm, 7 * mm, f"Page {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
