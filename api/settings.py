"""Configuration par variables d'environnement (préfixe TLB_)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _env(*names: str) -> str:
    for n in names:
        v = os.environ.get(n, "").strip()
        if v:
            return v
    return ""


@dataclass
class Settings:
    # Clés API autorisées, séparées par des virgules. Vide = auth désactivée (dev).
    api_keys: set[str] = field(default_factory=set)
    # Limite de temps max (s) d'un calcul synchrone (POST /v1/balance).
    sync_time_limit: int = 15
    # Limite de temps max (s) d'un calcul en file (POST /v1/jobs).
    job_time_limit: int = 300
    # Nombre de calculs simultanés dans la file.
    job_workers: int = 2
    # Taille max d'un fichier importé (octets).
    max_upload_bytes: int = 5 * 1024 * 1024
    # Nombre max d'opérations par problème (garde-fou CPU).
    max_operations: int = 500
    # Supabase (comptes, ateliers, historique). Vide = mode sans compte.
    supabase_url: str = ""
    supabase_anon_key: str = ""        # clé publishable (sb_publishable_…) ou anon
    supabase_service_key: str = ""     # optionnelle : mise à jour des calculs longs
    supabase_jwt_secret: str = ""      # optionnelle : jetons HS256 historiques
    # Origines autorisées pour le navigateur (CORS), séparées par des virgules.
    cors_origins: list[str] = field(default_factory=list)

    @property
    def supabase_enabled(self) -> bool:
        return bool(self.supabase_url and self.supabase_anon_key)

    @classmethod
    def from_env(cls) -> "Settings":
        keys = {k.strip() for k in os.environ.get("TLB_API_KEYS", "").split(",") if k.strip()}
        return cls(
            api_keys=keys,
            sync_time_limit=_int("TLB_SYNC_TIME_LIMIT", 15),
            job_time_limit=_int("TLB_JOB_TIME_LIMIT", 300),
            job_workers=_int("TLB_JOB_WORKERS", 2),
            max_upload_bytes=_int("TLB_MAX_UPLOAD_BYTES", 5 * 1024 * 1024),
            max_operations=_int("TLB_MAX_OPERATIONS", 500),
            supabase_url=_env("TLB_SUPABASE_URL", "SUPABASE_URL"),
            supabase_anon_key=_env("TLB_SUPABASE_ANON_KEY", "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_ANON_KEY"),
            supabase_service_key=_env("TLB_SUPABASE_SERVICE_KEY", "SUPABASE_SECRET_KEY"),
            supabase_jwt_secret=_env("TLB_SUPABASE_JWT_SECRET", "SUPABASE_JWT_SECRET"),
            cors_origins=[o.strip() for o in os.environ.get("TLB_CORS_ORIGINS", "").split(",") if o.strip()],
        )
