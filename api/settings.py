"""Configuration par variables d'environnement (préfixe TLB_)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


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
        )
