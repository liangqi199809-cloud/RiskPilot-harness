"""Typed request bodies for the public V2 HTTP surface."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HistoricalRequest(StrictRequest):
    as_of: datetime
    snapshot_id: str | None = None


class StockRequest(HistoricalRequest):
    stock_code: str = Field(pattern=r"^\d{6}$")


class RiskBudgetRequest(StockRequest):
    stock_name: str
    capital: float
    max_loss: float
    current_price: float
    atr_14: float
    key_support: float
    board: str = "main"


class DrawCaseRequest(HistoricalRequest):
    stock_code: str | None = Field(default=None, pattern=r"^\d{6}$")
    industry: str | None = None
    decision_mode: str = "monthly"
    capital: float = 100000
    max_loss: float = 2000
    faction: str | None = None


class ReplayPreviewRequest(HistoricalRequest):
    experiment_id: str
    expected_step: int = Field(ge=0)
    target_value: float


class ReplaySessionRequest(HistoricalRequest):
    experiment_id: str


class ReplayActionRequest(HistoricalRequest):
    experiment_id: str
    expected_step: int = Field(ge=0)
    idempotency_key: str = Field(min_length=1, max_length=128)
    target_value: float | None = None


class SubmitScoreRequest(HistoricalRequest):
    experiment_id: str
    display_name: str = Field(min_length=1, max_length=24)
    avatar: str = Field(default="🎮", max_length=16)
    faction: str = Field(default="jin", max_length=32)


class LeaderboardRequest(HistoricalRequest):
    limit: int = Field(default=20, ge=1, le=100)


class ReportCreateRequest(StockRequest):
    snapshot_id: str = Field(min_length=1, max_length=160)
    capital: float = Field(gt=0)
    max_loss: float = Field(gt=0)
    idempotency_key: str = Field(min_length=1, max_length=128)


class ReportRequest(HistoricalRequest):
    report_id: str = Field(min_length=1, max_length=64)


class ReportListRequest(HistoricalRequest):
    limit: int = Field(default=20, ge=1, le=100)

