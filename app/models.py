from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ExceptionStatus(str, Enum):
    OPEN = "open"
    PENDING_APPROVAL = "pending_approval"
    RESOLVED = "resolved"


class EvidenceItem(BaseModel):
    source: str
    fact: str
    raw_reference: str | None = None


class ResolutionRecommendation(BaseModel):
    exception_id: str
    category: str
    summary: str
    recommended_action: str
    confidence: float = Field(ge=0, le=1)
    risk_level: RiskLevel
    human_approval_required: bool
    evidence: list[EvidenceItem]


class ApprovalRequest(BaseModel):
    approved: bool
    approver: str
    comment: str | None = None


class AuditEvent(BaseModel):
    event_type: str
    exception_id: str
    details: dict[str, Any]
