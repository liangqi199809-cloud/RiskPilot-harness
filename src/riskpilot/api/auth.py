"""Fail-closed bearer-token identity boundary for the first V2 API."""

from __future__ import annotations

from dataclasses import dataclass, field
import hmac
import json
import os
from typing import Mapping, Protocol


class IdentityConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AuthenticatedIdentity:
    user_id: str
    permissions: frozenset[str] = frozenset()


class IdentityResolver(Protocol):
    def resolve(self, bearer_token: str) -> AuthenticatedIdentity | None: ...


@dataclass(frozen=True, slots=True)
class StaticBearerIdentityResolver:
    """Development adapter; replace with verified WeChat login before release."""

    identities: Mapping[str, AuthenticatedIdentity] = field(repr=False)

    def __post_init__(self) -> None:
        if not self.identities:
            raise IdentityConfigurationError("at least one API identity must be configured")
        if any(not token.strip() for token in self.identities):
            raise IdentityConfigurationError("API bearer tokens must not be empty")
        if any(not identity.user_id.strip() for identity in self.identities.values()):
            raise IdentityConfigurationError("API user IDs must not be empty")

    def resolve(self, bearer_token: str) -> AuthenticatedIdentity | None:
        for expected, identity in self.identities.items():
            if hmac.compare_digest(expected.encode("utf-8"), bearer_token.encode("utf-8")):
                return identity
        return None


def identity_resolver_from_environment() -> IdentityResolver | None:
    """Read a JSON token-to-user map without ever logging or persisting tokens."""

    raw = os.environ.get("RISKPILOT_API_TOKENS_JSON", "").strip()
    if not raw:
        return None
    try:
        values = json.loads(raw)
        if not isinstance(values, dict):
            raise TypeError("token map must be a JSON object")
        identities = {
            str(token): AuthenticatedIdentity(user_id=str(user_id))
            for token, user_id in values.items()
            if str(token).strip() and str(user_id).strip()
        }
    except (TypeError, ValueError) as exc:
        raise IdentityConfigurationError("RISKPILOT_API_TOKENS_JSON is invalid") from exc
    return StaticBearerIdentityResolver(identities)

