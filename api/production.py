"""Suivi de production en direct : plan figé d'une session et indicateurs temps réel.

Calculs de pilotage (pas de logique d'équilibrage : le moteur n'est pas sollicité).
Entrées = lignes telles qu'enregistrées en base (production_sessions / production_entries).

Définitions :
- réalisé ligne = pièces déclarées à la DERNIÈRE station (pièces finies) ;
- objectif à date = objectif pièces/heure × temps écoulé dans le poste ;
- minutes produites (station) = pièces × temps de la station par pièce (calcul de référence) ;
- minutes de présence = opérateurs × temps écoulé − arrêts « absence » ;
- efficience = minutes produites / minutes de présence ;
- goulot calculé = station la plus chargée du calcul (temps / opérateurs) ;
- goulot observé = station qui a sorti le moins de pièces (égalité : plus d'arrêts) ;
- encours entre deux stations = pièces de la station amont − pièces de la station aval.
"""
from __future__ import annotations

import io
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable, Optional
from zoneinfo import ZoneInfo

DOWNTIME_REASONS = {
    "panne": "Panne machine",
    "manque_fourniture": "Manque de fourniture",
    "absence": "Absence",
    "changement_modele": "Changement de modèle",
    "autre": "Autre",
}
UNDER_TARGET = 0.80          # alerte : station sous 80 % de l'objectif à date
LONG_STOP_MIN = 15.0         # alerte : arrêt de plus de 15 minutes
MIN_ELAPSED_FOR_ALERT = 15.0


# --------------------------------------------------------------------------- plan
def balance_result(run: dict) -> Optional[dict]:
    res = run.get("result") or {}
    if run.get("kind") == "min_cycle":
        return res.get("result")
    return res or None


def build_plan(run: dict, problem: Optional[dict]) -> dict:
    """Copie figée des stations du calcul (opérations, ouvriers, temps) pour la session."""
    r = balance_result(run) or {}
    ops = {o["id"]: o for o in (problem or {}).get("operations", [])}
    workers = {w["id"]: w for w in (problem or {}).get("workers", [])}
    stations = []
    for sd in r.get("station_details") or []:
        shares = sd.get("shares") or {}
        total = float(sd.get("total_time") or 0)
        op_ids = list(sd.get("operations") or [])
        op_list = []
        for oid in op_ids:
            minutes = shares.get(oid, ops.get(oid, {}).get("duration"))
            if minutes is None and len(op_ids) == 1:
                minutes = total
            op_list.append({"id": oid, "name": ops.get(oid, {}).get("name", ""),
                            "minutes": round(float(minutes or 0), 4), "shared": oid in shares})
        worker_ids = list(sd.get("worker_ids") or [])
        names = list(sd.get("workers") or [workers.get(w, {}).get("name", w) for w in worker_ids])
        operators = max(1, int(sd.get("parallel") or 1))
        stations.append({
            "station": int(sd.get("station")), "operations": op_list, "workers": names,
            "worker_ids": worker_ids, "operators": operators, "minutes": round(total, 4),
            "load_pct": sd.get("load_pct"), "machine_types": sd.get("machine_types") or [],
            "workstations": sd.get("workstations") or ([sd["workstation"]] if sd.get("workstation") else []),
        })
    stations.sort(key=lambda s: s["station"])
    bottleneck = max(stations, key=lambda s: s["minutes"] / s["operators"], default=None)
    return {
        "stations": stations,
        "cycle_time": r.get("actual_cycle_time") or None,
        "takt_time": r.get("target_cycle_time") or (problem or {}).get("target_cycle_time"),
        "sam_total": round(sum(s["minutes"] for s in stations), 4),
        "operators": sum(s["operators"] for s in stations),
        "bottleneck_station": bottleneck["station"] if bottleneck else None,
        "problem_name": (problem or {}).get("name", ""),
        "solver": r.get("solver", ""),
    }


def default_target_per_hour(plan: dict) -> Optional[float]:
    c = plan.get("cycle_time") or plan.get("takt_time")
    return round(60.0 / float(c), 1) if c else None


# --------------------------------------------------------------------------- temps
def _dt(v: Any) -> Optional[datetime]:
    if v is None or isinstance(v, datetime):
        return v
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _tz(session: dict) -> ZoneInfo:
    try:
        return ZoneInfo(session.get("timezone") or "Africa/Tunis")
    except Exception:  # noqa: BLE001
        return ZoneInfo("Africa/Tunis")


