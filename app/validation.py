import math

from pydantic import ValidationError

from app.errors import InvalidProviderOutput
from app.models import (
    ActionTarget, ExecutionMode, ProviderRecommendation, ProposedActionType,
    ReasoningContext, ResolutionRecommendation,
)


def _valid_action_proposal(draft: ProviderRecommendation) -> bool:
    proposal = draft.action_proposal
    if (
        not proposal.requires_approval
        or proposal.execution_mode != ExecutionMode.RECORD_ONLY
        or proposal.requires_approval != draft.human_approval_required
    ):
        return False
    if proposal.action_type == ProposedActionType.REQUEST_DOCUMENT:
        return (
            proposal.document_type is not None
            and proposal.target_system == ActionTarget.DOCUMENT_REQUEST_WORKFLOW
            and proposal.supported
        )
    if proposal.action_type == ProposedActionType.MANUAL_INVESTIGATION:
        return (
            proposal.document_type is None
            and proposal.target_system == ActionTarget.LOGISTICS_OPERATIONS
            and not proposal.supported
        )
    return (
        proposal.action_type == ProposedActionType.MONITOR_SHIPMENT
        and proposal.document_type is None
        and proposal.target_system == ActionTarget.SHIPMENT_MONITORING
        and not proposal.supported
    )


def validate_recommendation(
    draft: ProviderRecommendation, context: ReasoningContext, run_id: str, provider: str,
) -> ResolutionRecommendation:
    catalogue = {item.evidence_id: item for item in context.evidence}
    references = draft.cause_evidence_ids + draft.action_evidence_ids
    if (
        not math.isfinite(draft.confidence) or not 0 <= draft.confidence <= 1
        or any(not text.strip() for text in (draft.category, draft.summary, draft.recommended_action))
        or not draft.cause_evidence_ids or not draft.action_evidence_ids
        or any(reference not in catalogue for reference in references)
        or not _valid_action_proposal(draft)
    ):
        raise InvalidProviderOutput()
    try:
        return ResolutionRecommendation(
            exception_id=context.exception["exception_id"], run_id=run_id, provider=provider,
            evidence=[item for item in context.evidence if item.evidence_id in references],
            **draft.model_dump(),
        )
    except ValidationError:
        raise InvalidProviderOutput() from None
