"""Routes « simulation à événements discrets » (v3.0, type FlexSim).

  GET  /v1/orgs/{org}/runs/{id}/des/model             modèle généré (calcul + implantation / plan d'atelier)
  POST /v1/orgs/{org}/runs/{id}/des                   lancer scénarios × réplications (tâche de fond) -> 202
  GET  /v1/orgs/{org}/runs/{id}/des/simulations       historique des simulations DES du calcul
  GET  /v1/orgs/{org}/simulations/{sid}               statut + résultats (route du jumeau, commune)
  GET  /v1/orgs/{org}/simulations/{sid}/des.xlsx|pdf  exports des tableaux de bord

Stockage : table twin_simulations (kind = 'des', layout = modèle). RLS par atelier.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import Response

from api import des
from api.jobs import JobQueue
from api.schemas import DesRequest
from api.store import StoreError, SupabaseStore
from engine.des.builder import summary
from engine.des.model import ModelError

log = logging.getLogger("tlb.api")


def register(app: FastAPI, queue: JobQueue, store: SupabaseStore, principal, h: dict) -> None:
    call, uid, membership = h["call"], h["uid"], h["membership"]
    load_plan, saved_layout, effective_layout = h["load_plan"], h["saved_layout"], h["effective_layout"]
    org_name, safe_update, now = h["org_name"], h["safe_update"], h["now"]

    def workshop_row(org_id: str, plan_id: Optional[str], p) -> Optional[dict]:
        if not plan_id:
            return None
        try:
            return store.get_plan(p.token, org_id, uid(plan_id, "Plan d'atelier"))
        except StoreError:
            return None

    def base(org_id: str, run_id: str, p, plan_id: Optional[str] = None):
        run, plan, problem = load_plan(org_id, run_id, p)
        saved = saved_layout(org_id, run["id"], p)
        if plan_id:
            saved = {**(saved or {}), "plan_id": plan_id, "assignment": (saved or {}).get("assignment") or {}} \
                if (saved or {}).get("plan_id") == plan_id else {"plan_id": plan_id}
        layout, placement = effective_layout(org_id, plan, saved, p)
        wp = workshop_row(org_id, layout.get("plan_id"), p)
        if placement:
            layout = {**layout, "routes": placement.get("routes")}
        return run, plan, problem, layout, wp, placement

    @app.get("/v1/orgs/{org_id}/runs/{run_id}/des/model", tags=["simulation"])
    def des_model(org_id: str, run_id: str, plan_id: Optional[str] = None, p=Depends(principal)):
        org_id = membership(org_id, p)
        run, plan, problem, layout, wp, placement = base(org_id, run_id, p, plan_id)
        model = des.auto_model(plan, layout, wp)
        return {"run": {k: v for k, v in run.items() if k != "result"}, "model": model, "summary": summary(model),
                "problem_name": (problem or {}).get("name", ""), "workshop_plan": wp, "placement": placement,
                "workshop_plans": call(store.list_plans, p.token, org_id),
                "simulations": call(store.list_simulations, p.token, org_id, run["id"], 20, "des")}

    @app.post("/v1/orgs/{org_id}/runs/{run_id}/des", status_code=202, tags=["simulation"])
    def des_run(org_id: str, run_id: str, body: DesRequest, p=Depends(principal)):
        org_id = membership(org_id, p, write=True)
        run, plan, _, layout, wp, _ = base(org_id, run_id, p, body.plan_id)
        try:
            model = des.prepare(body.model, wp) if body.model else des.auto_model(plan, layout, wp)
        except (ModelError, ValueError) as e:
            raise HTTPException(422, str(e))
        scenarios = [s.model_dump() for s in body.scenarios]
        row = call(store.create_simulation, p.token, org_id, p.user_id, {
            "run_id": run["id"], "kind": "des", "name": body.name or " / ".join(s["name"] for s in scenarios)[:120],
            "scenarios": scenarios, "layout": model})
        token, sim_id, reps = p.token, row["id"], body.replications

        def work() -> dict:
            safe_update(token, sim_id, {"status": "running", "started_at": now()})
            try:
                results = des.run(model, scenarios, reps, wp)
            except Exception as e:  # noqa: BLE001
                log.exception("Simulation DES %s en échec", sim_id)
                safe_update(token, sim_id, {"status": "failed", "error": str(e)[:2000], "finished_at": now()})
                raise
            safe_update(token, sim_id, {"status": "done", "results": results, "finished_at": now()})
            return {"id": sim_id}

        queue.submit("des", org_id, work)
        return row

    @app.get("/v1/orgs/{org_id}/runs/{run_id}/des/simulations", tags=["simulation"])
    def des_list(org_id: str, run_id: str, p=Depends(principal)):
        org_id = membership(org_id, p)
        return call(store.list_simulations, p.token, org_id, uid(run_id, "Calcul"), 20, "des")

    def done(org_id: str, sim_id: str, p) -> dict:
        org_id = membership(org_id, p)
        sim = call(store.get_simulation, p.token, org_id, uid(sim_id, "Simulation"))
        if sim.get("status") != "done" or sim.get("kind") != "des":
            raise HTTPException(409, f"Simulation non terminée (statut : {sim.get('status')}).")
        return sim

    @app.get("/v1/orgs/{org_id}/simulations/{sim_id}/des.xlsx", tags=["simulation"])
    def des_xlsx(org_id: str, sim_id: str, p=Depends(principal)):
        sim = done(org_id, sim_id, p)
        return Response(des.build_xlsx(sim, org_name(sim["org_id"], p)),
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="simulation_{sim_id[:8]}.xlsx"'})

    @app.get("/v1/orgs/{org_id}/simulations/{sim_id}/des.pdf", tags=["simulation"])
    def des_pdf(org_id: str, sim_id: str, p=Depends(principal)):
        sim = done(org_id, sim_id, p)
        return Response(des.build_pdf(sim, org_name(sim["org_id"], p)), media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="simulation_{sim_id[:8]}.pdf"'})
