"""Simulation à événements discrets (type FlexSim) : adaptateur entre calculs / plans d'atelier et
engine.des. Aucune logique métier ici (modèle, simulation et statistiques sont dans engine/des/).

- auto_model(...)       : modèle généré depuis le calcul + l'implantation (plan d'atelier si lié).
- prepare(...)          : modèle édité par l'utilisateur, borné et complété des chemins manquants.
- run(...)              : scénarios × réplications (trace d'animation pour la 1re réplication).
- build_xlsx / build_pdf: exports des tableaux de bord.
"""
from __future__ import annotations

import copy
import io
import json
from typing import Any, Optional

from engine.des import build_model, ensure_paths, normalize_model, run_experiment
from engine.des.builder import compute_paths
from engine.des.model import LIMITS, apply_overrides

from api.production import _fmt, _pdf_text

MODEL_MAX_BYTES = 2_000_000
TRACE_BUDGET = 90_000          # événements d'animation pour l'ensemble des scénarios (taille du résultat)
WORK_BUDGET = 60 * 480 * 30    # postes × minutes × réplications × scénarios (≈ 1 min sur Render gratuit)


def auto_model(plan: dict, layout: dict, workshop_plan: Optional[dict], settings: Optional[dict] = None) -> dict:
    return build_model(plan, layout, workshop_plan, settings)


def absent(model: dict, ids: list[str]) -> tuple[dict, list[str]]:
    """Absences : l'opérateur est retiré ; un poste vide est repris par l'opérateur du poste voisin
    le moins chargé (il tient alors les deux postes et marche entre eux)."""
    m = copy.deepcopy(model)
    gone = {str(i) for i in ids or []}
    notes: list[str] = []
    if not gone:
        return m, notes
    names = {o["id"]: o.get("name", o["id"]) for o in m.get("operators") or []}
    m["operators"] = [o for o in m.get("operators") or [] if o["id"] not in gone]
    route = [str(s["id"]) for s in m["stations"]]
    load = {o["id"]: 0.0 for o in m["operators"]}
    for st in m["stations"]:
        st["operators"] = [o for o in st.get("operators") or [] if o not in gone]
        for o in st["operators"]:
            load[o] = load.get(o, 0) + float(st.get("minutes") or 0) / max(1, len(st["operators"]))
    for o in m["operators"]:
        o["stations"] = [s for s in o.get("stations") or []]
    for st in m["stations"]:
        if st["operators"]:
            st["servers"] = max(1, min(int(st.get("servers") or 1), len(st["operators"])))
            continue
        i = route.index(str(st["id"]))
        neigh = [s for j in (i - 1, i + 1) if 0 <= j < len(route) for s in m["stations"] if str(s["id"]) == route[j]]
        cands = [o for s in neigh for o in s.get("operators") or []]
        if not cands:
            notes.append(f"Poste {st['id']} sans opérateur (personne à côté pour le reprendre).")
            continue
        o = min(cands, key=lambda x: (load.get(x, 0), x))
        st["operators"], st["servers"] = [o], 1
        load[o] = load.get(o, 0) + float(st.get("minutes") or 0)
        for op in m["operators"]:
            if op["id"] == o and str(st["id"]) not in op["stations"]:
                op["stations"].append(str(st["id"]))
        notes.append(f"{', '.join(names.get(g, g) for g in gone)} absente(s) : {names.get(o, o)} reprend aussi "
                     f"le poste {st['id']}.")
    return m, notes


def prepare(model: dict, workshop_plan: Optional[dict]) -> dict:
    if len(json.dumps(model)) > MODEL_MAX_BYTES:
        raise ValueError("Modèle trop volumineux.")
    normalize_model(model)          # validation (ModelError)
    return ensure_paths(copy.deepcopy(model), workshop_plan)