def shift_window(session: dict) -> tuple[datetime, datetime]:
    tz = _tz(session)
    d = session.get("session_date")
    d = date.fromisoformat(d) if isinstance(d, str) else d
    st = session.get("shift_start") or "08:00"
    st = time.fromisoformat(st) if isinstance(st, str) else st
    start = datetime.combine(d, st, tz)
    return start, start + timedelta(hours=float(session.get("shift_hours") or 8))


def local_hour(session: dict, when: Optional[datetime] = None) -> int:
    return (when or datetime.now(timezone.utc)).astimezone(_tz(session)).hour


def _stop_time(session: dict, now: datetime) -> datetime:
    """Fin du décompte : maintenant, la fermeture de la session ou la fin du poste."""
    _, end = shift_window(session)
    t = now
    if session.get("status") == "closed":
        t = _dt(session.get("closed_at")) or end
    return min(t, end)


# --------------------------------------------------------------------------- tableau de bord
def _r(v: Optional[float], d: int = 1) -> Optional[float]:
    return None if v is None else round(v, d)


def dashboard(session: dict, entries: Iterable[dict], now: Optional[datetime] = None) -> dict:
    now = now or datetime.now(timezone.utc)
    plan = session.get("plan") or {}
    stations = plan.get("stations") or []
    order = [s["station"] for s in stations]
    by_st = {s["station"]: s for s in stations}
    target_h = float(session.get("target_per_hour") or 0)
    start, end = shift_window(session)
    stop = _stop_time(session, now)
    elapsed = max(0.0, (stop - start).total_seconds() / 60)
    shift_min = (end - start).total_seconds() / 60
    tz = _tz(session)

    # Créneaux horaires du poste (heure locale) + toute heure ayant reçu une saisie.
    hours: list[int] = []
    t = start.replace(minute=0, second=0, microsecond=0)
    while t < end:
        hours.append(t.astimezone(tz).hour)
        t += timedelta(hours=1)
    hour_target: dict[int, float] = {}
    t = start.replace(minute=0, second=0, microsecond=0)
    for h in hours:
        a, b = max(t, start), min(t + timedelta(hours=1), stop)
        hour_target[h] = target_h * max(0.0, (b - a).total_seconds() / 3600)
        t += timedelta(hours=1)

    live = [e for e in entries if not e.get("voided")]
    for e in live:
        h = int(e.get("slot_hour", 0))
        if h not in hours:
            hours.append(h)
            hour_target.setdefault(h, 0.0)
        if e.get("station") not in by_st:
            st_no = int(e.get("station"))
            by_st[st_no] = {"station": st_no, "operations": [], "workers": [], "operators": 1, "minutes": 0.0}
            order.append(st_no)
    order.sort()

    def stop_minutes(e: dict) -> tuple[float, bool]:
        if not e.get("downtime_reason"):
            return 0.0, False
        if e.get("downtime_minutes") is not None:
            return float(e["downtime_minutes"]), False
        s = _dt(e.get("downtime_start"))
        if s is None:
            return 0.0, False
        endt = stop if session.get("status") == "closed" else now
        return max(0.0, (endt - s).total_seconds() / 60), True

    st_stats: dict[int, dict] = {
        n: {"station": n, "pieces": 0, "defects": 0, "rework": 0, "downtime": 0.0, "absence": 0.0,
            "ongoing_stop": None, "by_hour": {h: 0 for h in hours}} for n in order}
    reasons = {k: 0.0 for k in DOWNTIME_REASONS}
    reasons_hour: dict[int, float] = {h: 0.0 for h in hours}
    alerts: list[dict] = []
    stops_list: list[dict] = []
    for e in live:
        s = st_stats[int(e["station"])]
        h = int(e.get("slot_hour", 0))
        s["pieces"] += int(e.get("pieces") or 0)
        s["by_hour"][h] = s["by_hour"].get(h, 0) + int(e.get("pieces") or 0)
        s["defects"] += int(e.get("defects") or 0)
        s["rework"] += int(e.get("rework") or 0)
        mins, ongoing = stop_minutes(e)
        if e.get("downtime_reason"):
            reason = e["downtime_reason"]
            s["downtime"] += mins
            reasons[reason] = reasons.get(reason, 0.0) + mins
            reasons_hour[h] = reasons_hour.get(h, 0.0) + mins
            if reason == "absence":
                s["absence"] += mins
            item = {"station": s["station"], "reason": reason, "label": DOWNTIME_REASONS.get(reason, reason),
                    "minutes": _r(mins), "ongoing": ongoing, "start": e.get("downtime_start") or e.get("entered_at"),
                    "slot_hour": h, "comment": e.get("comment", ""), "id": e.get("id"),
                    "client_id": e.get("client_id")}
            stops_list.append(item)
            if ongoing:
                s["ongoing_stop"] = item
            if mins > LONG_STOP_MIN:
                alerts.append({"level": "danger" if ongoing else "warning", "kind": "long_stop",
                               "station": s["station"],
                               "message": (f"Station {s['station']} : arrêt en cours depuis {mins:.0f} min "
                                           f"({item['label'].lower()})") if ongoing else
                                          (f"Station {s['station']} : arrêt de {mins:.0f} min à {h} h "
                                           f"({item['label'].lower()})")})

    expected = target_h * elapsed / 60
    last = order[-1] if order else None
    output = st_stats[last]["pieces"] if last is not None else 0
    rows = []
    produced_total = presence_total = 0.0
    for n in order:
        s, p = st_stats[n], by_st[n]
        ops = max(1, int(p.get("operators") or 1))
        produced = s["pieces"] * float(p.get("minutes") or 0)
        presence = max(0.0, ops * elapsed - s["absence"])
        produced_total += produced
        presence_total += presence
        run_min = max(0.0, elapsed - s["downtime"] / ops)
        real_pp = (run_min * ops / s["pieces"]) if s["pieces"] else None
        pct = (s["pieces"] / expected) if expected >= 1 else None
        rows.append({
            "station": n, "operations": [o["id"] for o in p.get("operations", [])],
            "workers": p.get("workers", []), "operators": ops,
            "planned_minutes": p.get("minutes"), "planned_per_operator": _r(float(p.get("minutes") or 0) / ops, 3),
            "pieces": s["pieces"], "expected": _r(expected), "pct_target": _r(pct * 100 if pct is not None else None),
            "defects": s["defects"], "rework": s["rework"], "downtime_minutes": _r(s["downtime"]),
            "produced_minutes": _r(produced), "presence_minutes": _r(presence),
            "efficiency": _r(produced / presence * 100 if presence else None),
            "real_minutes_per_piece": _r(real_pp, 3),
            "by_hour": [{"hour": h, "pieces": s["by_hour"].get(h, 0), "target": _r(hour_target.get(h, 0.0))}
                        for h in hours],
            "ongoing_stop": s["ongoing_stop"],
        })
        if (pct is not None and elapsed >= MIN_ELAPSED_FOR_ALERT and pct < UNDER_TARGET
                and session.get("status") == "open"):
            alerts.append({"level": "warning", "kind": "under_target", "station": n,
                           "message": f"Station {n} à {pct * 100:.0f} % de l'objectif "
                                      f"({s['pieces']} / {expected:.0f} pièces)"})

    wip = [{"between": [a, b], "pieces": max(0, st_stats[a]["pieces"] - st_stats[b]["pieces"])}
           for a, b in zip(order, order[1:])]
    observed = None
    if order and any(st_stats[n]["pieces"] for n in order):
        observed = min(order, key=lambda n: (st_stats[n]["pieces"], -st_stats[n]["downtime"],
                                             -float(by_st[n].get("minutes") or 0)))
    hourly = [{"hour": h, "target": _r(hour_target.get(h, 0.0)),
               "output": st_stats[last]["by_hour"].get(h, 0) if last is not None else 0,
               "downtime_minutes": _r(reasons_hour.get(h, 0.0))} for h in hours]
    defects = sum(s["defects"] for s in st_stats.values())
    rework = sum(s["rework"] for s in st_stats.values())
    alerts.sort(key=lambda a: (a["level"] != "danger", a["level"] != "warning"))
    return {
        "session_id": session.get("id"), "status": session.get("status"),
        "now": now.isoformat(), "shift_start": start.isoformat(), "shift_end": end.isoformat(),
        "elapsed_minutes": _r(elapsed), "shift_minutes": _r(shift_min),
        "current_hour": local_hour(session, now),
        "target_per_hour": target_h, "target_shift": _r(target_h * shift_min / 60),
        "expected_to_date": _r(expected), "output": output,
        "pct_target": _r(output / expected * 100 if expected >= 1 else None),
        "efficiency": _r(produced_total / presence_total * 100 if presence_total else None),
        "produced_minutes": _r(produced_total), "presence_minutes": _r(presence_total),
        "bottleneck_planned": plan.get("bottleneck_station"), "bottleneck_observed": observed,
        "wip": wip, "wip_total": sum(w["pieces"] for w in wip),
        "defects": defects, "rework": rework,
        "defect_rate": _r(defects / output * 100 if output else None),
        "downtime_by_reason": [{"reason": k, "label": DOWNTIME_REASONS.get(k, k), "minutes": _r(v)}
                               for k, v in reasons.items()],
        "downtime_total": _r(sum(reasons.values())),
        "hourly": hourly, "stations": rows, "stops": stops_list, "alerts": alerts,
        "cycle_time": plan.get("cycle_time"), "takt_time": plan.get("takt_time"),
    }


