"""Routes « suivi de production » : sessions de ligne, saisies tablette, tableau de bord, exports.

  GET    /v1/orgs/{org}/production/sessions                       liste
  POST   /v1/orgs/{org}/production/sessions                       ouvrir depuis un calcul
  GET    /v1/orgs/{org}/production/sessions/{id}                  session + plan
  PATCH  /v1/orgs/{org}/production/sessions/{id}                  fermer / rouvrir / objectif
  GET    /v1/orgs/{org}/production/sessions/{id}/entries          saisies
  POST   /v1/orgs/{org}/production/sessions/{id}/entries          envoi groupé idempotent (client_id)
  PATCH  /v1/orgs/{org}/production/sessions/{id}/entries/{eid}    corriger une saisie
  GET    /v1/orgs/{org}/production/sessions/{id}/dashboard        indicateurs temps réel
  GET    /v1/orgs/{org}/production/sessions/{id}/export.xlsx|pdf  rapport de la journée

Sécurité : jeton de l'utilisateur transmis à PostgREST, RLS par atelier (membres seulement).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import Response

from api import production
from api.auth import Principal, SupabaseAuth
from api.routes_saas import WRITE_ROLES, bearer_principal
from api.schemas import EntriesBatch, EntryPatch, SessionCreate, SessionUpdate
from api.store import StoreError, SupabaseStore


def register(app: FastAPI, auth: SupabaseAuth, store: SupabaseStore) -> None:
    principal = bearer_principal(auth)
    base = "/v1/orgs/{org_id}/production/sessions"

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
            raise HTTPException(403, "Votre rôle (lecteur) ne permet pas de saisir la production.")
        return org_id

    def load(org_id: str, session_id: str, p: Principal) -> dict:
        return call(store.get_session, p.token, org_id, uid(session_id, "Session"))

    def org_name(org_id: str, p: Principal) -> str:
        return next((o.get("name", "") for o in call(store.my_orgs, p.token, p.user_id)
                     if o.get("id") == org_id), "")

    @app.get(base, tags=["production"])
    def list_sessions(org_id: str, limit: int = Query(50, ge=1, le=200), p: Principal = Depends(principal)):
        org_id = membership(org_id, p)
        return call(store.list_sessions, p.token, org_id, limit)

    @app.post(base, status_code=201, tags=["production"])
    def open_session(org_id: str, body: SessionCreate, p: Principal = Depends(principal)):
        org_id = membership(org_id, p, write=True)
        run = call(store.get_run, p.token, org_id, uid(body.run_id, "Calcul"))
        if run.get("status") != "done" or not production.balance_result(run):
            raise HTTPException(409, "Le calcul doit être terminé avec une répartition des stations.")
        problem = None
        if run.get("problem_id"):
            try:
                problem = store.get_problem(p.token, org_id, run["problem_id"]).get("payload")
            except StoreError:
                problem = None
        plan = production.build_plan(run, problem)
        if not plan["stations"]:
            raise HTTPException(409, "Ce calcul ne contient aucune station à suivre.")
        target = body.target_per_hour or production.default_target_per_hour(plan)
        if not target:
            raise HTTPException(422, "Indiquez l'objectif en pièces par heure.")
        line_name = ""
        line_id = uid(body.line_id, "Ligne") if body.line_id else None
        if line_id:
            line = next((l for l in call(store.list_lines, p.token, org_id) if l["id"] == line_id), None)
            if line is None:
                raise HTTPException(404, "Ligne introuvable.")
            line_name = line.get("name", "")
        data = {"line_id": line_id, "run_id": run["id"], "problem_id": run.get("problem_id"),
                "line_name": line_name, "model": body.model or plan.get("problem_name", "")[:120],
                "shift_start": body.shift_start, "shift_hours": body.shift_hours,
                "target_per_hour": round(float(target), 2), "timezone": body.timezone,
                "cycle_time": plan.get("cycle_time") or None, "takt_time": plan.get("takt_time") or None,
                "plan": plan}
        if body.session_date:
            data["session_date"] = body.session_date.isoformat()
        return call(store.create_session, p.token, org_id, p.user_id, data)

    @app.get(base + "/{session_id}", tags=["production"])
    def get_session(org_id: str, session_id: str, p: Principal = Depends(principal)):
        org_id = membership(org_id, p)
        return load(org_id, session_id, p)

    @app.patch(base + "/{session_id}", tags=["production"])
    def update_session(org_id: str, session_id: str, body: SessionUpdate, p: Principal = Depends(principal)):
        org_id = membership(org_id, p, write=True)
        fields = body.model_dump(exclude_none=True)
        if not fields:
            raise HTTPException(422, "Rien à modifier.")
        return call(store.update_session, p.token, org_id, uid(session_id, "Session"), fields)

    @app.get(base + "/{session_id}/entries", tags=["production"])
    def list_entries(org_id: str, session_id: str, p: Principal = Depends(principal)):
        org_id = membership(org_id, p)
        return call(store.list_entries, p.token, org_id, uid(session_id, "Session"))

    @app.post(base + "/{session_id}/entries", tags=["production"])
    def add_entries(org_id: str, session_id: str, body: EntriesBatch, p: Principal = Depends(principal)):
        org_id = membership(org_id, p, write=True)
        session = load(org_id, session_id, p)
        if session.get("status") != "open":
            raise HTTPException(409, "Session fermée : saisie impossible.")
        stations = {s["station"] for s in (session.get("plan") or {}).get("stations", [])}
        rows = []
        for e in body.entries:
            if stations and e.station not in stations:
                raise HTTPException(422, f"Station {e.station} inconnue dans cette session.")
            d = e.model_dump(mode="json", exclude_none=True)
            when = e.entered_at or datetime.now(timezone.utc)
            if e.slot_hour is None:
                d["slot_hour"] = production.local_hour(session, when if when.tzinfo else when.replace(tzinfo=timezone.utc))
            if e.downtime_reason is None:
                d.pop("downtime_start", None)
                d.pop("downtime_minutes", None)
            rows.append(d)
        saved = call(store.upsert_entries, p.token, session["id"], rows)
        return {"saved": len(saved), "entries": saved}

    @app.patch(base + "/{session_id}/entries/{entry_id}", tags=["production"])
    def patch_entry(org_id: str, session_id: str, entry_id: str, body: EntryPatch,
                    p: Principal = Depends(principal)):
        org_id = membership(org_id, p, write=True)
        fields = body.model_dump(exclude_unset=True)
        if not fields:
            raise HTTPException(422, "Rien à modifier.")
        return call(store.update_entry, p.token, org_id, uid(session_id, "Session"),
                    uid(entry_id, "Saisie"), fields)

    @app.get(base + "/{session_id}/dashboard", tags=["production"])
    def get_dashboard(org_id: str, session_id: str, p: Principal = Depends(principal)):
        org_id = membership(org_id, p)
        session = load(org_id, session_id, p)
        entries = call(store.list_entries, p.token, org_id, session["id"])
        return production.dashboard(session, entries)

    def _report(org_id: str, session_id: str, p: Principal):
        org_id = membership(org_id, p)
        session = load(org_id, session_id, p)
        entries = call(store.list_entries, p.token, org_id, session["id"])
        return session, entries, production.dashboard(session, entries), org_name(org_id, p)

    def _fname(session: dict, ext: str) -> str:
        return f'production_{session.get("session_date", "")}_{str(session["id"])[:8]}.{ext}'

    @app.get(base + "/{session_id}/export.xlsx", tags=["production"])
    def export_xlsx(org_id: str, session_id: str, p: Principal = Depends(principal)):
        session, entries, dash, name = _report(org_id, session_id, p)
        return Response(production.build_xlsx(session, dash, entries, name),
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{_fname(session, "xlsx")}"'})

    @app.get(base + "/{session_id}/export.pdf", tags=["production"])
    def export_pdf(org_id: str, session_id: str, p: Principal = Depends(principal)):
        session, _entries, dash, name = _report(org_id, session_id, p)
        return Response(production.build_pdf(session, dash, name), media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{_fname(session, "pdf")}"'})
