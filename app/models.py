from enum import Enum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ExceptionStatus(str, Enum):
    OPEN = "open"
    PENDING_APPROVAL = "pending_approval"
    RESOLVED = "resolved"


class EvidenceItem(BaseModel):
    model_config = ConfigDict(frozen=True)
    evidence_id: str
    source: str
    fact: str
    raw_reference: str | None = None


class ResolutionRecommendation(BaseModel):
    run_id: str
    provider: str
    exception_id: str
    category: str
    summary: str
    recommended_action: str
    confidence: float = Field(ge=0, le=1)
    risk_level: RiskLevel
    human_approval_required: bool
    evidence: list[EvidenceItem]
    cause_evidence_ids: list[str]
    action_evidence_ids: list[str]


class ProviderRecommendation(BaseModel):
    """Azure-compatible wire schema; bounds and citations are checked locally."""

    model_config = ConfigDict(extra="forbid")
    category: str
    summary: str
    recommended_action: str
    confidence: float
    risk_level: RiskLevel
    human_approval_required: bool
    cause_evidence_ids: list[str]
    action_evidence_ids: list[str]


class ReasoningContext(BaseModel):
    model_config = ConfigDict(frozen=True)
    exception: dict[str, Any]
    order: dict[str, Any]
    shipment: dict[str, Any]
    note: dict[str, Any]
    evidence: tuple[EvidenceItem, ...]


class ReasonerResult(BaseModel):
    recommendation: ProviderRecommendation
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApprovalRequest(BaseModel):
    approved: bool
    approver: str
    comment: str | None = None


class AuditEvent(BaseModel):
    timestamp: str
    run_id: str
    sequence: int
    event_type: str
    exception_id: str
    details: dict[str, Any]