# --------------------------------------------------------------------------- exports
def _fmt(v: Any, d: int = 1) -> str:
    if v is None:
        return "—"
    s = f"{float(v):,.{d}f}".replace(",", " ").replace(".", ",")
    if "," in s:
        s = s.rstrip("0").rstrip(",")
    return s


def summary_rows(session: dict, dash: dict) -> list[tuple[str, str]]:
    bn_o, bn_p = dash.get("bottleneck_observed"), dash.get("bottleneck_planned")
    return [
        ("Réalisé (pièces finies)", str(dash["output"])),
        ("Objectif à date", f"{_fmt(dash['expected_to_date'], 0)} pièces"),
        ("Taux de réalisation", f"{_fmt(dash['pct_target'], 0)} %"),
        ("Objectif du poste", f"{_fmt(dash['target_shift'], 0)} pièces ({_fmt(dash['target_per_hour'])} / h)"),
        ("Efficience", f"{_fmt(dash['efficiency'])} %"),
        ("Goulot calculé", f"Station {bn_p}" if bn_p else "—"),
        ("Goulot observé", f"Station {bn_o}" if bn_o else "—"),
        ("Encours total", f"{dash['wip_total']} pièces"),
        ("Défauts / retouches", f"{dash['defects']} / {dash['rework']}"),
        ("Arrêts cumulés", f"{_fmt(dash['downtime_total'], 0)} min"),
    ]


