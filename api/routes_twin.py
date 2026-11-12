"""Routes « jumeau numérique » : implantation 2D, simulations « et si », réel vs simulé.

  GET  /v1/orgs/{org}/runs/{id}/twin                plan + implantation + sessions + simulations
  PUT  /v1/orgs/{org}/runs/{id}/layout              enregistrer l'implantation (ligne / U / libre)
  POST /v1/orgs/{org}/runs/{id}/simulate            lancer 1–3 scénarios (tâche de fond) -> 202
  GET  /v1/orgs/{org}/runs/{id}/simulations         historique des simulations du calcul
  GET  /v1/orgs/{org}/simulations/{sid}             statut + résultats
  GET  /v1/orgs/{org}/simulations/{sid}/export.xlsx|pdf
  GET  /v1/orgs/{org}/runs/{id}/twin/sync?session_id=…&order_qty=…&order_done=…
  POST /v1/orgs/{org}/runs/{id}/twin/plan           placer les stations sur les machines d'un plan d'atelier
                                                    (association auto + manuelle, distances par les allées)

Sécurité : jeton utilisateur transmis à PostgREST (RLS par atelier).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import Response

from api import production, twin
from api.auth import Principal, SupabaseAuth
from api.jobs import JobQueue
from api.routes_saas import WRITE_ROLES, bearer_principal
from api.routes_workshop import placement
from api.schemas import LayoutIn, PlanPlacementIn, SimulateRequest
from api.store import StoreError, SupabaseStore

log = logging.getLogger("tlb.api")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def register(app: FastAPI, queue: JobQueue, auth: SupabaseAuth, store: SupabaseStore) -> None:
    principal = bearer_principal(auth)

    def call(fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except StoreError as e:
            raise HTTPException(e.status, e.message)

    def uid(value: Optional[str], what: str) -> str:
        try:
            return str(UUID(str(value)))
        except (ValueError, TypeError):
            raise HTTPException(404, f"{what} introuvable.")

    def membership(org_id: str, p: Principal, write: bool = False) -> str:
        org_id = uid(org_id, "Atelier")
        role = call(store.member_role, p.token, org_id, p.user_id)
        if role is None:
            raise HTTPException(404, "Atelier introuvable.")
        if write and role not in WRITE_ROLES:
            raise HTTPException(403, "Votre rôle (lecteur) ne permet pas de modifier le jumeau numérique.")
        return org_id

    def load_plan(org_id: str, run_id: str, p: Principal) -> tuple[dict, dict, Optional[dict]]:
        run = call(store.get_run, p.token, org_id, uid(run_id, "Calcul"))
        if run.get("status") != "done" or not production.balance_result(run):
            raise HTTPException(409, "Le calcul doit être terminé avec une répartition des stations.")
        problem = None
        if run.get("problem_id"):
            try:
                problem = store.get_problem(p.token, org_id, run["problem_id"]).get("payload")
            except StoreError:
                problem = None
        plan = twin.twin_plan(run, problem)
        if not plan["stations"]:
            raise HTTPException(409, "Ce calcul ne contient aucune station.")
        return run, plan, problem

    def saved_layout(org_id: str, run_id: str, p: Principal) -> Optional[dict]:
        try:
            return store.get_layout(p.token, org_id, run_id)
        except StoreError as e:
            log.warning("Implantation illisible : %s", e.message)
            return None

    def plan_row(org_id: str, plan_id: str, p: Principal) -> dict:
        return call(store.get_plan, p.token, org_id, uid(plan_id, "Plan d'atelier"))

    def effective_layout(org_id: str, plan: dict, saved: Optional[dict], p: Principal,
                         kind: str = "line") -> tuple[dict, Optional[dict]]:
        """Implantation de simulation : plan d'atelier si l'implantation y est liée, sinon positions."""
        if saved and saved.get("plan_id"):
            try:
                row = store.get_plan(p.token, org_id, saved["plan_id"])
            except StoreError:
                row = None
            if row:
                pl = placement(plan["stations"], row, saved.get("assignment") or {})
                return pl["layout"], pl
        return twin.layout_for(plan, saved, kind), None

    def org_name(org_id: str, p: Principal) -> str:
        return next((o.get("name", "") for o in call(store.my_orgs, p.token, p.user_id)
                     if o.get("id") == org_id), "")

    @app.get("/v1/orgs/{org_id}/runs/{run_id}/twin", tags=["jumeau"])
    def get_twin(org_id: str, run_id: str, p: Principal = Depends(principal)):
        org_id = membership(org_id, p)
        run, plan, problem = load_plan(org_id, run_id, p)
        saved = saved_layout(org_id, run["id"], p)
        layout, pl = effective_layout(org_id, plan, saved, p)
        sessions = [s for s in call(store.list_sessions, p.token, org_id, 50) if s.get("run_id") == run["id"]]
        others = [r for r in call(store.list_runs, p.token, org_id, None, 50)
                  if r.get("status") == "done" and r.get("id") != run["id"] and r.get("stations_used")]
        return {"run": {k: v for k, v in run.items() if k != "result"},
                "plan": plan, "problem_name": (problem or {}).get("name", ""),
                "layout": layout, "layout_saved": bool(saved), "placement": pl,
                "workshop_plans": call(store.list_plans, p.token, org_id),
                "sessions": sessions, "simulations": call(store.list_simulations, p.token, org_id, run["id"], 20, "twin"),
                "other_runs": [{"id": r["id"], "created_at": r.get("created_at"), "stations_used": r.get("stations_used"),
                                "actual_cycle_time": r.get("actual_cycle_time"), "solver": r.get("solver"),
                                "problem_id": r.get("problem_id")} for r in others[:30]]}

    @app.put("/v1/orgs/{org_id}/runs/{run_id}/layout", tags=["jumeau"])
    def put_layout(org_id: str, run_id: str, body: LayoutIn, p: Principal = Depends(principal)):
        org_id = membership(org_id, p, write=True)
        run, plan, _ = load_plan(org_id, run_id, p)
        known = {str(s["station"]) for s in plan["stations"]}
        if body.plan_id:
            pl = placement(plan["stations"], plan_row(org_id, body.plan_id, p),
                           {k: v for k, v in body.assignment.items() if k in known})
            lay = pl["layout"]
            row = call(store.save_layout, p.token, org_id, run["id"], "free", lay["positions"],
                       pl["plan_id"], pl["assignment"])
            return {**row, "layout": lay, "placement": pl}
        positions = {k: v.model_dump() for k, v in body.positions.items() if k in known}
        row = call(store.save_layout, p.token, org_id, run["id"], body.kind, positions)
        return {**row, "layout": twin.layout_for(plan, row), "placement": None}

    @app.post("/v1/orgs/{org_id}/runs/{run_id}/twin/plan", tags=["jumeau"])
    def place_on_plan(org_id: str, run_id: str, body: PlanPlacementIn, p: Principal = Depends(principal)):
        org_id = membership(org_id, p)
        run, plan, _ = load_plan(org_id, run_id, p)
        known = {str(s["station"]) for s in plan["stations"]}
        return placement(plan["stations"], plan_row(org_id, body.plan_id, p),
                         {k: v for k, v in body.assignment.items() if k in known})

    @app.post("/v1/orgs/{org_id}/runs/{run_id}/simulate", status_code=202, tags=["jumeau"])
    def simulate(org_id: str, run_id: str, body: SimulateRequest, p: Principal = Depends(principal)):
        org_id = membership(org_id, p, write=True)
        run, plan, _ = load_plan(org_id, run_id, p)
        base_id = run["id"]
        plans, layouts = {base_id: plan}, {}
        base_saved = body.layout.model_dump() if body.layout else saved_layout(org_id, base_id, p)
        layouts[base_id], _ = effective_layout(org_id, plan, base_saved, p)
        base_plan_id = (base_saved or {}).get("plan_id") if layouts[base_id].get("plan_id") else None
        scenarios = []
        for s in body.scenarios:
            d = s.model_dump()
            if d.get("run_id"):
                other = uid(d["run_id"], "Calcul")
                d["run_id"] = other
                if other not in plans:
                    _, oplan, _ = load_plan(org_id, other, p)
                    plans[other] = oplan
                    if base_plan_id:   # même plan d'atelier : association automatique du 2e modèle
                        layouts[other], _ = effective_layout(org_id, oplan, {"plan_id": base_plan_id}, p)
                    else:
                        layouts[other] = twin.layout_for(oplan, saved_layout(org_id, other, p),
                                                         layouts[base_id]["kind"])
            known = {str(st["station"]) for st in plans[d.get("run_id") or base_id]["stations"]}
            for b in d["breakdowns"]:
                if str(b["station"]) not in known:
                    raise HTTPException(422, f"Station {b['station']} inconnue ({d['name']}).")
            scenarios.append(d)
        row = call(store.create_simulation, p.token, org_id, p.user_id, {
            "run_id": base_id, "name": body.name or " / ".join(s["name"] for s in scenarios)[:120],
            "scenarios": scenarios, "layout": layouts[base_id]})
        token, sim_id = p.token, row["id"]

        def work() -> dict:
            safe_update(token, sim_id, {"status": "running", "started_at": _now()})
            try:
                results = twin.run_scenarios(plans, layouts, scenarios, base_id)
            except Exception as e:  # noqa: BLE001
                log.exception("Simulation %s en échec", sim_id)
                safe_update(token, sim_id, {"status": "failed", "error": str(e)[:2000], "finished_at": _now()})
                raise
            safe_update(token, sim_id, {"status": "done", "results": results, "finished_at": _now()})
            return {"id": sim_id}

        queue.submit("simulate", org_id, work)
        return row

    def safe_update(token: str, sim_id: str, fields: dict) -> None:
        try:
            store.update_simulation(token, sim_id, fields)
        except Exception as e:  # noqa: BLE001
            log.warning("Mise à jour de la simulation %s impossible : %s", sim_id, e)

    @app.get("/v1/orgs/{org_id}/runs/{run_id}/simulations", tags=["jumeau"])
    def list_sims(org_id: str, run_id: str, p: Principal = Depends(principal)):
        org_id = membership(org_id, p)
        return call(store.list_simulations, p.token, org_id, uid(run_id, "Calcul"))

    @app.get("/v1/orgs/{org_id}/simulations/{sim_id}", tags=["jumeau"])
    def get_sim(org_id: str, sim_id: str, p: Principal = Depends(principal)):
        org_id = membership(org_id, p)
        sim = call(store.get_simulation, p.token, org_id, uid(sim_id, "Simulation"))
        if sim.get("kind") == "opt":          # variantes d'implantation (modèles complets) : inutiles au front
            lay = sim.get("layout") or {}
            sim = {**sim, "layout": {"variants": [{"name": v.get("name"), "layout": v.get("layout")} for v in lay.get("variants") or []]}}
        return sim

    def _done(org_id: str, sim_id: str, p: Principal) -> dict:
        org_id = membership(org_id, p)
        sim = call(store.get_simulation, p.token, org_id, uid(sim_id, "Simulation"))
        if sim.get("status") != "done":
            raise HTTPException(409, f"Simulation non terminée (statut : {sim.get('status')}).")
        return sim

    @app.get("/v1/orgs/{org_id}/simulations/{sim_id}/export.xlsx", tags=["jumeau"])
    def sim_xlsx(org_id: str, sim_id: str, p: Principal = Depends(principal)):
        sim = _done(org_id, sim_id, p)
        return Response(twin.build_xlsx(sim, org_name(sim["org_id"], p)),
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="simulation_{sim_id[:8]}.xlsx"'})

    @app.get("/v1/orgs/{org_id}/simulations/{sim_id}/export.pdf", tags=["jumeau"])
    def sim_pdf(org_id: str, sim_id: str, p: Principal = Depends(principal)):
        sim = _done(org_id, sim_id, p)
        return Response(twin.build_pdf(sim, org_name(sim["org_id"], p)), media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="simulation_{sim_id[:8]}.pdf"'})

    @app.get("/v1/orgs/{org_id}/runs/{run_id}/twin/sync", tags=["jumeau"])
    def twin_sync(org_id: str, run_id: str, session_id: str,
                  order_qty: Optional[int] = Query(None, ge=1, le=10_000_000),
                  order_done: int = Query(0, ge=0, le=10_000_000),
                  bundle_size: int = Query(10, ge=1, le=100),
                  p: Principal = Depends(principal)):
        org_id = membership(org_id, p)
        run, plan, problem = load_plan(org_id, run_id, p)
        session = call(store.get_session, p.token, org_id, uid(session_id, "Session"))
        if session.get("plan", {}).get("stations"):
            plan = twin.twin_plan(run, problem, session["plan"])   # plan figé à l'ouverture de la session
        entries = call(store.list_entries, p.token, org_id, session["id"])
        layout, _ = effective_layout(org_id, plan, saved_layout(org_id, run["id"], p), p)
        return twin.sync(session, entries, plan, layout, order_qty=order_qty, order_done=order_done,
                         bundle_size=bundle_size)

    from api import routes_des
    routes_des.register(app, queue, store, principal, {
        "call": call, "uid": uid, "membership": membership, "load_plan": load_plan, "saved_layout": saved_layout,
        "effective_layout": effective_layout, "org_name": org_name, "safe_update": safe_update, "now": _now})
