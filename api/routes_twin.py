"""Routes « jumeau numérique » : implantation 2D, simulations « et si », réel vs simulé.

  GET  /v1/orgs/{org}/runs/{id}/twin                plan + implantation + sessions + simulations
  PUT  /v1/orgs/{org}/runs/{id}/layout              enregistrer l'implantation (ligne / U / libre)
  POST /v1/orgs/{org}/runs/{id}/simulate            lancer 1–3 scénarios (tâche de fond) -> 202
  GET  /v1/orgs/{org}/runs/{id}/simulations         historique des simulations du calcul
  GET  /v1/orgs/{org}/simulations/{sid}             statut + résultats
  GET  /v1/orgs/{org}/simulations/{sid}/export.xlsx|pdf
  GET  /v1/orgs/{org}/runs/{id}/twin/sync?session_id=…&order_qty=…&order_done=…

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
from api.schemas import LayoutIn, SimulateRequest
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

    def org_name(org_id: str, p: Principal) -> str:
        return next((o.get("name", "") for o in call(store.my_orgs, p.token, p.user_id)
                     if o.get("id") == org_id), "")

    @app.get("/v1/orgs/{org_id}/runs/{run_id}/twin", tags=["jumeau"])
    def get_twin(org_id: str, run_id: str, p: Principal = Depends(principal)):
        org_id = membership(org_id, p)
        run, plan, problem = load_plan(org_id, run_id, p)
        saved = saved_layout(org_id, run["id"], p)
        sessions = [s for s in call(store.list_sessions, p.token, org_id, 50) if s.get("run_id") == run["id"]]
        others = [r for r in call(store.list_runs, p.token, org_id, None, 50)
                  if r.get("status") == "done" and r.get("id") != run["id"] and r.get("stations_used")]
        return {"run": {k: v for k, v in run.items() if k != "result"},
                "plan": plan, "problem_name": (problem or {}).get("name", ""),
                "layout": twin.layout_for(plan, saved), "layout_saved": bool(saved),
                "sessions": sessions, "simulations": call(store.list_simulations, p.token, org_id, run["id"]),
                "other_runs": [{"id": r["id"], "created_at": r.get("created_at"), "stations_used": r.get("stations_used"),
                                "actual_cycle_time": r.get("actual_cycle_time"), "solver": r.get("solver"),
                                "problem_id": r.get("problem_id")} for r in others[:30]]}

    @app.put("/v1/orgs/{org_id}/runs/{run_id}/layout", tags=["jumeau"])
    def put_layout(org_id: str, run_id: str, body: LayoutIn, p: Principal = Depends(principal)):
        org_id = membership(org_id, p, write=True)
        run, plan, _ = load_plan(org_id, run_id, p)
        known = {str(s["station"]) for s in plan["stations"]}
        positions = {k: v.model_dump() for k, v in body.positions.items() if k in known}
        row = call(store.save_layout, p.token, org_id, run["id"], body.kind, positions)
        return {**row, "layout": twin.layout_for(plan, row)}

    @app.post("/v1/orgs/{org_id}/runs/{run_id}/simulate", status_code=202, tags=["jumeau"])
    def simulate(org_id: str, run_id: str, body: SimulateRequest, p: Principal = Depends(principal)):
        org_id = membership(org_id, p, write=True)
        run, plan, _ = load_plan(org_id, run_id, p)
        base_id = run["id"]
        plans, layouts = {base_id: plan}, {}
        layouts[base_id] = (twin.layout_for(plan, body.layout.model_dump()) if body.layout
                            else twin.layout_for(plan, saved_layout(org_id, base_id, p)))
        scenarios = []
        for s in body.scenarios:
            d = s.model_dump()
            if d.get("run_id"):
                other = uid(d["run_id"], "Calcul")
                d["run_id"] = other
                if other not in plans:
                    _, oplan, _ = load_plan(org_id, other, p)
                    plans[other] = oplan
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
        return call(store.get_simulation, p.token, org_id, uid(sim_id, "Simulation"))

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
        layout = twin.layout_for(plan, saved_layout(org_id, run["id"], p))
        return twin.sync(session, entries, plan, layout, order_qty=order_qty, order_done=order_done,
                         bundle_size=bundle_size)
