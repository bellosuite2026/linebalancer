"""Application FastAPI — `uvicorn api.main:app`.

Routes v1 :
  GET  /health                      état + solveurs disponibles
  GET  /v1/solvers
  POST /v1/import/{sam|workstations|workers}   fichier -> JSON
  POST /v1/import/problem           3 fichiers + cadence -> problème + diagnostic
  POST /v1/precheck                 diagnostic de faisabilité
  POST /v1/balance                  équilibrage synchrone (temps plafonné)
  POST /v1/min-cycle                cadence minimale synchrone
  POST /v1/export/json              équilibrage -> fichier JSON téléchargeable
  POST /v1/jobs  /  GET /v1/jobs/{id}  /  GET /v1/jobs/{id}/export.json

Avec Supabase configuré : comptes, ateliers, lignes, gammes et historique
(voir api/routes_saas.py).
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from engine.solvers import registry

from api import __version__
from api.conversion import (
    operations_out, parse_upload, run_balance, run_min_cycle, run_precheck,
    workers_out, workstations_out,
)
from api.jobs import JobQueue
from api.schemas import (
    BalanceRequest, ImportOut, JobKind, JobOut, JobRequest, MinCycleOut, MinCycleRequest,
    PrecheckOut, ProblemIn, ResultOut,
)
from api.settings import Settings


def create_app(settings: Optional[Settings] = None, *, auth=None, store=None) -> FastAPI:
    """`auth` / `store` : injection pour les tests (sinon construits depuis Supabase)."""
    settings = settings or Settings.from_env()
    queue = JobQueue(workers=settings.job_workers)
    if settings.supabase_enabled:
        from api.auth import SupabaseAuth
        from api.store import SupabaseStore
        auth = auth or SupabaseAuth(settings.supabase_url, jwt_secret=settings.supabase_jwt_secret)
        store = store or SupabaseStore(settings.supabase_url, settings.supabase_anon_key,
                                       service_key=settings.supabase_service_key)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        queue.shutdown()

    app = FastAPI(title="Textile Line Balancer API", version=__version__, lifespan=lifespan,
                  description="Équilibrage de lignes de confection (RPW, CP-SAT).")
    app.state.settings, app.state.queue = settings, queue
    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                           allow_methods=["*"], allow_headers=["*"], allow_credentials=False)

    # --- Sécurité : jeton Supabase (utilisateur) ou clé API (intégrations) ----
    def tenant(x_api_key: Optional[str] = Header(default=None),
               authorization: Optional[str] = Header(default=None)) -> str:
        if auth is not None and authorization and authorization.lower().startswith("bearer "):
            from api.auth import AuthError
            try:
                return "user:" + auth.verify(authorization.split(" ", 1)[1].strip()).user_id
            except AuthError as e:
                raise HTTPException(401, str(e))
        if x_api_key and x_api_key in settings.api_keys:
            return x_api_key
        if not settings.api_keys and auth is None:
            return "dev"
        raise HTTPException(401, "Authentification requise (Authorization: Bearer <jeton> ou X-API-Key).")

    def guard(p: ProblemIn) -> None:
        if len(p.operations) > settings.max_operations:
            raise HTTPException(413, f"Trop d'opérations ({len(p.operations)} > {settings.max_operations}).")

    async def read_upload(f: UploadFile) -> bytes:
        data = await f.read(settings.max_upload_bytes + 1)
        if len(data) > settings.max_upload_bytes:
            raise HTTPException(413, "Fichier trop volumineux.")
        return data

    def parse_or_422(kind: str, f: UploadFile, data: bytes) -> list:
        try:
            return parse_upload(kind, f.filename or "", data)
        except Exception as e:  # noqa: BLE001 — erreurs de format remontées au client
            raise HTTPException(422, f"Import {kind} impossible : {e}")

    # --- Santé ----------------------------------------------------------------
    @app.get("/health")
    def health():
        return {"status": "ok", "version": __version__,
                "solvers": [n for n in registry.names() if registry.is_available(n)]}

    @app.get("/v1/solvers")
    def solvers(_t: str = Depends(tenant)):
        return [{"name": n, "description": registry.get(n).description,
                 "available": registry.is_available(n)} for n in registry.names()]

    # --- Import ---------------------------------------------------------------
    @app.post("/v1/import/sam")
    async def import_sam(file: UploadFile = File(...), _t: str = Depends(tenant)):
        ops = parse_or_422("sam", file, await read_upload(file))
        return {"operations": [o.model_dump() for o in operations_out(ops)]}

    @app.post("/v1/import/workstations")
    async def import_workstations(file: UploadFile = File(...), _t: str = Depends(tenant)):
        wss = parse_or_422("workstations", file, await read_upload(file))
        return {"workstations": [w.model_dump() for w in workstations_out(wss)]}

    @app.post("/v1/import/workers")
    async def import_workers(file: UploadFile = File(...), _t: str = Depends(tenant)):
        ws = parse_or_422("workers", file, await read_upload(file))
        return {"workers": [w.model_dump() for w in workers_out(ws)]}

    @app.post("/v1/import/problem", response_model=ImportOut)
    async def import_problem(
        sam: UploadFile = File(...),
        target_cycle_time: float = Form(..., gt=0),
        workstations: Optional[UploadFile] = File(None),
        workers: Optional[UploadFile] = File(None),
        name: str = Form("ligne"),
        _t: str = Depends(tenant),
    ):
        ops = parse_or_422("sam", sam, await read_upload(sam))
        wss = parse_or_422("workstations", workstations, await read_upload(workstations)) if workstations else []
        wks = parse_or_422("workers", workers, await read_upload(workers)) if workers else []
        problem = ProblemIn(name=name, target_cycle_time=target_cycle_time,
                            operations=operations_out(ops), workstations=workstations_out(wss),
                            workers=workers_out(wks))
        guard(problem)
        return ImportOut(problem=problem, precheck=run_precheck(problem))

    # --- Diagnostic & calcul --------------------------------------------------
    @app.post("/v1/precheck", response_model=PrecheckOut)
    def precheck_route(problem: ProblemIn, _t: str = Depends(tenant)):
        guard(problem)
        return run_precheck(problem)

    async def _balance(req: BalanceRequest) -> ResultOut:
        guard(req.problem)
        try:
            return await run_in_threadpool(run_balance, req, settings.sync_time_limit)
        except RuntimeError as e:
            raise HTTPException(503, str(e))

    @app.post("/v1/balance", response_model=ResultOut)
    async def balance(req: BalanceRequest, _t: str = Depends(tenant)):
        return await _balance(req)

    @app.post("/v1/min-cycle", response_model=MinCycleOut)
    async def min_cycle(req: MinCycleRequest, _t: str = Depends(tenant)):
        guard(req.problem)
        try:
            return await run_in_threadpool(run_min_cycle, req, settings.sync_time_limit)
        except RuntimeError as e:
            raise HTTPException(503, str(e))

    def _json_file(payload: dict, filename: str) -> Response:
        return Response(json.dumps(payload, ensure_ascii=False, indent=2),
                        media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    @app.post("/v1/export/json")
    async def export_json(req: BalanceRequest, _t: str = Depends(tenant)):
        res = await _balance(req)
        payload = {"problem": req.problem.model_dump(), "solver": req.solver.value,
                   "result": res.model_dump()}
        return _json_file(payload, f"equilibrage_{req.problem.name}.json")

    # --- File de calculs ------------------------------------------------------
    def job_out(j) -> JobOut:
        return JobOut(id=j.id, kind=j.kind, status=j.status, created_at=j.created_at,
                      started_at=j.started_at, finished_at=j.finished_at,
                      result=j.result, error=j.error)

    @app.post("/v1/jobs", response_model=JobOut, status_code=202)
    def create_job(req: JobRequest, t: str = Depends(tenant)):
        cap = settings.job_time_limit
        if req.kind == JobKind.balance:
            if req.balance is None:
                raise HTTPException(422, "Champ « balance » requis pour kind=balance.")
            guard(req.balance.problem)
            body = req.balance
            fn = lambda: run_balance(body, cap).model_dump()  # noqa: E731
        else:
            if req.min_cycle is None:
                raise HTTPException(422, "Champ « min_cycle » requis pour kind=min_cycle.")
            guard(req.min_cycle.problem)
            body = req.min_cycle
            fn = lambda: run_min_cycle(body, cap).model_dump()  # noqa: E731
        return job_out(queue.submit(req.kind.value, t, fn))

    @app.get("/v1/jobs/{job_id}", response_model=JobOut)
    def get_job(job_id: str, t: str = Depends(tenant)):
        j = queue.get(job_id, t)
        if j is None:
            raise HTTPException(404, "Calcul introuvable.")
        return job_out(j)

    @app.get("/v1/jobs/{job_id}/export.json")
    def export_job(job_id: str, t: str = Depends(tenant)):
        j = queue.get(job_id, t)
        if j is None:
            raise HTTPException(404, "Calcul introuvable.")
        if j.status != "done":
            raise HTTPException(409, f"Calcul non terminé (statut : {j.status}).")
        return _json_file({"job": j.id, "kind": j.kind, "result": j.result}, f"calcul_{j.id[:8]}.json")

    if auth is not None and store is not None:
        from api import routes_saas
        routes_saas.register(app, settings, queue, auth, store)
        from api import routes_admin
        routes_admin.register(app, auth, store)

    return app


app = create_app()
