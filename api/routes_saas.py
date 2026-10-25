"""Routes « compte » : ateliers, lignes, gammes et historique des calculs (Supabase).

Actives uniquement si TLB_SUPABASE_URL et TLB_SUPABASE_ANON_KEY sont définis.
Authentification : en-tête `Authorization: Bearer <jeton d'accès Supabase>`.

  GET    /v1/me                                   utilisateur + ateliers + offre
  POST   /v1/orgs                                 créer un atelier (essai 30 j)
  GET    /v1/orgs/{org}                           atelier, rôle, offre, membres
  GET    /v1/orgs/{org}/lines   POST …            lignes de production
  DELETE /v1/orgs/{org}/lines/{line}
  GET    /v1/orgs/{org}/problems  POST …          gammes enregistrées
  GET    /v1/orgs/{org}/problems/{id}
  POST   /v1/orgs/{org}/runs                      lancer un calcul (en file, historisé)
  GET    /v1/orgs/{org}/runs                      historique
  GET    /v1/orgs/{org}/runs/{id}                 détail + résultat
  GET    /v1/orgs/{org}/runs/{id}/export.json
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Callable, Optional
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import Response

from api.auth import AuthError, Principal, SupabaseAuth
from api.conversion import run_balance, run_min_cycle
from api.jobs import JobQueue
from api.schemas import (
    BalanceRequest, JobKind, LineCreate, MinCycleRequest, OrgCreate, ProblemIn, ProblemSave,
    RunCreate, SolverName,
)
from api.settings import Settings
from api.store import StoreError, SupabaseStore

log = logging.getLogger("tlb.api")

WRITE_ROLES = {"owner", "admin", "methodes", "chef_ligne"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def bearer_principal(auth: SupabaseAuth) -> Callable[..., Principal]:
    def dep(authorization: Optional[str] = Header(default=None)) -> Principal:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(401, "Connexion requise (en-tête Authorization: Bearer <jeton>).")
        try:
            return auth.verify(authorization.split(" ", 1)[1].strip())
        except AuthError as e:
            raise HTTPException(401, str(e))
    return dep


def register(app: FastAPI, settings: Settings, queue: JobQueue,
             auth: SupabaseAuth, store: SupabaseStore) -> None:
    principal = bearer_principal(auth)

    def call(fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except StoreError as e:
            raise HTTPException(e.status, e.message)

    def uuid_or_404(value: str, what: str) -> str:
        try:
            return str(UUID(value))
        except (ValueError, TypeError):
            raise HTTPException(404, f"{what} introuvable.")

    def membership(org_id: str, p: Principal) -> str:
        org_id = uuid_or_404(org_id, "Atelier")
        role = call(store.member_role, p.token, org_id, p.user_id)
        if role is None:
            raise HTTPException(404, "Atelier introuvable.")
        return role

    # ------------------------------------------------------------ compte
    @app.get("/v1/me", tags=["compte"])
    def me(p: Principal = Depends(principal)):
        return {"user_id": p.user_id, "email": p.email, "orgs": call(store.my_orgs, p.token, p.user_id)}

    @app.post("/v1/orgs", status_code=201, tags=["compte"])
    def create_org(body: OrgCreate, p: Principal = Depends(principal)):
        return call(store.create_org, p.token, body.name, body.country.upper())

    @app.get("/v1/orgs/{org_id}", tags=["compte"])
    def get_org(org_id: str, p: Principal = Depends(principal)):
        role = membership(org_id, p)
        orgs = {o["id"]: o for o in call(store.my_orgs, p.token, p.user_id)}
        org = orgs.get(str(UUID(org_id)), {})
        return {**org, "role": role, "plan": call(store.org_plan, p.token, org_id),
                "members": call(store.list_members, p.token, org_id)}

    # ------------------------------------------------------------ lignes
    @app.get("/v1/orgs/{org_id}/lines", tags=["lignes"])
    def list_lines(org_id: str, p: Principal = Depends(principal)):
        membership(org_id, p)
        return call(store.list_lines, p.token, org_id)

    @app.post("/v1/orgs/{org_id}/lines", status_code=201, tags=["lignes"])
    def create_line(org_id: str, body: LineCreate, p: Principal = Depends(principal)):
        membership(org_id, p)
        return call(store.create_line, p.token, org_id, p.user_id, body.model_dump())

    @app.delete("/v1/orgs/{org_id}/lines/{line_id}", status_code=204, tags=["lignes"])
    def delete_line(org_id: str, line_id: str, p: Principal = Depends(principal)):
        membership(org_id, p)
        if not call(store.delete_line, p.token, org_id, uuid_or_404(line_id, "Ligne")):
            raise HTTPException(404, "Ligne introuvable ou suppression non autorisée.")
        return Response(status_code=204)

    # ------------------------------------------------------------ gammes
    def plan_limits(org_id: str, p: Principal) -> dict:
        sub = call(store.org_plan, p.token, org_id) or {}
        return sub.get("plan") or {}

    def check_problem(problem: ProblemIn, plan: dict, solver: Optional[SolverName] = None) -> None:
        cap = min(settings.max_operations, int(plan.get("max_operations") or settings.max_operations))
        if len(problem.operations) > cap:
            raise HTTPException(413, f"Trop d'opérations ({len(problem.operations)} > {cap} pour votre offre).")
        if solver == SolverName.cp_sat and plan and not plan.get("cpsat", True):
            raise HTTPException(402, "CP-SAT n'est pas inclus dans votre offre.")

    @app.post("/v1/orgs/{org_id}/problems", status_code=201, tags=["gammes"])
    def save_problem(org_id: str, body: ProblemSave, p: Principal = Depends(principal)):
        membership(org_id, p)
        check_problem(body.problem, plan_limits(org_id, p))
        line_id = uuid_or_404(body.line_id, "Ligne") if body.line_id else None
        return call(store.create_problem, p.token, org_id, p.user_id, body.problem.model_dump(), line_id)

    @app.get("/v1/orgs/{org_id}/problems", tags=["gammes"])
    def list_problems(org_id: str, line_id: Optional[str] = None, limit: int = Query(50, ge=1, le=200),
                      p: Principal = Depends(principal)):
        membership(org_id, p)
        return call(store.list_problems, p.token, org_id,
                    uuid_or_404(line_id, "Ligne") if line_id else None, limit)

    @app.get("/v1/orgs/{org_id}/problems/{problem_id}", tags=["gammes"])
    def get_problem(org_id: str, problem_id: str, p: Principal = Depends(principal)):
        membership(org_id, p)
        return call(store.get_problem, p.token, org_id, uuid_or_404(problem_id, "Gamme"))

    # ------------------------------------------------------------ calculs
    @app.post("/v1/orgs/{org_id}/runs", status_code=202, tags=["calculs"])
    def create_run(org_id: str, body: RunCreate, p: Principal = Depends(principal)):
        role = membership(org_id, p)
        if role not in WRITE_ROLES:
            raise HTTPException(403, "Votre rôle ne permet pas de lancer un calcul.")
        plan = plan_limits(org_id, p)
        if not plan:
            raise HTTPException(402, "Abonnement inactif ou essai expiré.")

        problem_id: Optional[str] = None
        if body.problem_id:
            problem_id = uuid_or_404(body.problem_id, "Gamme")
            row = call(store.get_problem, p.token, org_id, problem_id)
            problem = ProblemIn.model_validate(row["payload"])
        elif body.problem is not None:
            problem = body.problem
        else:
            raise HTTPException(422, "Fournir « problem_id » ou « problem ».")
        check_problem(problem, plan, body.solver)
        if problem_id is None and body.save_problem:
            line_id = uuid_or_404(body.line_id, "Ligne") if body.line_id else None
            problem_id = call(store.create_problem, p.token, org_id, p.user_id,
                              problem.model_dump(), line_id)["id"]

        params = {"time_limit_seconds": body.time_limit_seconds}
        if body.kind == JobKind.min_cycle:
            params["precision"] = body.precision
        run = call(store.create_run, p.token, org_id, p.user_id, kind=body.kind.value,
                   solver=body.solver.value, params=params, problem_id=problem_id)

        cap, token, run_id = settings.job_time_limit, p.token, run["id"]

        def work() -> dict:
            safe_update(token, run_id, {"status": "running", "started_at": _now()})
            try:
                if body.kind == JobKind.balance:
                    res = run_balance(BalanceRequest(problem=problem, solver=body.solver,
                                                     time_limit_seconds=body.time_limit_seconds), cap)
                    out = res.model_dump()
                    summary = {"success": res.success, "compliant": res.compliant,
                               "stations_used": res.stations_used,
                               "actual_cycle_time": res.actual_cycle_time, "efficiency": res.efficiency}
                else:
                    res = run_min_cycle(MinCycleRequest(problem=problem, solver=body.solver,
                                                        precision=body.precision,
                                                        time_limit_seconds=body.time_limit_seconds), cap)
                    out = res.model_dump()
                    r = res.result
                    summary = {"success": res.found, "min_cycle_time": res.min_cycle_time,
                               "compliant": r.compliant if r else False,
                               "stations_used": r.stations_used if r else None,
                               "actual_cycle_time": r.actual_cycle_time if r else None,
                               "efficiency": r.efficiency if r else None}
            except Exception as e:  # noqa: BLE001
                safe_update(token, run_id, {"status": "failed", "error": str(e)[:2000],
                                            "finished_at": _now()})
                raise
            safe_update(token, run_id, {**summary, "status": "done", "result": out,
                                        "finished_at": _now()})
            return out

        queue.submit(body.kind.value, org_id, work)
        return {**run, "problem_id": problem_id}

    def safe_update(token: str, run_id: str, fields: dict) -> None:
        try:
            store.update_run(token, run_id, fields)
        except Exception as e:  # noqa: BLE001 — ne pas perdre le calcul pour un souci d'écriture
            log.warning("Mise à jour du calcul %s impossible : %s", run_id, e)

    @app.get("/v1/orgs/{org_id}/runs", tags=["calculs"])
    def list_runs(org_id: str, problem_id: Optional[str] = None, limit: int = Query(50, ge=1, le=200),
                  p: Principal = Depends(principal)):
        membership(org_id, p)
        return call(store.list_runs, p.token, org_id,
                    uuid_or_404(problem_id, "Gamme") if problem_id else None, limit)

    @app.get("/v1/orgs/{org_id}/runs/{run_id}", tags=["calculs"])
    def get_run(org_id: str, run_id: str, p: Principal = Depends(principal)):
        membership(org_id, p)
        return call(store.get_run, p.token, org_id, uuid_or_404(run_id, "Calcul"))

    @app.get("/v1/orgs/{org_id}/runs/{run_id}/export.json", tags=["calculs"])
    def export_run(org_id: str, run_id: str, p: Principal = Depends(principal)):
        membership(org_id, p)
        run = call(store.get_run, p.token, org_id, uuid_or_404(run_id, "Calcul"))
        if run.get("status") != "done":
            raise HTTPException(409, f"Calcul non terminé (statut : {run.get('status')}).")
        payload = {"run": {k: v for k, v in run.items() if k != "result"}, "result": run.get("result")}
        return Response(json.dumps(payload, ensure_ascii=False, indent=2), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="calcul_{run_id[:8]}.json"'})
