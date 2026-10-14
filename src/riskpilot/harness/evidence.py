"""Evidence boundary shared by data tools and audit records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True, slots=True)
class EvidenceContext:
    """Identifies exactly which evidence was visible for a calculation."""

    snapshot_id: str
    as_of: datetime
    source: str
    license_status: str
    file_hashes: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None or self.as_of.utcoffset() is None:
            raise ValueError("as_of must include timezone information")
        if not self.snapshot_id.strip():
            raise ValueError("snapshot_id must not be empty")
        object.__setattr__(self, "file_hashes", MappingProxyType(dict(self.file_hashes)))