def _meta(session: dict, org_name: str) -> list[tuple[str, str]]:
    return [("Atelier", org_name or "—"), ("Ligne", session.get("line_name") or "—"),
            ("Modèle", session.get("model") or "—"), ("Date", str(session.get("session_date", ""))),
            ("Poste", f"{str(session.get('shift_start', ''))[:5]} · {_fmt(session.get('shift_hours'))} h"),
            ("Statut", "Fermée" if session.get("status") == "closed" else "Ouverte")]


def build_xlsx(session: dict, dash: dict, entries: list[dict], org_name: str = "") -> bytes:
    from openpyxl import Workbook
    from openpyxl.chart import BarChart, LineChart, Reference
    from openpyxl.styles import Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    brand = "1F4E79"
    hf, hfill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor=brand)
    thin = Side(style="thin", color="D9D9D9")
    border = Border(top=thin, bottom=thin, left=thin, right=thin)

    def table(ws, row: int, cols: list[str], data: list[list[Any]], widths: list[int]):
        for i, c in enumerate(cols, 1):
            cell = ws.cell(row=row, column=i, value=c)
            cell.font, cell.fill, cell.border = hf, hfill, border
        for r_i, vals in enumerate(data, row + 1):
            for j, v in enumerate(vals, 1):
                ws.cell(row=r_i, column=j, value=v).border = border
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.freeze_panes = ws.cell(row=row + 1, column=1)

    wb = Workbook()
    ws = wb.active
    ws.title = "Synthèse"
    ws["A1"] = "Suivi de production de la journée"
    ws["A1"].font = Font(bold=True, size=16, color=brand)
    row = 3
    for k, v in _meta(session, org_name) + [("", "")] + summary_rows(session, dash):
        ws.cell(row=row, column=1, value=k).font = Font(bold=True)
        ws.cell(row=row, column=2, value=v)
        row += 1
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 28, 40

    hours = [h["hour"] for h in dash["hourly"]]
    ws = wb.create_sheet("Par heure")
    data = [[f"{h['hour']} h", h["output"], h["target"], h["downtime_minutes"]] for h in dash["hourly"]]
    table(ws, 1, ["Heure", "Réalisé (pièces finies)", "Objectif", "Arrêts (min)"], data, [10, 22, 12, 14])
    if data:
        n = len(data) + 1
        bar = BarChart()
        bar.title, bar.y_axis.title = "Réalisé / objectif par heure", "pièces"
        bar.add_data(Reference(ws, min_col=2, min_row=1, max_row=n), titles_from_data=True)
        bar.set_categories(Reference(ws, min_col=1, min_row=2, max_row=n))
        line = LineChart()
        line.add_data(Reference(ws, min_col=3, min_row=1, max_row=n), titles_from_data=True)
        bar += line
        bar.height, bar.width = 9, 18
        ws.add_chart(bar, "F2")

    ws = wb.create_sheet("Par station")
    data = [[s["station"], ", ".join(s["operations"]), ", ".join(s["workers"]), s["operators"],
             s["planned_minutes"], s["pieces"], s["expected"], s["pct_target"], s["efficiency"],
             s["real_minutes_per_piece"], s["defects"], s["rework"], s["downtime_minutes"]] for s in dash["stations"]]
    table(ws, 1, ["Station", "Opérations", "Ouvriers", "Opérateurs", "Temps prévu (min/pce)", "Pièces",
                  "Objectif à date", "% objectif", "Efficience (%)", "Temps réel (min/pce)", "Défauts",
                  "Retouches", "Arrêts (min)"], data, [9, 26, 26, 11, 14, 9, 13, 11, 13, 14, 9, 10, 11])

    ws = wb.create_sheet("Stations × heures")
    data = [[s["station"]] + [b["pieces"] for b in s["by_hour"]] + [s["pieces"]] for s in dash["stations"]]
    table(ws, 1, ["Station"] + [f"{h} h" for h in hours] + ["Total"], data, [9] + [8] * (len(hours) + 1))

    ws = wb.create_sheet("Arrêts")
    data = [[s["station"], s["label"], s["minutes"], "en cours" if s["ongoing"] else "", f"{s['slot_hour']} h",
             s.get("comment", "")] for s in dash["stops"]]
    data += [[], ["Total par motif"]] + [[None, d["label"], d["minutes"]] for d in dash["downtime_by_reason"]]
    table(ws, 1, ["Station", "Motif", "Durée (min)", "État", "Heure", "Commentaire"], data, [9, 24, 12, 10, 8, 40])

    ws = wb.create_sheet("Saisies")
    data = [[e.get("entered_at"), e.get("slot_hour"), e.get("station"), e.get("worker_id") or "", e.get("pieces"),
             e.get("defects"), e.get("rework"), DOWNTIME_REASONS.get(e.get("downtime_reason") or "", ""),
             e.get("downtime_minutes"), e.get("comment", ""), "annulée" if e.get("voided") else ""]
            for e in sorted(entries, key=lambda e: str(e.get("entered_at")))]
    table(ws, 1, ["Horodatage (UTC)", "Heure", "Station", "Ouvrier", "Pièces", "Défauts", "Retouches",
                  "Arrêt", "Durée (min)", "Commentaire", "État"], data, [26, 8, 9, 12, 8, 9, 10, 22, 11, 30, 10])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _pdf_text(t: str) -> str:
    t = t.replace("→", "»").replace("≥", ">=").replace("≤", "<=").replace("×", "x")
    return t.encode("cp1252", "ignore").decode("cp1252").strip()


