"""Routes « simulation à événements discrets » (v3.0, type FlexSim).

  GET  /v1/orgs/{org}/runs/{id}/des/model             modèle généré (calcul + implantation / plan d'atelier)
  POST /v1/orgs/{org}/runs/{id}/des                   lancer scénarios × réplications (tâche de fond) -> 202
  GET  /v1/orgs/{org}/runs/{id}/des/simulations       historique des simulations DES du calcul
  GET  /v1/orgs/{org}/simulations/{sid}               statut + résultats (route du jumeau, commune)
  GET  /v1/orgs/{org}/simulations/{sid}/des.xlsx|pdf  exports des tableaux de bord

Logique par blocs (Process Flow) :
  GET    /v1/orgs/{org}/runs/{id}/flow/auto           graphe généré depuis la gamme + modèle du plan (animation)
  POST   /v1/orgs/{org}/flows/validate                validation (cycles, branches orphelines, sorties)
  GET    /v1/orgs/{org}/flows[?run_id]                graphes enregistrés ; POST : créer
  GET|PATCH|DELETE /v1/orgs/{org}/flows/{fid}
  POST   /v1/orgs/{org}/runs/{id}/flow/simulate       exécution par le moteur DES (tâche de fond, kind = 'flow')

Optimiseur (phase 2.3, type OptQuest) :
  POST /v1/orgs/{org}/runs/{id}/optimize              recherche NSGA-II (tâche de fond bornée, progression) -> 202
  GET  /v1/orgs/{org}/runs/{id}/optimizations         historique (kind = 'opt')
  POST /v1/orgs/{org}/optimizations/{sid}/apply       solution du front de Pareto -> simulation DES (+ implantation)

Stockage : table twin_simulations (kind = 'des' | 'flow' | 'opt', layout = modèle). RLS par atelier.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import Response

import time

from api import des, optimizer
from api.jobs import JobQueue
from api.schemas import DesRequest, OptApplyIn, OptimizeRequest, FlowIn, FlowPatch, FlowSimulateIn, FlowValidateIn
from api.store import StoreError, SupabaseStore
from engine.des.builder import summary
from engine.des.flow import FlowError, from_plan, normalize_graph, run_flow_experiment, validate as validate_flow
from engine.des.model import ModelError

log = logging.getLogger("tlb.api")


def register(app: FastAPI, queue: JobQueue, store: SupabaseStore, principal, h: dict) -> None:
    call, uid, membership = h["call"], h["uid"], h["membership"]
    load_plan, saved_layout, effective_layout = h["load_plan"], h["saved_layout"], h["effective_layout"]
    org_name, safe_update, now = h["org_name"], h["safe_update"], h["now"]

    def progress_cb(token: str, sim_id: str):
        """Progression des simulations : {pct, done, total, elapsed_s} écrite au plus toutes les 2 s."""
        t0, last = time.monotonic(), [0.0]

        def cb(done: int, total: int) -> None:
            if done < total and time.monotonic() - last[0] < 2.0:
                return
            last[0] = time.monotonic()
            safe_update(token, sim_id, {"results": {"progress": {
                "pct": min(99, round(100 * done / max(1, total))), "done": done, "total": total,
                "elapsed_s": round(time.monotonic() - t0, 1)}}})
        return cb

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
            safe_update(token, sim_id, {"status": "running", "started_at": now(), "results": {"progress": {"pct": 0}}})
            try:
                results = des.run(model, scenarios, reps, wp, progress_cb(token, sim_id))
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


    # ================================================================== optimiseur (phase 2.3)
    @app.post("/v1/orgs/{org_id}/runs/{run_id}/optimize", status_code=202, tags=["optimiseur"])
    def opt_run(org_id: str, run_id: str, body: OptimizeRequest, p=Depends(principal)):
        org_id = membership(org_id, p, write=True)
        run, plan, _, layout, wp, _ = base(org_id, run_id, p, body.plan_id)
        try:
            model = des.prepare(body.model, wp) if body.model else des.auto_model(plan, layout, wp)
            vs = optimizer.variants(plan, layout, wp, model)
        except (ModelError, ValueError) as e:
            raise HTTPException(422, str(e))
        cfg = optimizer.normalize_config(body.config)
        cfg["time_budget_s"] = min(cfg["time_budget_s"], optimizer.MAX_BUDGET_S)
        row = call(store.create_simulation, p.token, org_id, p.user_id, {
            "run_id": run["id"], "kind": "opt", "name": (body.name or "Optimisation")[:120],
            "scenarios": [{"name": body.name or "Optimisation", "config": cfg}], "layout": {"variants": vs}})
        token, sim_id = p.token, row["id"]

        def work() -> dict:
            safe_update(token, sim_id, {"status": "running", "started_at": now(), "results": {"progress": {"pct": 0}}})
            last = [0.0]

            def progress(pr: dict) -> None:
                if time.monotonic() - last[0] >= 2.5:
                    last[0] = time.monotonic()
                    safe_update(token, sim_id, {"results": {"progress": pr}})
            try:
                res = optimizer.run(vs, cfg, wp, progress)
            except Exception as e:  # noqa: BLE001
                log.exception("Optimisation %s en échec", sim_id)
                safe_update(token, sim_id, {"status": "failed", "error": str(e)[:2000], "finished_at": now()})
                raise
            res["progress"] = {"pct": 100, "evals": res["evals"], "elapsed_s": res["elapsed_s"]}
            safe_update(token, sim_id, {"status": "done", "results": res, "finished_at": now()})
            return {"id": sim_id}

        queue.submit("opt", org_id, work)
        return {k: v for k, v in row.items() if k != "layout"}

    @app.get("/v1/orgs/{org_id}/runs/{run_id}/optimizations", tags=["optimiseur"])
    def opt_list(org_id: str, run_id: str, p=Depends(principal)):
        org_id = membership(org_id, p)
        return call(store.list_simulations, p.token, org_id, uid(run_id, "Calcul"), 20, "opt")

    @app.post("/v1/orgs/{org_id}/optimizations/{sim_id}/apply", status_code=202, tags=["optimiseur"])
    def opt_apply(org_id: str, sim_id: str, body: OptApplyIn, p=Depends(principal)):
        org_id = membership(org_id, p, write=True)
        sim = call(store.get_simulation, p.token, org_id, uid(sim_id, "Optimisation"))
        if sim.get("kind") != "opt" or sim.get("status") != "done":
            raise HTTPException(409, "Optimisation non terminée.")
        sols = (sim.get("results") or {}).get("pareto") or []
        sol = next((s for s in sols if s.get("id") == body.solution), None)
        if not sol:
            raise HTTPException(404, "Solution introuvable.")
        vs = (sim.get("layout") or {}).get("variants") or []
        if not vs:
            raise HTTPException(409, "Variantes d'implantation manquantes.")
        wp = workshop_row(org_id, (vs[0].get("layout") or {}).get("plan_id"), p)
        try:
            model = optimizer.solution_model(vs, sol, wp)
        except (ModelError, ValueError) as e:
            raise HTTPException(422, str(e))
        saved = None
        lay = optimizer.layout_to_save(vs, sol, model) if body.save_layout else None
        if lay:
            saved = call(store.save_layout, p.token, org_id, sim["run_id"], lay["kind"], lay["positions"],
                         lay.get("plan_id"), lay.get("assignment"))
        name = f"Optimiseur — solution {sol['id']}"
        scenarios = [{"name": name[:60], "overrides": {}, "absent": []}]
        row = call(store.create_simulation, p.token, org_id, p.user_id, {
            "run_id": sim["run_id"], "kind": "des", "name": name, "scenarios": scenarios, "layout": model})
        token, des_id, reps = p.token, row["id"], body.replications

        def work() -> dict:
            safe_update(token, des_id, {"status": "running", "started_at": now(), "results": {"progress": {"pct": 0}}})
            try:
                results = des.run(model, scenarios, reps, wp, progress_cb(token, des_id))
            except Exception as e:  # noqa: BLE001
                safe_update(token, des_id, {"status": "failed", "error": str(e)[:2000], "finished_at": now()})
                raise
            safe_update(token, des_id, {"status": "done", "results": results, "finished_at": now()})
            return {"id": des_id}

        queue.submit("des", org_id, work)
        return {"simulation": {k: v for k, v in row.items() if k != "layout"}, "layout_saved": bool(saved),
                "plan_id": (vs[0].get("layout") or {}).get("plan_id")}

    # ================================================================== logique par blocs (Process Flow)
    FLOW_MAX_BYTES = 500_000

    def _graph(g: dict) -> dict:
        import json as _json
        if len(_json.dumps(g)) > FLOW_MAX_BYTES:
            raise HTTPException(413, "Graphe trop volumineux.")
        return normalize_graph(g)

    @app.get("/v1/orgs/{org_id}/runs/{run_id}/flow/auto", tags=["process-flow"])
    def flow_auto(org_id: str, run_id: str, plan_id: Optional[str] = None, p=Depends(principal)):
        org_id = membership(org_id, p)
        run, plan, problem, layout, wp, _ = base(org_id, run_id, p, plan_id)
        try:
            graph = from_plan(plan, problem)
        except FlowError as e:
            raise HTTPException(422, str(e))
        model = des.auto_model(plan, layout, wp)
        return {"graph": graph, "validation": validate_flow(graph), "model": model, "workshop_plan": wp,
                "problem_name": (problem or {}).get("name", ""),
                "flows": call(store.list_flows, p.token, org_id, run["id"]),
                "simulations": call(store.list_simulations, p.token, org_id, run["id"], 20, "flow")}

    @app.post("/v1/orgs/{org_id}/flows/validate", tags=["process-flow"])
    def flow_validate(org_id: str, body: FlowValidateIn, p=Depends(principal)):
        membership(org_id, p)
        return validate_flow(_graph(body.graph))

    @app.get("/v1/orgs/{org_id}/flows", tags=["process-flow"])
    def flow_list(org_id: str, run_id: Optional[str] = None, p=Depends(principal)):
        org_id = membership(org_id, p)
        return call(store.list_flows, p.token, org_id, uid(run_id, "Calcul") if run_id else None)

    @app.post("/v1/orgs/{org_id}/flows", status_code=201, tags=["process-flow"])
    def flow_create(org_id: str, body: FlowIn, p=Depends(principal)):
        org_id = membership(org_id, p, write=True)
        return call(store.create_flow, p.token, org_id, {"name": body.name, "graph": _graph(body.graph),
                                                         "run_id": uid(body.run_id, "Calcul") if body.run_id else None})

    @app.get("/v1/orgs/{org_id}/flows/{flow_id}", tags=["process-flow"])
    def flow_get(org_id: str, flow_id: str, p=Depends(principal)):
        org_id = membership(org_id, p)
        return call(store.get_flow, p.token, org_id, uid(flow_id, "Graphe"))

    @app.patch("/v1/orgs/{org_id}/flows/{flow_id}", tags=["process-flow"])
    def flow_patch(org_id: str, flow_id: str, body: FlowPatch, p=Depends(principal)):
        org_id = membership(org_id, p, write=True)
        fields = {k: v for k, v in {"name": body.name, "graph": _graph(body.graph) if body.graph is not None else None}.items()
                  if v is not None}
        if not fields:
            raise HTTPException(422, "Rien à modifier.")
        return call(store.update_flow, p.token, org_id, uid(flow_id, "Graphe"), fields)

    @app.delete("/v1/orgs/{org_id}/flows/{flow_id}", status_code=204, tags=["process-flow"])
    def flow_delete(org_id: str, flow_id: str, p=Depends(principal)):
        org_id = membership(org_id, p, write=True)
        if not call(store.delete_flow, p.token, org_id, uid(flow_id, "Graphe")):
            raise HTTPException(404, "Graphe introuvable (ou droits insuffisants).")
        return Response(status_code=204)

    @app.post("/v1/orgs/{org_id}/runs/{run_id}/flow/simulate", status_code=202, tags=["process-flow"])
    def flow_simulate(org_id: str, run_id: str, body: FlowSimulateIn, p=Depends(principal)):
        org_id = membership(org_id, p, write=True)
        run, plan, _, layout, wp, _ = base(org_id, run_id, p, body.plan_id)
        graph = _graph(body.graph)
        chk = validate_flow(graph)
        if not chk["ok"]:
            raise HTTPException(422, chk["errors"][0]["msg"])
        model = des.auto_model(plan, layout, wp)
        sids = [str(s["id"]) for s in model["stations"]]
        row = call(store.create_simulation, p.token, org_id, p.user_id, {
            "run_id": run["id"], "kind": "flow", "name": (body.name or graph.get("name") or "Flux")[:120],
            "scenarios": [{"name": graph.get("name") or "Flux", "flow_id": body.flow_id}],
            "layout": {"graph": graph, "model": des.model_view(model)}})
        token, sim_id = p.token, row["id"]
        T = float((graph.get("shift") or {}).get("minutes") or 480)
        reps = max(1, min(body.replications, int(des.WORK_BUDGET // max(1.0, len(graph["blocks"]) * T * 2))))

        def work() -> dict:
            safe_update(token, sim_id, {"status": "running", "started_at": now(), "results": {"progress": {"pct": 0}}})
            try:
                res = run_flow_experiment(graph, reps, sids, progress_cb(token, sim_id))
            except Exception as e:  # noqa: BLE001
                log.exception("Flux %s en échec", sim_id)
                safe_update(token, sim_id, {"status": "failed", "error": str(e)[:2000], "finished_at": now()})
                raise
            safe_update(token, sim_id, {"status": "done", "results": {"engine": "flow-1.0", "replications": reps,
                                                                       "result": res}, "finished_at": now()})
            return {"id": sim_id}

        queue.submit("flow", org_id, work)
        return row
