"""Routes « plan d'atelier » (cartographie) : plans, inventaire des machines, placement d'un calcul.

  GET    /v1/orgs/{org}/workshop-plans                    plans de l'atelier (résumé)
  POST   /v1/orgs/{org}/workshop-plans                    créer un plan
  GET    /v1/orgs/{org}/workshop-plans/{pid}              plan complet (éléments, fond, réglages)
  PUT    /v1/orgs/{org}/workshop-plans/{pid}              modifier
  DELETE /v1/orgs/{org}/workshop-plans/{pid}              supprimer
  GET    /v1/orgs/{org}/workshop-plans/{pid}/inventory    postes (WS) déduits des machines + temps de déplacement
  GET    /v1/orgs/{org}/workshop-catalog                  bibliothèque de machines et zones

Le fond de plan (image) est déposé par le navigateur dans Supabase Storage (bucket privé
« workshop-plans », dossier <org_id>/), sous RLS ; l'API ne stocke que son chemin.
Géométrie : engine/workshop.py.
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException

from api.auth import Principal, SupabaseAuth
from api.routes_saas import WRITE_ROLES, bearer_principal
from api.schemas import WorkshopPlanIn, WorkshopPlanPatch
from api.store import StoreError, SupabaseStore
from engine import workshop

DELETE_ROLES = {"owner", "admin", "methodes"}


def placement(stations: list[dict], plan_row: dict, assignment: Optional[dict] = None) -> dict:
    """Implantation de simulation d'un calcul sur un plan + analyse (pour le jumeau numérique)."""
    auto = workshop.auto_assign(stations, plan_row, assignment)
    lay = workshop.plan_layout(stations, plan_row, auto["assignment"])
    return {
        "layout": {"kind": lay["kind"], "positions": lay["positions"], "distances": lay["distances"],
                   "plan_id": plan_row["id"], "assignment": auto["assignment"]},
        "plan_id": plan_row["id"], "plan_name": plan_row.get("name", ""),
        "assignment": auto["assignment"], "missing": auto["missing"], "unused": auto["unused"],
        "notes": auto["notes"], "routes": lay["routes"], "virtual": lay["virtual"], "flow": lay["flow"],
        "travel": workshop.derived_travel(plan_row),
    }


def register(app: FastAPI, auth: SupabaseAuth, store: SupabaseStore) -> None:
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

    def membership(org_id: str, p: Principal, roles: Optional[set] = None) -> str:
        org_id = uid(org_id, "Atelier")
        role = call(store.member_role, p.token, org_id, p.user_id)
        if role is None:
            raise HTTPException(404, "Atelier introuvable.")
        if roles is not None and role not in roles:
            raise HTTPException(403, "Votre rôle ne permet pas de modifier le plan de l'atelier.")
        return org_id

    def check_background(org_id: str, bg: Optional[dict]) -> None:
        path = str((bg or {}).get("path") or "")
        if path and path.split("/", 1)[0] != org_id:
            raise HTTPException(422, "Le fond de plan doit être rangé dans le dossier de l'atelier.")

    @app.get("/v1/orgs/{org_id}/workshop-catalog", tags=["plan d'atelier"])
    def catalog(org_id: str, p: Principal = Depends(principal)):
        membership(org_id, p)
        return {"machines": workshop.MACHINE_CATALOG, "zones": workshop.ZONES}

    @app.get("/v1/orgs/{org_id}/workshop-plans", tags=["plan d'atelier"])
    def list_plans(org_id: str, p: Principal = Depends(principal)):
        org_id = membership(org_id, p)
        return call(store.list_plans, p.token, org_id)

    @app.post("/v1/orgs/{org_id}/workshop-plans", status_code=201, tags=["plan d'atelier"])
    def create_plan(org_id: str, body: WorkshopPlanIn, p: Principal = Depends(principal)):
        org_id = membership(org_id, p, WRITE_ROLES)
        check_background(org_id, body.background)
        return call(store.create_plan, p.token, org_id, body.model_dump())

    @app.get("/v1/orgs/{org_id}/workshop-plans/{plan_id}", tags=["plan d'atelier"])
    def get_plan(org_id: str, plan_id: str, p: Principal = Depends(principal)):
        org_id = membership(org_id, p)
        return call(store.get_plan, p.token, org_id, uid(plan_id, "Plan d'atelier"))

    @app.put("/v1/orgs/{org_id}/workshop-plans/{plan_id}", tags=["plan d'atelier"])
    def update_plan(org_id: str, plan_id: str, body: WorkshopPlanPatch, p: Principal = Depends(principal)):
        org_id = membership(org_id, p, WRITE_ROLES)
        fields = body.model_dump(exclude_none=True, exclude={"clear_background"})
        if body.clear_background:
            fields["background"] = None
        check_background(org_id, fields.get("background"))
        if not fields:
            raise HTTPException(422, "Rien à modifier.")
        return call(store.update_plan, p.token, org_id, uid(plan_id, "Plan d'atelier"), fields)

    @app.delete("/v1/orgs/{org_id}/workshop-plans/{plan_id}", status_code=204, tags=["plan d'atelier"])
    def delete_plan(org_id: str, plan_id: str, p: Principal = Depends(principal)):
        org_id = membership(org_id, p, DELETE_ROLES)
        if not call(store.delete_plan, p.token, org_id, uid(plan_id, "Plan d'atelier")):
            raise HTTPException(404, "Plan d'atelier introuvable.")

    @app.get("/v1/orgs/{org_id}/workshop-plans/{plan_id}/inventory", tags=["plan d'atelier"])
    def inventory(org_id: str, plan_id: str, p: Principal = Depends(principal)):
        org_id = membership(org_id, p)
        plan = call(store.get_plan, p.token, org_id, uid(plan_id, "Plan d'atelier"))
        ws = workshop.inventory_workstations(plan)
        by_type: dict[str, dict] = {}
        for w in ws:
            t = by_type.setdefault(w["machine_type"], {"service": 0, "hors_service": 0})
            t["service" if w["available"] else "hors_service"] += 1
        return {"plan_id": plan["id"], "workstations": ws, "by_type": by_type,
                "travel": workshop.derived_travel(plan)}
