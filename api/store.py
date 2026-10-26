"""Persistance Supabase (PostgREST) : ateliers, lignes, gammes, historique des calculs.

Chaque requête part avec le jeton de l'utilisateur : la sécurité multi-ateliers
est appliquée par les politiques RLS de Postgres (voir supabase/migrations/),
l'API n'a donc jamais besoin de la clé service_role pour lire ou écrire.
Exception optionnelle : la mise à jour d'un calcul long peut utiliser la clé
service (TLB_SUPABASE_SERVICE_KEY) si le jeton utilisateur risque d'expirer.
"""
from __future__ import annotations

from typing import Any, Optional

import httpx


class StoreError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status, self.message = status, message


_RUN_SUMMARY = ("id,org_id,problem_id,kind,solver,status,success,compliant,stations_used,"
                "actual_cycle_time,efficiency,min_cycle_time,error,created_by,created_at,"
                "started_at,finished_at,params")


class SupabaseStore:
    def __init__(self, supabase_url: str, anon_key: str, *, service_key: str = "",
                 client: Optional[httpx.Client] = None, timeout: float = 15.0) -> None:
        self.anon_key, self.service_key = anon_key, service_key
        self._http = client or httpx.Client(base_url=supabase_url.rstrip("/") + "/rest/v1",
                                            timeout=timeout)

    # ------------------------------------------------------------ bas niveau
    def _headers(self, token: str, prefer: str = "") -> dict[str, str]:
        h = {"apikey": self.anon_key, "Authorization": f"Bearer {token}"}
        if prefer:
            h["Prefer"] = prefer
        return h

    def _req(self, method: str, path: str, token: str, *, params=None, json=None,
             prefer: str = "", single: bool = False) -> Any:
        headers = self._headers(token, prefer)
        if single:
            headers["Accept"] = "application/vnd.pgrst.object+json"
        r = self._http.request(method, path, params=params, json=json, headers=headers)
        if r.status_code >= 400:
            raise _to_error(r, single)
        return r.json() if r.content else None

    # ------------------------------------------------------------ ateliers
    def my_orgs(self, token: str, user_id: str) -> list[dict]:
        rows = self._req("GET", "/memberships", token, params={
            "select": "role,org:organizations(id,name,country,created_at,"
                      "subscription:subscriptions(plan_code,status,trial_ends_at,current_period_end))",
            "user_id": f"eq.{user_id}", "order": "created_at.asc"})
        out = []
        for r in rows:
            org = dict(r["org"])
            org["role"] = r["role"]
            out.append(org)
        return out

    def create_org(self, token: str, name: str, country: str = "TN") -> dict:
        return self._req("POST", "/rpc/create_organization", token,
                         json={"p_name": name, "p_country": country})

    def member_role(self, token: str, org_id: str, user_id: str) -> Optional[str]:
        rows = self._req("GET", "/memberships", token, params={
            "select": "role", "org_id": f"eq.{org_id}", "user_id": f"eq.{user_id}"})
        return rows[0]["role"] if rows else None

    def org_plan(self, token: str, org_id: str) -> Optional[dict]:
        rows = self._req("GET", "/subscriptions", token, params={
            "select": "plan_code,status,trial_ends_at,current_period_end,plan:plans(*)",
            "org_id": f"eq.{org_id}"})
        return rows[0] if rows else None

    def list_members(self, token: str, org_id: str) -> list[dict]:
        return self._req("GET", "/memberships", token, params={
            "select": "user_id,role,created_at", "org_id": f"eq.{org_id}", "order": "created_at.asc"})

    # ------------------------------------------------------------ super admin (fonctions SQL contrôlées)
    def rpc(self, token: str, name: str, args: Optional[dict] = None) -> Any:
        return self._req("POST", f"/rpc/{name}", token, json=args or {})

    def is_super_admin(self, token: str) -> bool:
        return bool(self.rpc(token, "admin_whoami"))

    # ------------------------------------------------------------ lignes
    def list_lines(self, token: str, org_id: str) -> list[dict]:
        return self._req("GET", "/lines", token, params={
            "select": "*", "org_id": f"eq.{org_id}", "order": "created_at.asc"})

    def create_line(self, token: str, org_id: str, user_id: str, data: dict) -> dict:
        rows = self._req("POST", "/lines", token, json={**data, "org_id": org_id, "created_by": user_id},
                         prefer="return=representation")
        return rows[0]

    def delete_line(self, token: str, org_id: str, line_id: str) -> bool:
        rows = self._req("DELETE", "/lines", token, params={"id": f"eq.{line_id}", "org_id": f"eq.{org_id}"},
                         prefer="return=representation")
        return bool(rows)

    # ------------------------------------------------------------ gammes (problèmes)
    def create_problem(self, token: str, org_id: str, user_id: str, problem: dict,
                       line_id: Optional[str] = None) -> dict:
        body = {"org_id": org_id, "created_by": user_id, "line_id": line_id,
                "name": problem.get("name", "ligne"), "target_cycle_time": problem["target_cycle_time"],
                "operations_count": len(problem.get("operations", [])), "payload": problem}
        rows = self._req("POST", "/problems", token, json=body, prefer="return=representation")
        return rows[0]

    def list_problems(self, token: str, org_id: str, line_id: Optional[str] = None,
                      limit: int = 50) -> list[dict]:
        params = {"select": "id,org_id,line_id,name,target_cycle_time,operations_count,created_by,created_at",
                  "org_id": f"eq.{org_id}", "order": "created_at.desc", "limit": str(limit)}
        if line_id:
            params["line_id"] = f"eq.{line_id}"
        return self._req("GET", "/problems", token, params=params)

    def get_problem(self, token: str, org_id: str, problem_id: str) -> dict:
        return self._req("GET", "/problems", token, single=True, params={
            "select": "*", "id": f"eq.{problem_id}", "org_id": f"eq.{org_id}"})

    # ------------------------------------------------------------ calculs
    def create_run(self, token: str, org_id: str, user_id: str, *, kind: str, solver: str,
                   params: dict, problem_id: Optional[str]) -> dict:
        rows = self._req("POST", "/runs", token, prefer="return=representation", json={
            "org_id": org_id, "created_by": user_id, "kind": kind, "solver": solver,
            "params": params, "problem_id": problem_id, "status": "queued"})
        return rows[0]

    def update_run(self, token: str, run_id: str, fields: dict) -> None:
        headers = self._headers(token, "return=minimal")
        if self.service_key:
            headers["apikey"] = self.service_key
            if self.service_key.startswith("sb_secret_"):   # nouvelle clé : en-tête apikey seul
                headers.pop("Authorization")
            else:                                           # ancienne clé service_role (JWT)
                headers["Authorization"] = f"Bearer {self.service_key}"
        r = self._http.patch("/runs", params={"id": f"eq.{run_id}"}, json=fields, headers=headers)
        if r.status_code >= 400:
            raise _to_error(r, False)

    def list_runs(self, token: str, org_id: str, problem_id: Optional[str] = None,
                  limit: int = 50) -> list[dict]:
        params = {"select": _RUN_SUMMARY, "org_id": f"eq.{org_id}", "order": "created_at.desc",
                  "limit": str(limit)}
        if problem_id:
            params["problem_id"] = f"eq.{problem_id}"
        return self._req("GET", "/runs", token, params=params)

    def get_run(self, token: str, org_id: str, run_id: str) -> dict:
        return self._req("GET", "/runs", token, single=True, params={
            "select": _RUN_SUMMARY + ",result", "id": f"eq.{run_id}", "org_id": f"eq.{org_id}"})


def _to_error(r: httpx.Response, single: bool) -> StoreError:
    try:
        body = r.json()
    except Exception:  # noqa: BLE001
        body = {}
    code, msg = body.get("code", ""), body.get("message") or r.text[:200]
    if single and code == "PGRST116":
        return StoreError(404, "Introuvable.")
    if code == "P0001":            # quotas / abonnement (exceptions SQL métier)
        return StoreError(402 if "Abonnement" in msg else 409, msg)
    if code == "42501" or r.status_code == 403:
        return StoreError(403, "Action non autorisée pour votre rôle dans cet atelier.")
    if code == "P0002":            # introuvable (fonctions d'administration)
        return StoreError(404, msg)
    if code in ("22P02", "23503", "23514", "23502", "22023"):
        return StoreError(422, msg)
    if r.status_code == 401:
        return StoreError(401, "Session invalide ou expirée.")
    return StoreError(502, f"Erreur base de données : {msg}")
