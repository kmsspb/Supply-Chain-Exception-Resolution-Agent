from typing import Protocol

from app.models import ProviderRecommendation, ReasonerResult, ReasoningContext, RiskLevel


class Reasoner(Protocol):
    provider: str

    def describe(self) -> dict: ...

    def resolve(self, context: ReasoningContext) -> ReasonerResult: ...


class RuleBasedReasoner:
    """v0.1 classification intentionally retained as the comparison baseline."""

    provider = "rule_based"

    def describe(self) -> dict:
        return {"rule_version": "0.1.0"}

    def resolve(self, context: ReasoningContext) -> ReasonerResult:
        note_text = context.note["text"].lower()
        if "customs" in note_text and ("document" in note_text or "documentation" in note_text):
            category = "customs_documentation"
            summary = "Shipment delay is most likely caused by incomplete customs documentation."
            action = (
                "Request the missing customs document from the responsible party, "
                "then recheck the carrier ETA before updating the customer."
            )
            confidence = 0.93
            risk = RiskLevel.MEDIUM
        else:
            category = "unknown_logistics_exception"
            summary = "The available evidence is insufficient to determine a reliable root cause."
            action = "Escalate to a logistics specialist for manual investigation."
            confidence = 0.45
            risk = RiskLevel.HIGH
        ids = [item.evidence_id for item in context.evidence]
        return ReasonerResult(
            recommendation=ProviderRecommendation(
                category=category, summary=summary, recommended_action=action,
                confidence=confidence, risk_level=risk, human_approval_required=True,
                cause_evidence_ids=ids, action_evidence_ids=ids,
            ),
            metadata=self.describe(),
        )


def create_reasoner(settings=None) -> Reasoner:
    from app.config import Settings
    from app.errors import ConfigurationError

    settings = settings or Settings.from_env()
    if settings.provider == "rule_based":
        return RuleBasedReasoner()
    if settings.provider != "azure_openai":
        raise ConfigurationError()
    from app.azure_reasoner import AzureOpenAIReasoner

    return AzureOpenAIReasoner(settings)
