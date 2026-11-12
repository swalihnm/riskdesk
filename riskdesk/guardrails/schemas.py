"""Pydantic schemas. Every agent step returns one of these; free text never leaves the graph unvalidated."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Classification(str, Enum):
    MARKET_MOVE = "market_move"
    DATA_ISSUE = "data_issue"
    LIMIT_ERROR = "limit_error"


class BreachFinding(BaseModel):
    desk: str
    metric: str
    value: float
    limit: float
    utilisation: float
    status: str


class Driver(BaseModel):
    underlying: str
    component_var: float
    share: float = Field(ge=-10, le=10)


class Attribution(BaseModel):
    drivers: list[Driver]
    margin_ratio: float  # top driver / runner-up
    data_flags: list[str] = []


class InvestigationReport(BaseModel):
    desk: str
    metric: str
    classification: Classification
    top_driver: str | None
    confidence: float = Field(ge=0, le=1)
    escalate: bool
    summary: str
    citations: list[str]
    prompt_version: str
    drafter: str


class ApprovalItem(BaseModel):
    id: str
    kind: str  # "investigation_report" | "limit_change_proposal" | "human_review"
    desk: str
    status: str = "pending"  # pending | approved | rejected
    payload: dict
    decided_by: str | None = None
    note: str | None = None