def run(model: dict, scenarios: list[dict], replications: int, workshop_plan: Optional[dict]) -> dict:
    scenarios = scenarios[: LIMITS["scenarios"]] or [{"name": "Référence", "overrides": {}}]
    n_st = len(model.get("stations") or [])
    T = float((model.get("shift") or {}).get("minutes") or 480)
    reps = max(1, min(LIMITS["replications"], int(replications)))
    # convoyeur : un cintre (souvent 1 pièce) = un « paquet » → bien plus d'événements
    cv_on = bool((model.get("conveyor") or {}).get("enabled")) or any(
        ((sc.get("overrides") or {}).get("conveyor") or {}).get("enabled") for sc in scenarios)
    if cv_on:
        n_st *= 4
    while reps > 1 and n_st * T * reps * len(scenarios) > WORK_BUDGET:
        reps -= 1
    items, notes_all = [], []
    budget = TRACE_BUDGET // len(scenarios)
    for sc in scenarios:
        base, notes = absent(model, sc.get("absent") or [])
        m = apply_overrides(base, sc.get("overrides") or {})
        if m.get("transporters") or notes:
            m["paths"] = {**compute_paths(m, workshop_plan, bool(m.get("transporters"))), **(m.get("paths") or {})}
        m.setdefault("settings", {})["max_trace_events"] = budget
        exp = run_experiment(m, [{"name": sc.get("name") or "Scénario", "overrides": {}}], reps)
        it = exp["scenarios"][0]
        it["overrides"], it["absent"] = sc.get("overrides") or {}, sc.get("absent") or []
        it["result"]["notes"] = notes + it["result"].get("notes", [])
        items.append(it)
        notes_all += notes
    from engine.des.experiment import comparison
    return {"engine": "des-3.0", "replications": reps, "scenarios": items, "comparison": comparison(items)}


# --------------------------------------------------------------------------- exports
STATE_LABELS = [("work", "Travail"), ("starved", "Attente matière"), ("blocked", "Bloqué aval"), ("down", "Panne"),
                ("setup", "Mise en route"), ("wait_operator", "Attente opérateur"), ("break", "Pause"),
                ("transfer", "Transfert")]


def _ci(v: Any) -> str:
    if not isinstance(v, dict):
        return "—" if v is None else str(v)
    if v.get("mean") is None:
        return "—"
    if isinstance(v["mean"], str):
        return f"Poste {v['mean']}"
    if v.get("n", 1) > 1 and v.get("lo") is not None:
        return f"{_fmt(v['mean'], 1)} [{_fmt(v['lo'], 1)} ; {_fmt(v['hi'], 1)}]"
    return _fmt(v["mean"], 1)


