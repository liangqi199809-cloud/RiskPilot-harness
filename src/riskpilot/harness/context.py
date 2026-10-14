"""Identity, product, and historical boundaries shared by every tool call."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping
from uuid import uuid4


class ProductScenario(StrEnum):
    CONSUMER_EDUCATION = "consumer_education"
    INSTITUTION_TRAINING = "institution_training"
    PORTFOLIO_DEMO = "portfolio_demo"
    RESEARCH_SANDBOX = "research_sandbox"


@dataclass(frozen=True, slots=True)
class RuntimeContext:
    """Immutable execution boundary passed to Harness tools and policies."""

    user_id: str
    entrypoint: str
    scenario: ProductScenario
    as_of: datetime
    trace_id: str = field(default_factory=lambda: str(uuid4()))
    experiment_id: str | None = None
    snapshot_id: str | None = None
    permissions: frozenset[str] = field(default_factory=frozenset)
    attributes: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.user_id.strip():
            raise ValueError("user_id must not be empty")
        if not self.entrypoint.strip():
            raise ValueError("entrypoint must not be empty")
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of must include timezone information")
        if not self.trace_id.strip():
            raise ValueError("trace_id must not be empty")
        object.__setattr__(self, "permissions", frozenset(self.permissions))
        object.__setattr__(self, "attributes", MappingProxyType(dict(self.attributes)))