def build_pdf(session: dict, dash: dict, org_name: str = "") -> bytes:
    from reportlab.graphics.shapes import Drawing, Line, PolyLine, Rect, String
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    brand = colors.HexColor("#1F4E79")
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], textColor=brand, alignment=TA_LEFT, fontSize=18, spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=brand, fontSize=12, spaceBefore=8, spaceAfter=4)
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=8.5, leading=11)
    small = ParagraphStyle("s", parent=body, fontSize=7.5, leading=9.5, textColor=colors.HexColor("#555555"))
    buf = io.BytesIO()
    page = landscape(A4)
    doc = SimpleDocTemplate(buf, pagesize=page, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=12 * mm,
                            bottomMargin=12 * mm, title="Suivi de production", author="Textile Line Balancer")
    W = page[0] - 28 * mm
    story: list = [Paragraph("Suivi de production de la journée", h1),
                   Paragraph(_pdf_text(" · ".join(f"{k} : {v}" for k, v in _meta(session, org_name))), small),
                   Spacer(1, 6)]
    kp = summary_rows(session, dash)
    cells = [[Paragraph(_pdf_text(f"<font size=7 color='#666666'>{k}</font><br/><b>{v}</b>"), body)
              for k, v in kp[i:i + 5]] for i in range(0, len(kp), 5)]
    t = Table(cells, colWidths=[W / 5] * 5)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F4F6F9")),
                           ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#DDDDDD")),
                           ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.white),
                           ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(t)

    hourly = dash["hourly"]
    if hourly:
        story.append(Paragraph("Réalisé et objectif par heure", h2))
        H, padl, padb = 55 * mm, 26, 16
        d = Drawing(W, H)
        top = max([1.0] + [h["output"] for h in hourly] + [h["target"] or 0 for h in hourly]) * 1.15
        pw, ph = W - padl - 4, H - padb - 8
        bw = pw / len(hourly)
        y = lambda v: padb + ph * v / top  # noqa: E731
        for tv in (0, top / 2, top / 1.15):
            d.add(Line(padl, y(tv), W - 4, y(tv), strokeColor=colors.HexColor("#EEEEEE"), strokeWidth=0.5))
            d.add(String(padl - 3, y(tv) - 3, _fmt(tv, 0), fontSize=6.5, textAnchor="end", fillColor=colors.grey))
        pts = []
        for i, h in enumerate(hourly):
            tg = h["target"] or 0
            ok = tg and h["output"] >= UNDER_TARGET * tg
            d.add(Rect(padl + i * bw + bw * .2, padb, bw * .6, y(h["output"]) - padb, strokeColor=None,
                       fillColor=colors.HexColor("#2F9E6E" if ok else "#E0A93B")))
            d.add(String(padl + i * bw + bw / 2, padb - 9, f"{h['hour']} h", fontSize=6.5, textAnchor="middle",
                         fillColor=colors.grey))
            pts += [padl + i * bw + bw / 2, y(tg)]
        if len(pts) >= 4:
            d.add(PolyLine(pts, strokeColor=brand, strokeWidth=1.2, strokeDashArray=[3, 2]))
        story.append(d)

    story.append(Paragraph("Par station", h2))
    data = [["Station", "Opérations", "Ouvriers", "Pièces", "% objectif", "Efficience", "Défauts", "Arrêts (min)"]]
    for s in dash["stations"]:
        data.append([str(s["station"]), Paragraph(_pdf_text(", ".join(s["operations"])), small),
                     Paragraph(_pdf_text(", ".join(s["workers"]) or "—"), small), str(s["pieces"]),
                     f"{_fmt(s['pct_target'], 0)} %", f"{_fmt(s['efficiency'], 0)} %", str(s["defects"]),
                     _fmt(s["downtime_minutes"], 0)])
    t = Table(data, colWidths=[W * .07, W * .30, W * .23, W * .07, W * .09, W * .09, W * .07, W * .08], repeatRows=1)
    style = [("BACKGROUND", (0, 0), (-1, 0), brand), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
             ("FONTSIZE", (0, 0), (-1, -1), 8), ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#DDDDDD"))]
    for i, s in enumerate(dash["stations"], 1):
        if s["pct_target"] is not None and s["pct_target"] < UNDER_TARGET * 100:
            style.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#FDF3E1")))
    t.setStyle(TableStyle(style))
    story.append(t)

    story.append(Paragraph("Arrêts par motif", h2))
    story.append(Paragraph(_pdf_text(" · ".join(f"{d['label']} : {_fmt(d['minutes'], 0)} min"
                                                for d in dash["downtime_by_reason"])), body))
    if dash["alerts"]:
        story.append(Paragraph("Alertes", h2))
        for a in dash["alerts"]:
            story.append(Paragraph(_pdf_text(a["message"]), body))

    def footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.grey)
        canvas.drawString(14 * mm, 7 * mm, "Textile Line Balancer · linebalancer.onrender.com")
        canvas.drawRightString(page[0] - 14 * mm, 7 * mm, f"Page {doc_.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()