def build_xlsx(sim: dict, org_name: str = "") -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    res = sim.get("results") or {}
    items = res.get("scenarios") or []
    wb = Workbook()
    head = PatternFill("solid", fgColor="1F4E79")
    white = Font(color="FFFFFF", bold=True)

    def header(ws, row):
        ws.append(row)
        for c in ws[ws.max_row]:
            c.fill, c.font = head, white

    ws = wb.active
    ws.title = "Comparaison"
    ws.append([f"Simulation à événements discrets — {org_name} — {sim.get('name') or ''}"])
    ws.append([f"{res.get('replications', 1)} réplication(s) par scénario ; [ ] = intervalle de confiance 95 %"])
    header(ws, ["Indicateur"] + [it["name"] for it in items])
    for r in res.get("comparison") or []:
        ws.append([r["label"]] + [_ci(v) for v in r["values"]])
    ws.column_dimensions["A"].width = 36
    for it in items:
        r = it["result"]
        w2 = wb.create_sheet(f"Postes {it['name']}"[:31])
        header(w2, ["Poste", "Opérateurs", "Temps (min/pc)", "Pièces"] + [lbl + " %" for _, lbl in STATE_LABELS]
               + ["File moy. (paquets)", "File max", "Défauts"])
        for s in r["stations"]:
            w2.append([s["label"], ", ".join(s["operators"]), s["minutes"], s["pieces"]]
                      + [s["states"].get(k, 0) for k, _ in STATE_LABELS] + [s["queue_avg"], s["queue_max"], s["defects"]])
        w3 = wb.create_sheet(f"Opérateurs {it['name']}"[:31])
        header(w3, ["Opérateur", "Postes", "Occupation %", "Marche %", "Transport %", "Inactif %", "Pause %",
                    "Distance à pied (m)", "Dont paquets portés (m)"])
        for o in r["operators"]:
            st = o["states"]
            w3.append([o["name"], ", ".join(o["stations"]), o["utilization_pct"], st["walk"], st["carry"], st["idle"],
                       st["break"], o["walk_m"], o["carry_m"]])
        for t in r.get("transporters") or []:
            w3.append([t["name"] + " (transporteur)", f"{t['loads']} enlèvements", t["utilization_pct"], "", "", "",
                       "", t["distance_m"], ""])
        w4 = wb.create_sheet(f"Débit {it['name']}"[:31])
        header(w4, ["Heure", "Pièces", "Objectif"])
        tgt = r["throughput"].get("target_per_hour")
        for h, n in enumerate(r["throughput"]["hourly"]):
            w4.append([h + 1, n, tgt])
        w4.append([])
        header(w4, ["Minute", "Encours (pièces)"])
        for t, v in r["wip_series"]:
            w4.append([t, v])
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
    from reportlab.graphics.shapes import Drawing, Rect, String

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
                            bottomMargin=12 * mm, title="Simulation", author="Textile Line Balancer")
    W = page[0] - 28 * mm
    story: list = [Paragraph("Simulation de l'atelier : tableau de bord", h1),
                   Paragraph(_pdf_text(f"{org_name} · {sim.get('name') or 'Simulation'} · "
                                       f"{res.get('replications', 1)} réplication(s) · intervalle de confiance 95 % entre "
                                       f"crochets · linebalancer.onrender.com"), small), Spacer(1, 6)]
    data = [["Indicateur"] + [_pdf_text(it["name"]) for it in items]]
    for r in res.get("comparison") or []:
        data.append([_pdf_text(r["label"])] + [_pdf_text(_ci(v)) for v in r["values"]])
    n = max(1, len(items))
    t = Table(data, colWidths=[W * .3] + [W * .7 / n] * n, repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), brand), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                           ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                           ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.HexColor("#DDDDDD"))]))
    story.append(t)
    palette = ["#2e9e5b", "#e8c547", "#f08a24", "#d64541", "#3b7dd8", "#9b59b6", "#95a5a6", "#16a085"]
    for it in items:
        r = it["result"]
        k = r["kpis"]
        story.append(Paragraph(_pdf_text(f"{it['name']} : {k['pieces']} pièces ({_fmt(k['per_hour'], 1)}/h), "
                                         f"goulot poste {k['bottleneck']}, traversée {_fmt(k['lead_time_avg'], 0)} min"), h2))
        for line in r.get("notes") or []:
            story.append(Paragraph(_pdf_text("• " + line), body))
        # barres d'états par poste (comme le graphique d'états de FlexSim)
        sts = r["stations"][:60]
        row_h, label_w = 9, 60
        d = Drawing(W, row_h * len(sts) + 22)
        bar_w = W - label_w - 10
        for i, s in enumerate(sts):
            y = d.height - 14 - (i + 1) * row_h
            d.add(String(0, y + 2, _pdf_text(s["label"])[:14], fontSize=6.5))
            x = label_w
            for j, (key, _) in enumerate(STATE_LABELS):
                w = bar_w * s["states"].get(key, 0) / 100
                if w > 0:
                    d.add(Rect(x, y, w, row_h - 2, fillColor=colors.HexColor(palette[j]), strokeColor=None))
                    x += w
        lx = label_w
        for j, (_, lbl) in enumerate(STATE_LABELS):
            d.add(Rect(lx, d.height - 8, 7, 6, fillColor=colors.HexColor(palette[j]), strokeColor=None))
            d.add(String(lx + 9, d.height - 7.5, _pdf_text(lbl), fontSize=6.5))
            lx += 78
        story.append(d)
        data = [["Opérateur", "Postes", "Occupation", "Marche", "Distance à pied"]]
        for o in r["operators"][:80]:
            data.append([_pdf_text(o["name"]), ", ".join(o["stations"]), f"{_fmt(o['utilization_pct'], 1)} %",
                         f"{_fmt(o['states']['walk'], 1)} %", f"{_fmt(o['walk_m'], 0)} m"])
        t = Table(data, colWidths=[W * .3, W * .25, W * .15, W * .15, W * .15], repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), brand), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                               ("FONTSIZE", (0, 0), (-1, -1), 7.5), ("ALIGN", (2, 0), (-1, -1), "RIGHT")]))
        story.append(Spacer(1, 4))
        story.append(t)
    doc.build(story)
    return buf.getvalue()
