"""Routes du super administrateur (propriétaire du SaaS) : /v1/admin/*.

Double contrôle : l'API vérifie le jeton Supabase puis le rôle (fonction SQL
private.is_super_admin(), rôle stocké côté serveur dans private.platform_admins) ;
chaque fonction SQL d'administration refait elle-même le contrôle. Aucune clé
secrète n'est utilisée : les appels partent avec le jeton de l'utilisateur.

  GET    /v1/admin/overview                 gains (TND) par mois / par offre, abonnements, essais
  GET    /v1/admin/users                    utilisateurs (+ ateliers, nb de calculs, statut)
  POST   /v1/admin/users/{id}/suspend       {"suspended": true|false}
  DELETE /v1/admin/users/{id}               {"confirm_email": "..."} (supprime aussi ses ateliers sans autre propriétaire)
  GET    /v1/admin/orgs                     ateliers (offre, statut, nb de calculs, total payé)
  PUT    /v1/admin/orgs/{id}/plan           changer l'offre / le statut
  DELETE /v1/admin/orgs/{id}                {"confirm_name": "..."}
  GET    /v1/admin/payments                 paiements saisis
  POST   /v1/admin/payments                 saisie manuelle d'un paiement (active l'offre par défaut)
  DELETE /v1/admin/payments/{id}
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional
from uuid import UUID

from fastapi import Body, Depends, FastAPI, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field, model_validator

from api.auth import Principal, SupabaseAuth
from api.routes_saas import bearer_principal
from api.store import StoreError, SupabaseStore

PlanCode = Literal["essai", "atelier", "usine", "groupe"]
SubStatus = Literal["trialing", "active", "past_due", "canceled"]
Method = Literal["especes", "virement", "cheque", "carte", "konnect", "flouci", "autre"]


class SuspendIn(BaseModel):
    suspended: bool


class DeleteUserIn(BaseModel):
    confirm_email: str = Field(min_length=3, max_length=320)


class DeleteOrgIn(BaseModel):
    confirm_name: str = Field(min_length=1, max_length=120)


class PlanIn(BaseModel):
    plan_code: PlanCode
    status: SubStatus
    trial_ends_at: Optional[datetime] = None
    current_period_end: Optional[datetime] = None


class PaymentIn(BaseModel):
    org_id: UUID
    plan_code: PlanCode
    amount_tnd: Decimal = Field(ge=0, le=Decimal("10000000"), decimal_places=3)
    paid_at: Optional[date] = None
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    method: Method = "virement"
    reference: str = Field(default="", max_length=200)
    note: str = Field(default="", max_length=1000)
    activate: bool = True   # passer l'atelier sur cette offre, statut actif jusqu'à period_end

    @model_validator(mode="after")
    def _period(self):
        if self.period_start and self.period_end and self.period_end < self.period_start:
            raise ValueError("La fin de période doit être après le début.")
        return self


def register(app: FastAPI, auth: SupabaseAuth, store: SupabaseStore) -> None:
    principal = bearer_principal(auth)

    def admin(p: Principal = Depends(principal)) -> Principal:
        try:
            ok = store.is_super_admin(p.token)
        except StoreError as e:
            raise HTTPException(e.status if e.status in (401, 503) else 502, e.message)
        if not ok:
            raise HTTPException(403, "Réservé au super administrateur.")
        return p

    def rpc(p: Principal, name: str, args: Optional[dict] = None):
        try:
            return store.rpc(p.token, name, args)
        except StoreError as e:
            msg = "Réservé au super administrateur." if e.status == 403 else e.message
            raise HTTPException(e.status, msg)

    def uid(value: str, what: str) -> str:
        try:
            return str(UUID(value))
        except (ValueError, TypeError):
            raise HTTPException(404, f"{what} introuvable.")

    def iso(v) -> Optional[str]:
        return v.isoformat() if v is not None else None

    @app.get("/v1/admin/overview", tags=["super admin"])
    def overview(p: Principal = Depends(admin)):
        return rpc(p, "admin_revenue")

    @app.get("/v1/admin/users", tags=["super admin"])
    def users(p: Principal = Depends(admin)):
        return rpc(p, "admin_users")

    @app.post("/v1/admin/users/{user_id}/suspend", tags=["super admin"])
    def suspend(user_id: str, body: SuspendIn, p: Principal = Depends(admin)):
        return rpc(p, "admin_set_suspended", {"p_user": uid(user_id, "Utilisateur"), "p_suspended": body.suspended})

    @app.delete("/v1/admin/users/{user_id}", tags=["super admin"])
    def delete_user(user_id: str, body: DeleteUserIn = Body(...), p: Principal = Depends(admin)):
        return rpc(p, "admin_delete_user", {"p_user": uid(user_id, "Utilisateur"),
                                            "p_confirm_email": body.confirm_email})

    @app.get("/v1/admin/orgs", tags=["super admin"])
    def orgs(p: Principal = Depends(admin)):
        return rpc(p, "admin_orgs")

    @app.put("/v1/admin/orgs/{org_id}/plan", tags=["super admin"])
    def set_plan(org_id: str, body: PlanIn, p: Principal = Depends(admin)):
        return rpc(p, "admin_set_plan", {"p_org": uid(org_id, "Atelier"), "p_plan": body.plan_code,
                                         "p_status": body.status, "p_trial_ends_at": iso(body.trial_ends_at),
                                         "p_period_end": iso(body.current_period_end)})

    @app.delete("/v1/admin/orgs/{org_id}", tags=["super admin"])
    def delete_org(org_id: str, body: DeleteOrgIn = Body(...), p: Principal = Depends(admin)):
        return rpc(p, "admin_delete_org", {"p_org": uid(org_id, "Atelier"), "p_confirm_name": body.confirm_name})

    @app.get("/v1/admin/payments", tags=["super admin"])
    def payments(limit: int = Query(200, ge=1, le=1000), p: Principal = Depends(admin)):
        return rpc(p, "admin_payments", {"p_limit": limit})

    @app.post("/v1/admin/payments", status_code=201, tags=["super admin"])
    def record_payment(body: PaymentIn, p: Principal = Depends(admin)):
        return rpc(p, "admin_record_payment", {
            "p_org": str(body.org_id), "p_plan": body.plan_code, "p_amount": str(body.amount_tnd),
            "p_paid_at": iso(body.paid_at), "p_period_start": iso(body.period_start),
            "p_period_end": iso(body.period_end), "p_method": body.method,
            "p_reference": body.reference, "p_note": body.note, "p_activate": body.activate})

    @app.delete("/v1/admin/payments/{payment_id}", status_code=204, tags=["super admin"])
    def delete_payment(payment_id: str, p: Principal = Depends(admin)):
        if not rpc(p, "admin_delete_payment", {"p_id": uid(payment_id, "Paiement")}):
            raise HTTPException(404, "Paiement introuvable.")
        return Response(status_code=204)
