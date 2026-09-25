from enum import Enum
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ExceptionStatus(str, Enum):
    OPEN = "open"
    PENDING_APPROVAL = "pending_approval"
    RESOLVED = "resolved"


class DocumentType(str, Enum):
    COMMERCIAL_INVOICE = "commercial_invoice"
    CERTIFICATE_OF_ORIGIN = "certificate_of_origin"
    PACKING_LIST = "packing_list"
    OTHER = "other"


class ProposedActionType(str, Enum):
    REQUEST_DOCUMENT = "request_document"
    MANUAL_INVESTIGATION = "manual_investigation"
    MONITOR_SHIPMENT = "monitor_shipment"


class ActionTarget(str, Enum):
    DOCUMENT_REQUEST_WORKFLOW = "document_request_workflow"
    LOGISTICS_OPERATIONS = "logistics_operations"
    SHIPMENT_MONITORING = "shipment_monitoring"


class ExecutionMode(str, Enum):
    RECORD_ONLY = "record_only"


class ActionProposal(BaseModel):
    """Typed advisory proposal. It is not an approval or execution instruction."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    action_type: ProposedActionType
    document_type: DocumentType | None
    target_system: ActionTarget
    requires_approval: bool
    execution_mode: ExecutionMode
    supported: bool


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
    action_proposal: ActionProposal
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
    action_proposal: ActionProposal
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


class RequestDocumentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    exception_id: str = Field(min_length=1)
    document_type: DocumentType
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("exception_id", "reason")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class ActionIntent(BaseModel):
    model_config = ConfigDict(frozen=True)
    action_id: str
    action_type: str
    exception_id: str
    order_id: str
    shipment_id: str
    document_type: DocumentType
    reason: str
    status: str
    created_at: str


class DemoStatus(BaseModel):
    model_config = ConfigDict(frozen=True)
    version: str
    reasoner_provider: str
    connector_mode: str
    action_mode: str = "record_only"
