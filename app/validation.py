import math

from pydantic import ValidationError

from app.errors import InvalidProviderOutput
from app.models import ProviderRecommendation, ReasoningContext, ResolutionRecommendation


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
