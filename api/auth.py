"""Authentification par jeton Supabase (JWT d'accès d'un utilisateur connecté).

Le jeton est vérifié localement avec la clé publique du projet (JWKS, ES256/RS256),
mise en cache ; option HS256 pour les projets à secret JWT historique.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import jwt


class AuthError(Exception):
    pass


@dataclass(frozen=True)
class Principal:
    user_id: str
    email: str
    token: str


class SupabaseAuth:
    def __init__(self, supabase_url: str, *, jwt_secret: str = "",
                 jwk_client: Optional[jwt.PyJWKClient] = None) -> None:
        base = supabase_url.rstrip("/")
        self.issuer = f"{base}/auth/v1"
        self.jwt_secret = jwt_secret
        self._jwks = jwk_client or jwt.PyJWKClient(
            f"{self.issuer}/.well-known/jwks.json", cache_keys=True, lifespan=600)

    def verify(self, token: str) -> Principal:
        try:
            header = jwt.get_unverified_header(token)
            alg = header.get("alg", "")
            if alg == "HS256":
                if not self.jwt_secret:
                    raise AuthError("Jeton HS256 non accepté (secret JWT non configuré).")
                key = self.jwt_secret
            elif alg in ("ES256", "RS256"):
                key = self._jwks.get_signing_key_from_jwt(token).key
            else:
                raise AuthError(f"Algorithme de jeton non supporté : {alg or '?'}")
            claims = jwt.decode(token, key, algorithms=[alg], audience="authenticated",
                                issuer=self.issuer, leeway=30,
                                options={"require": ["exp", "sub"]})
        except AuthError:
            raise
        except jwt.ExpiredSignatureError:
            raise AuthError("Session expirée, reconnectez-vous.")
        except Exception as e:  # noqa: BLE001
            raise AuthError(f"Jeton invalide : {e}")
        if claims.get("role") != "authenticated":
            raise AuthError("Jeton non associé à un utilisateur connecté.")
        return Principal(user_id=str(claims["sub"]), email=str(claims.get("email", "")), token=token)
